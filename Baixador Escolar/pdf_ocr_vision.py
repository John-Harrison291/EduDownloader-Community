"""Bounded, local image geometry for deciding where OCR is justified.

No spelling correction or recognition happens here. Small aligned ink
components are evidence of possible printed text, never proof of its content.
"""

from dataclasses import dataclass
from statistics import median

from PIL import Image, ImageOps

MAX_ANALYSIS_PIXELS = 2_000_000
MAX_COMPONENT_RUNS = 120_000
MAX_REGIONS = 96


class VisionLimit(ValueError):
    pass


@dataclass(frozen=True)
class Ink:
    left: int
    top: int
    right: int
    bottom: int
    area: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top


@dataclass(frozen=True)
class TextRegion:
    box: tuple[int, int, int, int]
    components: int
    vertical: bool = False


@dataclass(frozen=True)
class ImageAnalysis:
    regions: tuple[TextRegion, ...]
    segments: tuple[tuple[float, float, float, float], ...]
    component_count: int
    covered_components: int
    inverted: bool
    scale: float


def _threshold(image):
    histogram = image.histogram()
    total = sum(histogram)
    intensity = sum(i * count for i, count in enumerate(histogram))
    weight = value = 0
    best, threshold = -1, 180
    for index, count in enumerate(histogram):
        weight += count
        value += count * index
        other = total - weight
        if not weight or not other:
            continue
        score = weight * other * (value / weight - (intensity - value) / other) ** 2
        if score > best:
            best, threshold = score, index
    return max(90, min(205, threshold + 10))


def ink_components(binary, cancel=lambda: None):
    """Row-run connected components; no Python object per raster pixel."""
    width, height = binary.size
    if width * height > MAX_ANALYSIS_PIXELS:
        raise VisionLimit("analysis raster limit")
    data = binary.tobytes()
    parents, bounds = [], []
    previous = []
    runs = 0

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(a, b):
        a, b = find(a), find(b)
        if a == b:
            return a
        if bounds[a][4] < bounds[b][4]:
            a, b = b, a
        parents[b] = a
        aa, bb = bounds[a], bounds[b]
        bounds[a] = [
            min(aa[0], bb[0]),
            min(aa[1], bb[1]),
            max(aa[2], bb[2]),
            max(aa[3], bb[3]),
            aa[4] + bb[4],
        ]
        return a

    for y in range(height):
        if y % 32 == 0:
            cancel()
        row = data[y * width : (y + 1) * width]
        current, x, previous_index = [], 0, 0
        while x < width:
            start = row.find(b"\x00", x)
            if start < 0:
                break
            end = row.find(b"\xff", start)
            if end < 0:
                end = width
            runs += 1
            if runs > MAX_COMPONENT_RUNS:
                raise VisionLimit("component run limit")
            while (
                previous_index < len(previous)
                and previous[previous_index][1] < start - 1
            ):
                previous_index += 1
            index, overlaps = previous_index, []
            while index < len(previous) and previous[index][0] <= end:
                overlaps.append(previous[index][2])
                index += 1
            if overlaps:
                identity = find(overlaps[0])
                for other in overlaps[1:]:
                    identity = union(identity, other)
                item = bounds[identity]
                bounds[identity] = [
                    min(item[0], start),
                    item[1],
                    max(item[2], end),
                    y + 1,
                    item[4] + end - start,
                ]
            else:
                identity = len(parents)
                parents.append(identity)
                bounds.append([start, y, end, y + 1, end - start])
            current.append((start, end, identity))
            x = end
        previous = current
    return [Ink(*bounds[i]) for i in range(len(parents)) if find(i) == i]


def _line_regions(components, *, vertical=False):
    # Also look along the other axis for rotated cards. OCR decides whether the
    # candidate is text; a connected shape alone never becomes an invented word.
    if vertical:
        components = [Ink(c.top, c.left, c.bottom, c.right, c.area) for c in components]
    rows = []
    for item in sorted(components, key=lambda c: (c.top + c.bottom, c.left)):
        center = (item.top + item.bottom) / 2
        row = next(
            (
                r
                for r in reversed(rows[-12:])
                if abs((r[0].top + r[0].bottom) / 2 - center)
                < max(3, min(r[0].height, item.height) * 0.55)
            ),
            None,
        )
        if row is None:
            rows.append([item])
        else:
            row.append(item)
    result = []
    for row in rows:
        groups = [[]]
        for item in sorted(row, key=lambda c: c.left):
            if groups[-1] and item.left - groups[-1][-1].right > max(
                18, item.height * 2.8
            ):
                groups.append([])
            groups[-1].append(item)
        for group in groups:
            if len(group) < 3:
                continue
            box = (
                min(c.left for c in group),
                min(c.top for c in group),
                max(c.right for c in group),
                max(c.bottom for c in group),
            )
            if vertical:
                box = (box[1], box[0], box[3], box[2])
            result.append(TextRegion(box, len(group), vertical))
    return result


def _band_regions(binary, cancel):
    """Whole line extents also include small/disconnected accented letters."""
    width, height = binary.size
    data = binary.tobytes()
    bands = []
    for y in range(height):
        if y % 64 == 0:
            cancel()
        if data[y * width : (y + 1) * width].count(0) >= 3:
            if bands and y - bands[-1][1] <= 3:
                bands[-1][1] = y
            else:
                bands.append([y, y])
    regions = []
    for top, bottom in bands:
        band_height = bottom - top + 1
        if not 4 <= band_height <= 100:
            continue
        occupied = bytearray(width)
        for y in range(top, bottom + 1):
            row = data[y * width : (y + 1) * width]
            for x in range(width):
                if row[x] == 0:
                    occupied[x] = 1
        groups = []
        for x, value in enumerate(occupied):
            if value:
                if groups and x - groups[-1][1] <= max(24, band_height * 4):
                    groups[-1][1] = x
                else:
                    groups.append([x, x])
        for left, right in groups:
            if (
                right - left >= band_height * 1.8
                and sum(occupied[left : right + 1]) >= 12
            ):
                regions.append(TextRegion((left, top, right + 1, bottom + 1), 3))
    return regions


def _merge_regions(regions, padding, cancel):
    merged = []
    for region in sorted(regions, key=lambda r: (r.box[1], r.box[0])):
        cancel()
        x, y, xx, yy = region.box
        count = region.components
        remaining = []
        for other in merged:
            a, b, aa, bb = other.box
            if (
                other.vertical == region.vertical
                and x <= aa + padding
                and a <= xx + padding
                and y <= bb + padding
                and b <= yy + padding
            ):
                x, y, xx, yy = min(x, a), min(y, b), max(xx, aa), max(yy, bb)
                count += other.components
            else:
                remaining.append(other)
        merged = remaining + [TextRegion((x, y, xx, yy), count, region.vertical)]
    if len(merged) > MAX_REGIONS:
        raise VisionLimit("OCR region limit")
    return merged


def raster_segments(binary, cancel=lambda: None):
    segments = []
    for vertical in (False, True):
        image = binary.transpose(Image.Transpose.TRANSPOSE) if vertical else binary
        width, height = image.size
        data = image.tobytes()
        groups = []
        for y in range(height):
            if y % 64 == 0:
                cancel()
            row = data[y * width : (y + 1) * width]
            x = 0
            while x < width:
                left = row.find(b"\x00", x)
                if left < 0:
                    break
                right = row.find(b"\xff", left)
                if right < 0:
                    right = width
                if right - left >= max(45, width * 0.07):
                    found = next(
                        (
                            g
                            for g in reversed(groups[-32:])
                            if y - g[3] <= 1
                            and abs(g[0] - left) <= 3
                            and abs(g[2] - right) <= 3
                        ),
                        None,
                    )
                    if found is None:
                        groups.append([left, y, right, y])
                    else:
                        found[3] = y
                x = right
        for left, top, right, bottom in groups:
            if bottom - top > 6:
                continue
            neighbors = [
                position for position in (top - 2, bottom + 2) if 0 <= position < height
            ]
            # A thin slice through a photograph is not a ruled line: a real
            # divider has mostly clear pixels immediately on either side.
            if (
                not neighbors
                or sum(
                    data[position * width + left : position * width + right].count(0)
                    for position in neighbors
                )
                > (right - left) * len(neighbors) * 0.18
            ):
                continue
            y = (top + bottom) / 2
            segments.append((y, left, y, right) if vertical else (left, y, right, y))
        if vertical:
            image.close()
    if len(segments) > 1500:
        raise VisionLimit("raster segment limit")
    return tuple(segments)


def analyze(image, digital_boxes=(), *, cancel=lambda: None):
    """Boxes are in original-image pixels; returned regions use those pixels."""
    width, height = image.size
    if not 0 < width * height <= 20_000_000:
        raise VisionLimit("source image limit")
    scale = min(
        1.0, (MAX_ANALYSIS_PIXELS / max(1, width * height)) ** 0.5, 1400 / max(1, width)
    )
    with image.convert("L") as gray:
        small = gray.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BILINEAR,
        )
    try:
        histogram = small.histogram()
        inverted = sum(histogram[:100]) > sum(histogram) * 0.65
        if inverted:
            replacement = ImageOps.invert(small)
            small.close()
            small = replacement
        threshold = _threshold(small)
        with small.point(lambda value: 0 if value < threshold else 255) as binary:
            components = ink_components(binary, cancel)
            segments = raster_segments(binary, cancel)
            bands = _band_regions(binary, cancel)
    finally:
        small.close()
    cell = 12
    coverage = set()
    for x, y, xx, yy in digital_boxes:
        cancel()
        for gy in range(
            max(0, int(y * scale) // cell),
            min(int(height * scale) // cell + 1, int(yy * scale) // cell + 1),
        ):
            for gx in range(
                max(0, int(x * scale) // cell),
                min(int(width * scale) // cell + 1, int(xx * scale) // cell + 1),
            ):
                coverage.add((gx, gy))
    letters, covered = [], 0
    for item in components:
        if not (
            3 <= item.height <= max(120, int(height * scale * 0.25))
            and 1 <= item.width <= max(140, int(width * scale * 0.28))
            and item.area >= 3
            and 0.06 <= item.width / item.height <= 4
        ):
            continue
        if (
            (item.left + item.right) // (2 * cell),
            (item.top + item.bottom) // (2 * cell),
        ) in coverage:
            covered += 1
        else:
            letters.append(item)
    vertical_letters = [item for item in letters if item.width >= item.height * 1.15]
    vertical_regions = [
        region
        for region in _line_regions(vertical_letters, vertical=True)
        if region.components >= 4
        and region.box[3] - region.box[1] > (region.box[2] - region.box[0]) * 1.8
    ]
    horizontal = _line_regions(letters)
    # A vertical alignment through several horizontal lines is a column of
    # unrelated letters, not evidence of a rotated card.
    uncovered_bands = [
        band
        for band in bands
        if any(
            band.box[0] < h.box[2]
            and band.box[2] > h.box[0]
            and band.box[1] < h.box[3]
            and band.box[3] > h.box[1]
            for h in horizontal
        )
        or sum(
            band.box[0] <= c.left < band.box[2] and band.box[1] <= c.top < band.box[3]
            for c in letters
        )
        >= 3
    ]
    vertical_regions = [
        v
        for v in vertical_regions
        if sum(
            h.box[0] < v.box[2]
            and h.box[2] > v.box[0]
            and h.box[1] < v.box[3]
            and h.box[3] > v.box[1]
            for h in horizontal + uncovered_bands
        )
        < 2
    ]
    candidates = horizontal + uncovered_bands + vertical_regions
    padding = max(8, median(c.height for c in letters) * 1.3) if letters else 8
    regions = _merge_regions(candidates, padding, cancel)
    output = []
    for region in regions:
        x, y, xx, yy = region.box
        pad = max(5, min(20, padding / 2))
        if region.vertical:
            pad = max(pad, min(100, (xx - x) * 0.16))
        box = (
            max(0, int((x - pad) / scale)),
            max(0, int((y - pad) / scale)),
            min(width, int((xx + pad) / scale)),
            min(height, int((yy + pad) / scale)),
        )
        output.append(TextRegion(box, region.components, region.vertical))
    return ImageAnalysis(
        tuple(output),
        tuple(tuple(value / scale for value in line) for line in segments),
        len(components),
        covered,
        inverted,
        scale,
    )


def deskew_angle(image, cancel=lambda: None):
    """Small correction only when horizontal projection improves substantially."""
    with image.convert("L") as gray:
        gray.thumbnail((900, 1200))
        binary = gray.point(lambda value: 0 if value < 170 else 255)
    try:
        if binary.tobytes().count(0) > binary.width * binary.height * 0.25:
            return 0.0

        def score(raster):
            data = raster.tobytes()
            counts = [
                data[y * raster.width : (y + 1) * raster.width].count(0)
                for y in range(raster.height)
            ]
            return sum(value * value for value in counts)

        baseline = score(binary)
        best, angle = baseline, 0.0
        for step in range(-8, 9):
            cancel()
            if step == 0:
                continue
            with binary.rotate(step / 2, fillcolor=255) as trial:
                value = score(trial)
            if value > best:
                best, angle = value, step / 2
        return angle if best > baseline * 1.35 else 0.0
    finally:
        binary.close()
