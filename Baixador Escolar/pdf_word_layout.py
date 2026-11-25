"""Bounded geometric reconstruction into editable Word flow, without OCR.

PDFium access is owned/locked by PdfToDocxService. This module never reads an
external resource, writes a file, or creates a Tk object.
"""

from collections import Counter
from bisect import bisect_right
from contextlib import closing
import ctypes
from dataclasses import dataclass, replace
from io import BytesIO
import math
import re
from statistics import median

import pypdfium2.raw as raw

import docx_writer as w
from pdfium_access import page_matrix, page_objects

MAX_GEOMETRY_CHARS = 100_000
MAX_SEGMENTS = 1500
MAX_GRID_CELLS = 5000


def font_family(name):
    name = re.sub(r"^[A-Z]{6}\+", "", name).casefold().replace(" ", "")
    for needle, family in (
        ("times", "Times New Roman"),
        ("courier", "Courier New"),
        ("cambria", "Cambria"),
        ("calibri", "Calibri"),
        ("verdana", "Verdana"),
        ("tahoma", "Tahoma"),
        ("segoe", "Segoe UI"),
    ):
        if needle in name:
            return family
    return "Arial"


@dataclass(frozen=True)
class Glyph:
    text: str
    left: float
    bottom: float
    right: float
    top: float
    baseline: float
    run: w.Run
    space_before: bool = False
    object_id: int | None = None


@dataclass(frozen=True)
class Line:
    glyphs: tuple[Glyph, ...]

    @property
    def left(self):
        return min(g.left for g in self.glyphs)

    @property
    def right(self):
        return max(g.right for g in self.glyphs)

    @property
    def top(self):
        return max(g.top for g in self.glyphs)

    @property
    def bottom(self):
        return min(g.bottom for g in self.glyphs)

    @property
    def size(self):
        return median(g.run.size for g in self.glyphs)

    @property
    def baseline(self):
        return median(g.baseline for g in self.glyphs)


def path_segments(page, cancel, limit):
    segments = []
    with page_objects(page, cancel=cancel, limit=limit) as objects:
        for entry in objects:
            obj = entry.object
            cancel()
            if obj.type != raw.FPDF_PAGEOBJ_PATH:
                continue
            matrix = entry.matrix
            previous = first = None
            count = raw.FPDFPath_CountSegments(obj)
            limit(0 <= count <= MAX_SEGMENTS)
            for index in range(count):
                segment = raw.FPDFPath_GetPathSegment(obj, index)
                x, y = ctypes.c_float(), ctypes.c_float()
                if not raw.FPDFPathSegment_GetPoint(segment, x, y):
                    continue
                point = matrix.on_point(x.value, y.value)
                kind = raw.FPDFPathSegment_GetType(segment)
                if kind == raw.FPDF_SEGMENT_MOVETO:
                    first = point
                elif kind == raw.FPDF_SEGMENT_LINETO and previous is not None:
                    segments.append((*previous, *point))
                previous = point
                if raw.FPDFPathSegment_GetClose(segment) and first is not None:
                    segments.append((*point, *first))
                limit(len(segments) <= MAX_SEGMENTS)
    return [s for s in segments if all(math.isfinite(v) for v in s)]


def glyphs(page, blocks, segments, cancel, limit):
    frame = page_matrix(page)
    styles = {b.object_id: b for b in blocks if b.text and b.object_id}
    horizontal = [
        (min(x, xx), max(x, xx), (y + yy) / 2)
        for x, y, xx, yy in segments
        if abs(y - yy) < 1 and abs(x - xx) > 3
    ]
    result = []
    space_before = False
    with closing(page.get_textpage()) as textpage:
        count = textpage.count_chars()
        limit(count <= MAX_GEOMETRY_CHARS)
        for index in range(count):
            if index % 64 == 0:
                cancel()
            value = raw.FPDFText_GetUnicode(textpage, index)
            if not 0 < value <= 0x10FFFF:
                continue
            text = (
                "\u00ad"
                if raw.FPDFText_IsHyphen(textpage, index)
                else w.safe_text(chr(value))
            )
            if not text:
                continue
            if text.isspace():
                space_before = True
                continue
            bounds = frame.on_rect(*textpage.get_charbox(index))
            limit(all(math.isfinite(v) and abs(v) <= 5760 for v in bounds))
            obj = raw.FPDFText_GetTextObject(textpage, index)
            identity = ctypes.cast(obj, ctypes.c_void_p).value if obj else None
            block = styles.get(identity)
            size = block.size if block else raw.FPDFText_GetFontSize(textpage, index)
            if not math.isfinite(size) or size <= 0:
                size = 12
            size = min(96, max(6, size))
            x, y = ctypes.c_double(), ctypes.c_double()
            baseline = (
                frame.on_point(x.value, y.value)[1]
                if raw.FPDFText_GetCharOrigin(textpage, index, x, y)
                else bounds[1]
            )
            underline = any(
                left - 1 <= bounds[0]
                and right + 1 >= bounds[2]
                and -0.5 <= bounds[1] - yy <= 3
                for left, right, yy in horizontal
            )
            run = w.Run(
                text,
                size,
                block.bold if block else False,
                block.italic if block else False,
                block.font if block else "Arial",
                block.color if block else "000000",
                underline,
            )
            result.append(Glyph(text, *bounds, baseline, run, space_before, identity))
            space_before = False
    return _deduplicate_overprint(result, cancel)


def _deduplicate_overprint(chars, cancel):
    """Collapse matching overprinted glyphs, never adjacent repeated letters.

    Decorative PDF outlines/shadows can contain three digital text objects for
    each visible letter. Flattening those objects into Word repeats the title.
    Require matching text, size, centers and substantial geometric overlap.
    """
    cells, result = {}, []
    for glyph in chars:
        cancel()
        cx, cy = (glyph.left + glyph.right) / 2, (glyph.bottom + glyph.top) / 2
        x, y = math.floor(cx / 16), math.floor(cy / 16)
        duplicate = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for previous in cells.get((glyph.text, x + dx, y + dy), ()):
                    cancel()
                    if not 0.9 <= glyph.run.size / previous.run.size <= 1.1:
                        continue
                    pcx, pcy = (
                        (previous.left + previous.right) / 2,
                        (previous.bottom + previous.top) / 2,
                    )
                    if max(abs(cx - pcx), abs(cy - pcy)) > max(
                        1, glyph.run.size * 0.16
                    ):
                        continue
                    overlap = max(
                        0,
                        min(glyph.right, previous.right)
                        - max(glyph.left, previous.left),
                    ) * max(
                        0,
                        min(glyph.top, previous.top)
                        - max(glyph.bottom, previous.bottom),
                    )
                    area = min(
                        (glyph.right - glyph.left) * (glyph.top - glyph.bottom),
                        (previous.right - previous.left)
                        * (previous.top - previous.bottom),
                    )
                    if area > 0 and overlap / area >= 0.75:
                        duplicate = True
                        break
                if duplicate:
                    break
            if duplicate:
                break
        if not duplicate:
            cells.setdefault((glyph.text, x, y), []).append(glyph)
            result.append(glyph)
    return result


def reading_lines(chars):
    rows = []
    for glyph in sorted(chars, key=lambda g: (-g.baseline, g.left)):
        found = None
        for row in reversed(rows[-8:]):
            if abs(row[0].baseline - glyph.baseline) <= max(
                1.3, min(row[0].run.size, glyph.run.size) * 0.16
            ):
                found = row
                break
        if found is None:
            rows.append([glyph])
        else:
            found.append(glyph)
    lines = []
    for row in rows:
        row.sort(key=lambda g: g.left)
        group = []
        for glyph in row:
            if group and glyph.left - group[-1].right > max(18, glyph.run.size * 2.2):
                lines.append(Line(tuple(group)))
                group = []
            group.append(glyph)
        if group:
            lines.append(Line(tuple(group)))
    return sorted(lines, key=lambda line: (-line.top, line.left))


def line_runs(line):
    runs = []
    previous = None
    for glyph in line.glyphs:
        value = glyph.text
        if previous is not None:
            gap = glyph.left - previous.right
            if gap > glyph.run.size * 2.2:
                value = " \t" + value
            elif glyph.space_before or (
                glyph.object_id != previous.object_id
                and gap > max(1.2, glyph.run.size * 0.22)
            ):
                value = " " + value
        item = replace(glyph.run, text=value)
        if runs and replace(runs[-1], text="") == replace(item, text=""):
            runs[-1] = replace(runs[-1], text=runs[-1].text + value)
        else:
            runs.append(item)
        previous = glyph
    return tuple(runs)


LIST_START = re.compile(r"^(?:[0-9]{1,3}[.)]|[a-zA-Z][.)]|[•●▪◦\-])\s")


def paragraphs(lines, left, right, cancel, *, previous_bottom=None, body_size=12):
    rows = []
    for line in sorted(lines, key=lambda item: (-item.baseline, item.left)):
        if rows and abs(rows[-1].baseline - line.baseline) < 2:
            rows[-1] = Line(
                tuple(sorted(rows[-1].glyphs + line.glyphs, key=lambda g: g.left))
            )
        else:
            rows.append(line)
    groups = []
    for line in rows:
        cancel()
        text = "".join(r.text for r in line_runs(line))
        previous = groups[-1][-1] if groups and groups[-1] else None
        merge = False
        if previous is not None:
            previous_text = "".join(r.text for r in line_runs(previous))
            merge = (
                0.4 * line.size
                <= previous.baseline - line.baseline
                <= 1.65 * max(previous.size, line.size) + 1
                and abs(line.size - previous.size) < 1
                and abs(line.left - previous.left) <= 1.7 * line.size
                and not LIST_START.match(text)
                and "\t" not in text + previous_text
            )
        if merge:
            groups[-1].append(line)
        else:
            groups.append([line])
    result = []
    previous_leading = 0
    for group in groups:
        first, last = group[0], group[-1]
        runs = list(line_runs(first))
        for line in group[1:]:
            next_runs = line_runs(line)
            end = runs[-1].text
            following = "".join(r.text for r in next_runs)
            remove_hyphen = end.endswith("\u00ad") or (
                end.endswith("-")
                and re.match(
                    r"(?:ç[ãõ]o|ções|mente|dade|tion|sion|ncia|namento)\b", following
                )
            )
            if remove_hyphen:
                runs[-1] = replace(runs[-1], text=end[:-1])
            elif not end.endswith("-"):
                runs.append(replace(next_runs[0], text=" "))
            runs.extend(next_runs)
        alignment = "left"
        center = (first.left + first.right) / 2
        if abs(center - (left + right) / 2) <= 8 and first.left > left + 12:
            alignment = "center"
        elif first.right >= right - 8 and first.left > (left + right) / 2:
            alignment = "right"
        elif (
            len(group) >= 3
            and sum(line.right >= right - 15 for line in group[:-1]) >= len(group) - 2
        ):
            alignment = "both"
        line_height = (
            median([a.baseline - b.baseline for a, b in zip(group, group[1:])])
            if len(group) > 1
            else first.size * 1.12
        )
        line_height = max(first.size * 1.05, min(first.size * 1.8, line_height))
        before = (
            max(0, previous_bottom - first.top - previous_leading)
            if previous_bottom is not None
            else 0
        )
        heading = (
            (0 if first.size >= body_size * 1.6 else 1)
            if first.size >= body_size * 1.28 and len(group) == 1
            else None
        )
        indentation = max(0, min(144, first.left - left)) if alignment == "left" else 0
        hanging = (
            -min(18, indentation + 12)
            if LIST_START.match("".join(r.text for r in runs))
            else 0
        )
        if hanging:
            indentation += -hanging
        result.append(
            w.Paragraph(
                tuple(runs),
                alignment,
                before,
                0,
                line_height,
                indentation,
                hanging,
                0,
                heading,
            )
        )
        previous_bottom = last.bottom
        previous_leading = max(0, line_height - (last.top - last.bottom))
    return result


def clustered(values, tolerance=2):
    groups = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [median(group) for group in groups]


def ruled_tables(segments, chars, cancel, limit):
    hs = [
        (min(x, xx), (y + yy) / 2, max(x, xx))
        for x, y, xx, yy in segments
        if abs(y - yy) < 1 and abs(x - xx) >= 12
    ]
    vs = [
        ((x + xx) / 2, min(y, yy), max(y, yy))
        for x, y, xx, yy in segments
        if abs(x - xx) < 1 and abs(y - yy) >= 12
    ]
    parents = list(range(len(hs) + len(vs)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, (left, y, right) in enumerate(hs):
        cancel()
        for j, (x, bottom, top) in enumerate(vs):
            if left - 2 <= x <= right + 2 and bottom - 2 <= y <= top + 2:
                parents[find(i)] = find(len(hs) + j)
    components = {}
    for i in range(len(parents)):
        components.setdefault(find(i), []).append(i)
    result = []
    used = set()
    for indices in components.values():
        hh = [hs[i] for i in indices if i < len(hs)]
        vv = [vs[i - len(hs)] for i in indices if i >= len(hs)]
        xs = clustered(v[0] for v in vv)
        ys = list(reversed(clustered(h[1] for h in hh)))
        if len(xs) < 3 or len(ys) < 3:
            continue
        columns, rows = len(xs) - 1, len(ys) - 1
        limit(columns <= 64 and rows <= 2000 and columns * rows <= MAX_GRID_CELLS)
        selected = [
            (i, g)
            for i, g in enumerate(chars)
            if xs[0] - 1 <= (g.left + g.right) / 2 <= xs[-1] + 1
            and ys[-1] - 1 <= (g.top + g.bottom) / 2 <= ys[0] + 1
        ]
        if len(selected) < 4:
            continue
        cells = list(range(rows * columns))

        def cell_root(i):
            while cells[i] != i:
                cells[i] = cells[cells[i]]
                i = cells[i]
            return i

        for r in range(rows):
            for c in range(columns):
                cancel()
                if c + 1 < columns and not any(
                    abs(x - xs[c + 1]) < 2
                    and bottom - 1 <= (ys[r] + ys[r + 1]) / 2 <= top + 1
                    for x, bottom, top in vv
                ):
                    cells[cell_root(r * columns + c)] = cell_root(r * columns + c + 1)
                if r + 1 < rows and not any(
                    abs(y - ys[r + 1]) < 2
                    and left - 1 <= (xs[c] + xs[c + 1]) / 2 <= right + 1
                    for left, y, right in hh
                ):
                    cells[cell_root(r * columns + c)] = cell_root((r + 1) * columns + c)
        groups = {}
        for r in range(rows):
            for c in range(columns):
                groups.setdefault(cell_root(r * columns + c), []).append((r, c))
        by_cell = {}
        descending_ys = [-value for value in ys]
        for _, glyph in selected:
            c = min(
                columns - 1,
                max(0, bisect_right(xs, (glyph.left + glyph.right) / 2) - 1),
            )
            r = min(
                rows - 1,
                max(
                    0, bisect_right(descending_ys, -(glyph.top + glyph.bottom) / 2) - 1
                ),
            )
            by_cell.setdefault(cell_root(r * columns + c), []).append(glyph)
        layout = [[] for _ in range(rows)]
        valid = True
        for identity, group in groups.items():
            cancel()
            rr = [v[0] for v in group]
            cc = [v[1] for v in group]
            r, c, last_r, last_c = min(rr), min(cc), max(rr), max(cc)
            if len(group) != (last_r - r + 1) * (last_c - c + 1):
                valid = False
                break
            owned = by_cell.get(identity, [])
            content = tuple(
                paragraphs(reading_lines(owned), xs[c] + 3, xs[last_c + 1] - 3, cancel)
            )
            center = (ys[r] + ys[last_r + 1]) / 2
            centered = (
                owned
                and abs(
                    (max(g.top for g in owned) + min(g.bottom for g in owned)) / 2
                    - center
                )
                < 6
            )
            layout[r].append(
                w.Cell(
                    c,
                    content,
                    last_c - c + 1,
                    last_r - r + 1,
                    vertical="center" if centered else "top",
                )
            )
            for continuation in range(r + 1, last_r + 1):
                layout[continuation].append(
                    w.Cell(c, (), last_c - c + 1, continuation=True)
                )
        if valid:
            table = w.Table(
                tuple(b - a for a, b in zip(xs, xs[1:])),
                tuple(
                    tuple(sorted(row, key=lambda cell: cell.column)) for row in layout
                ),
                heights=tuple(a - b for a, b in zip(ys, ys[1:])),
            )
            result.append((xs[0], ys[-1], xs[-1], ys[0], table))
            used.update(i for i, _ in selected)
    return result, [g for i, g in enumerate(chars) if i not in used]


def borderless_tables(chars, cancel):
    """Only repeated, short fields in three or more aligned columns.

    Two-column text is intentionally left to the reading-flow detector.
    """
    rows = []
    for line in sorted(
        reading_lines(chars), key=lambda item: (-item.baseline, item.left)
    ):
        if rows and abs(rows[-1][0].baseline - line.baseline) < 2:
            rows[-1].append(line)
        else:
            rows.append([line])
    groups = []
    for row in rows:
        cancel()
        eligible = 3 <= len(row) <= 12 and all(
            len("".join(r.text for r in line_runs(line))) <= 50 for line in row
        )
        previous = groups[-1][-1] if groups and groups[-1] else None
        aligned = (
            previous
            and len(previous) == len(row)
            and all(abs(a.left - b.left) < 3 for a, b in zip(previous, row))
            and 8 <= previous[0].baseline - row[0].baseline <= 60
        )
        if eligible and aligned:
            groups[-1].append(row)
        elif eligible:
            groups.append([row])
        else:
            groups.append([])
    tables, owned = [], set()
    for rows in groups:
        if len(rows) < 3:
            continue
        xs = [median(row[i].left for row in rows) for i in range(len(rows[0]))]
        # Painted glyph bounds are narrower than Word's advance width; leave
        # room for that difference as well as the two cell margins.
        right = max(row[-1].right for row in rows) + 12
        widths = tuple(b - a for a, b in zip(xs, xs[1:] + [right]))
        if min(widths) < 18:
            continue
        height = median(a[0].baseline - b[0].baseline for a, b in zip(rows, rows[1:]))
        output_rows = []
        for row in rows:
            output_rows.append(
                tuple(
                    w.Cell(
                        i,
                        tuple(
                            paragraphs(
                                [line], line.left, line.left + widths[i] - 6, cancel
                            )
                        ),
                    )
                    for i, line in enumerate(row)
                )
            )
            owned.update(id(g) for line in row for g in line.glyphs)
        top = max(line.top for line in rows[0]) + 4
        bottom = top - height * len(rows)
        tables.append(
            (
                xs[0],
                bottom,
                right,
                top,
                w.Table(
                    widths,
                    tuple(output_rows),
                    border=False,
                    heights=(height,) * len(rows),
                ),
            )
        )
    return tables, [g for g in chars if id(g) not in owned]


def flow_lines(lines, left, right, cancel, *, previous_bottom=None, body_size=12):
    rows = []
    for line in sorted(lines, key=lambda item: (-item.baseline, item.left)):
        if rows and abs(rows[-1][0].baseline - line.baseline) < 2:
            rows[-1].append(line)
        else:
            rows.append([line])
    pairs = [
        (a, b) for row in rows for a, b in zip(row, row[1:]) if b.left - a.right > 24
    ]
    is_ocr = any(
        g.object_id is not None and g.object_id < 0
        for line in lines
        for g in line.glyphs
    )
    inferred = None
    if is_ocr:
        # Scanned worksheets often have independently placed questions, not
        # matching baselines. Require a clear central gutter and overlapping
        # vertical coverage on both sides rather than pairing unrelated rows.
        options = []
        for fraction in (0.42, 0.46, 0.5, 0.54, 0.58):
            split = left + (right - left) * fraction
            lhs = [line for line in lines if line.right < split - 6]
            rhs = [line for line in lines if line.left > split + 6]
            if len(lhs) < 3 or len(rhs) < 3:
                continue
            shared = min(
                max(row.top for row in lhs), max(row.top for row in rhs)
            ) - max(min(row.bottom for row in lhs), min(row.bottom for row in rhs))
            if shared > 30:
                options.append(
                    (len(lhs) + len(rhs), split, min(row.left for row in rhs))
                )
        if options:
            _, cut, candidate = max(options)
            inferred = cut, candidate
    if len(pairs) < 3 and inferred is None:
        return paragraphs(
            lines,
            left,
            right,
            cancel,
            previous_bottom=previous_bottom,
            body_size=body_size,
        )
    starts = clustered(b.left for _, b in pairs)
    candidate = (
        inferred[1]
        if inferred
        else max(starts, key=lambda x: sum(abs(b.left - x) < 4 for _, b in pairs))
    )
    matching = [(a, b) for a, b in pairs if abs(b.left - candidate) < 4]
    if len(matching) < 3 and inferred is None:
        return paragraphs(
            lines,
            left,
            right,
            cancel,
            previous_bottom=previous_bottom,
            body_size=body_size,
        )
    cut = (
        inferred[0] if inferred else median((a.right + b.left) / 2 for a, b in matching)
    )
    output, group = [], []

    def flush():
        nonlocal previous_bottom
        if not group:
            return
        lhs = [line for line in group if line.right <= cut]
        rhs = [line for line in group if line.left >= cut]
        if len(lhs) >= 3 and len(rhs) >= 3:
            gap = max(18, min(144, 2 * candidate - left - right))
            column_width = (right - left - gap) / 2
            first = tuple(
                paragraphs(
                    lhs,
                    left,
                    left + column_width,
                    cancel,
                    body_size=body_size,
                )
            )
            second = tuple(
                paragraphs(
                    rhs, left + column_width + gap, right, cancel, body_size=body_size
                )
            )
            # Space above a column region belongs to the section, otherwise
            # Word applies it only to the left column after a column break.
            top = max(line.top for line in group)
            before = max(0, previous_bottom - top) if previous_bottom is not None else 0
            first = (
                replace(first[0], before=top - max(line.top for line in lhs)),
            ) + first[1:]
            second = (
                replace(second[0], before=top - max(line.top for line in rhs)),
            ) + second[1:]
            output.append(w.Columns((first, second), gap, before))
        else:
            output.extend(
                paragraphs(
                    group,
                    left,
                    right,
                    cancel,
                    previous_bottom=previous_bottom,
                    body_size=body_size,
                )
            )
        previous_bottom = min(line.bottom for line in group)
        group.clear()

    for row in rows:
        cancel()
        if all(
            (line.right <= cut or line.left >= cut)
            and (is_ocr or line.size < body_size * 1.28)
            for line in row
        ):
            group.extend(row)
        else:
            flush()
            output.extend(
                paragraphs(
                    row,
                    left,
                    right,
                    cancel,
                    previous_bottom=previous_bottom,
                    body_size=body_size,
                )
            )
            previous_bottom = min(line.bottom for line in row)
    flush()
    return output


def isolated_graphics(page, chars, images, dimensions, budget, cancel, limit):
    """Render only isolated vector regions; surrounding text remains Word text."""
    boxes = []
    with page_objects(page, cancel=cancel, limit=limit) as objects:
        for entry in objects:
            obj = entry.object
            cancel()
            if obj.type == raw.FPDF_PAGEOBJ_PATH:
                bounds = entry.bounds
                if all(math.isfinite(x) for x in bounds):
                    boxes.append(bounds)
                if len(boxes) > 512:
                    return []
    groups = []
    for box in boxes:
        joined = box
        remaining = []
        for other in groups:
            if (
                joined[0] <= other[2] + 36
                and other[0] <= joined[2] + 36
                and joined[1] <= other[3] + 36
                and other[1] <= joined[3] + 36
            ):
                joined = (
                    min(joined[0], other[0]),
                    min(joined[1], other[1]),
                    max(joined[2], other[2]),
                    max(joined[3], other[3]),
                )
            else:
                remaining.append(other)
        groups = remaining + [joined]
    result = []
    width, height = dimensions
    for x, y, xx, yy in groups:
        cancel()
        x, y, xx, yy = (
            max(0, x - 1),
            max(0, y - 1),
            min(width, xx + 1),
            min(height, yy + 1),
        )
        if xx - x < 12 or yy - y < 12 or (xx - x) * (yy - y) > width * height * 0.85:
            continue
        if any(
            x <= (g.left + g.right) / 2 <= xx and y <= (g.bottom + g.top) / 2 <= yy
            for g in chars
        ):
            continue
        if any(
            x < b.right and b.left < xx and y < b.top and b.bottom < yy for b in images
        ):
            continue
        pixels = math.ceil((xx - x) * 2) * math.ceil((yy - y) * 2)
        budget[1] += pixels * 4
        limit(pixels <= 25_000_000 and budget[1] <= 256 * 1024 * 1024)
        with closing(
            page.render(scale=2, crop=(x, y, width - xx, height - yy))
        ) as bitmap:
            with bitmap.to_pil() as image, BytesIO() as stream:
                image.save(stream, format="PNG")
                result.append(
                    (x, y, xx, yy, w.Picture(stream.getvalue(), xx - x, yy - y))
                )
    return result


def make_page(page, dimensions, blocks, budget, cancel, limit):
    segments = path_segments(page, cancel, limit)
    chars = glyphs(page, blocks, segments, cancel, limit)
    graphics = isolated_graphics(
        page, chars, [b for b in blocks if b.image], dimensions, budget, cancel, limit
    )
    return compose_page(
        dimensions, blocks, chars, segments, graphics, budget, cancel, limit
    )


def compose_page(dimensions, blocks, chars, segments, graphics, budget, cancel, limit):
    """Pure reconstruction shared by digital and recognized text geometry."""
    width, height = dimensions
    floating = [
        g[4]
        for g in graphics
        if isinstance(g[4], w.Picture) and g[4].position is not None
    ]
    graphics = [
        g
        for g in graphics
        if not (isinstance(g[4], w.Picture) and g[4].position is not None)
    ]
    # Extracted white lettering relied on a PDF background; Word's text flow
    # has a white canvas. Keep that lettering visible and editable.
    chars = [
        replace(g, run=replace(g.run, color="000000"))
        if min(int(g.run.color[i : i + 2], 16) for i in (0, 2, 4)) > 210
        else g
        for g in chars
    ]
    if not chars:
        return w.Page(
            width,
            height,
            tuple(
                w.Paragraph((w.Run(b.text, b.size, b.bold, b.italic, b.font, b.color),))
                for b in blocks
                if b.text
            ),
        )
    tables, remaining = ruled_tables(segments, chars, cancel, limit)
    text_tables, remaining = borderless_tables(remaining, cancel)
    tables.extend(text_tables)
    lines = reading_lines(remaining)
    sizes = Counter()
    for glyph in chars:
        sizes[round(glyph.run.size)] += len(glyph.text)
    body_size = sizes.most_common(1)[0][0]
    headers = [
        line
        for line in lines
        if line.bottom > height - 32 and line.size <= body_size * 1.1
    ]
    footers = [
        line
        for line in lines
        if (line.top < 45 and line.size <= max(12, body_size * 1.1))
        or (line.top < 60 and line.size <= max(10, body_size * 0.95))
    ]
    story_glyphs = {id(g) for line in headers + footers for g in line.glyphs}
    # A page may contain only a table plus its footer. Table glyphs are already
    # outside `lines`, but still establish body content for this safeguard.
    if len(story_glyphs) >= len(chars):
        headers, footers = [], []
        story_glyphs = set()
    story_lines = {id(line) for line in headers + footers}
    lines = [line for line in lines if id(line) not in story_lines]
    body_chars = [g for g in chars if id(g) not in story_glyphs]
    images = [b for b in blocks if b.image]
    left = max(12, min(144, min([g.left for g in chars] + [b.left for b in images])))
    right = max(
        12, min(72, width - max([g.right for g in chars] + [b.right for b in images]))
    )
    top = max(
        12,
        min(
            144,
            height
            - max(
                [g.top for g in body_chars]
                + [b.top for b in images]
                + [g[3] for g in graphics]
            ),
        ),
    )
    bottom = max(
        12,
        min(
            36,
            min(
                [g.bottom for g in body_chars]
                + [b.bottom for b in images]
                + [g[1] for g in graphics]
            ),
        ),
    )
    if headers:
        top = max(top, height - min(line.bottom for line in headers) + 8)
    if footers:
        bottom = max(bottom, max(line.top for line in footers) + 4)
    region_right = width - right
    entities = (
        [(line.left, line.bottom, line.right, line.top, line) for line in lines]
        + tables
        + [
            (
                b.left,
                b.bottom,
                b.right,
                b.top,
                w.Picture(
                    b.image, b.right - b.left, (b.right - b.left) * b.image_ratio
                ),
            )
            for b in images
        ]
        + graphics
    )
    consumed = set()
    sidebars = []
    for x, y, xx, yy, item in entities:
        if not isinstance(item, w.Picture):
            continue
        beside = [
            line
            for line in lines
            if id(line) not in consumed
            and line.bottom < yy + line.size
            and line.top > y
            and line.right < x - 6
        ]
        if len(beside) < 2 or x - left < 100:
            continue
        gap = max(18, min(144, 2 * x - left - region_right))
        column_width = (region_right - left - gap) / 2
        content = tuple(
            paragraphs(beside, left, left + column_width, cancel, body_size=body_size)
        )
        sidebars.append(
            (
                left,
                min(y, min(line.bottom for line in beside)),
                xx,
                max(yy, max(line.top for line in beside)),
                w.Columns((content, (item,)), gap),
            )
        )
        consumed.update(id(line) for line in beside)
        consumed.add(id(item))
    entities = [
        entity for entity in entities if id(entity[4]) not in consumed
    ] + sidebars
    entities.sort(key=lambda item: (-item[3], item[0]))
    content = []
    pending = []
    previous_bottom = None

    def flush():
        nonlocal previous_bottom
        if pending:
            content.extend(
                flow_lines(
                    pending,
                    left,
                    region_right,
                    cancel,
                    previous_bottom=previous_bottom,
                    body_size=body_size,
                )
            )
            previous_bottom = pending[-1].bottom
            pending.clear()

    for x, y, xx, yy, item in entities:
        cancel()
        if isinstance(item, Line):
            pending.append(item)
        else:
            flush()
            before = (
                max(0, previous_bottom - yy - 3) if previous_bottom is not None else 0
            )
            if isinstance(item, w.Table):
                content.append(replace(item, before=before, left=max(0, x - left)))
            elif isinstance(item, w.Columns):
                content.append(replace(item, before=before))
            else:
                content.append(replace(item, left=max(0, x - left), before=before))
            previous_bottom = y
    flush()
    header = tuple(paragraphs(headers, left, region_right, cancel, body_size=body_size))
    footer = tuple(paragraphs(footers, left, region_right, cancel, body_size=body_size))
    budget[2] += sum(len(p.runs) for p in walk_paragraphs(content))
    budget[2] += sum(len(row) for table in walk_tables(content) for row in table.rows)
    budget[2] += sum(len(p.runs) for p in header + footer)
    limit(budget[2] <= 50_000)
    return w.Page(
        width,
        height,
        tuple(floating + content),
        (top, right, bottom, left),
        header,
        footer,
        max(8, height - max(line.top for line in headers)) if headers else 18,
        max(8, min(line.bottom for line in footers)) if footers else 18,
    )


def walk_paragraphs(blocks):
    for block in blocks:
        if isinstance(block, w.Paragraph):
            yield block
        elif isinstance(block, w.Table):
            for row in block.rows:
                for cell in row:
                    yield from walk_paragraphs(cell.blocks)
        elif isinstance(block, w.Columns):
            for column in block.columns:
                yield from walk_paragraphs(column)


def walk_tables(blocks):
    for block in blocks:
        if isinstance(block, w.Table):
            yield block
        elif isinstance(block, w.Columns):
            for column in block.columns:
                yield from walk_tables(column)
