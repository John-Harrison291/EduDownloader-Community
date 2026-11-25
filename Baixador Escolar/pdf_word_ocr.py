"""Regional OCR geometry for the existing editable Word reconstructor.

Only detached Pillow images and immutable layout records enter this module.
PDFium and Tk are never accessed here.
"""

from dataclasses import dataclass, replace
from io import BytesIO
from statistics import median
import unicodedata

from PIL import ImageDraw, ImageFont, ImageOps

import docx_writer as w
import pdf_word_layout as layout
from pdf_ocr_runtime import OcrUnavailable, OcrBatch
from pdf_ocr_vision import analyze, ink_components, VisionLimit


@dataclass(frozen=True)
class Recognition:
    glyphs: tuple
    graphics: tuple
    segments: tuple
    words: int
    review: bool
    seconds: float
    peak_memory_bytes: int
    regions: int
    engine: str = "tesseract"


def _score(words):
    useful = [word for word in words if any(c.isalnum() for c in word.text)]
    return sum(
        max(0, (word.confidence or 0) - 25) * min(12, len(word.text)) for word in useful
    )


def _accepted(words):
    useful = [
        word
        for word in words
        if _text_token(word.text) and any(c.isalnum() for c in word.text)
    ]
    if not useful:
        return False
    if not any(
        len(word.text) >= 3 or any(c.isdigit() for c in word.text) for word in useful
    ):
        return False
    if (
        len(useful) >= 4
        and all(len(word.text) == 1 for word in useful)
        and len({word.text for word in useful}) <= 2
    ):
        return False
    known = [word.confidence for word in useful if word.confidence is not None]
    if not known:
        return (
            any(any(c.isdigit() for c in word.text) for word in useful)
            or sum(len(word.text) for word in useful) >= 4
        )
    confidence = median(known)
    if len(useful) == 1 and useful[0].text.isdigit() and confidence >= 85:
        return True
    return (len(useful) >= 3 and confidence >= 48) or (
        confidence >= 78 and sum(len(word.text) for word in useful) >= 4
    )


def _text_token(text):
    return not (len(text) >= 4 and text.isalpha() and len(set(text.casefold())) == 1)


def _font():
    try:
        return ImageFont.truetype("arial.ttf", 100)
    except OSError:
        return None


def _inverse_box(box, angle, width, height):
    x, y, xx, yy = box
    if angle == 90:  # Pillow rotation is counterclockwise.
        return width - yy, x, width - y, xx
    if angle == 180:
        return width - xx, height - yy, width - x, height - y
    if angle == 270:
        return y, height - xx, yy, height - x
    return box


def _graphics(image, erased, digital_boxes, segments, dimensions, store, cancel):
    """Retain coherent non-text crops, with recovered text removed once."""
    scale = min(
        1, 1399 / image.width, (1_990_000 / (image.width * image.height)) ** 0.5
    )
    with image.convert("RGB") as rgb:
        cleaned = rgb.resize((round(image.width * scale), round(image.height * scale)))
    try:
        draw = ImageDraw.Draw(cleaned)
        for x, y, xx, yy in (*erased, *digital_boxes):
            cancel()
            draw.rectangle(
                (
                    int(x * scale) - 2,
                    int(y * scale) - 2,
                    int(xx * scale) + 2,
                    int(yy * scale) + 2,
                ),
                fill="white",
            )
        for x, y, xx, yy in segments:
            draw.line(
                (x * scale, y * scale, xx * scale, yy * scale), fill="white", width=4
            )
        with (
            ImageOps.grayscale(cleaned) as gray,
            gray.point(lambda v: 0 if v < 225 else 255) as binary,
        ):
            candidates = [
                c
                for c in ink_components(binary, cancel)
                if c.area > 160 and c.width > 16 and c.height > 16
            ]
        boxes = []
        for item in candidates:
            x, y, xx, yy = item.left, item.top, item.right, item.bottom
            remaining = []
            for a, b, aa, bb in boxes:
                if x < aa + 12 and a < xx + 12 and y < bb + 12 and b < yy + 12:
                    x, y, xx, yy = min(x, a), min(y, b), max(xx, aa), max(yy, bb)
                else:
                    remaining.append((a, b, aa, bb))
            boxes = remaining + [(x, y, xx, yy)]
        if len(boxes) > 128:
            raise VisionLimit("graphic crop limit")
        result = []
        for x, y, xx, yy in boxes:
            cancel()
            if xx - x < 24 or yy - y < 24:
                continue
            box = (
                max(0, x - 2),
                max(0, y - 2),
                min(cleaned.width, xx + 2),
                min(cleaned.height, yy + 2),
            )
            with cleaned.crop(box) as crop:
                stream = BytesIO()
                crop.save(stream, "PNG")
            left, right = (
                box[0] / cleaned.width * dimensions[0],
                box[2] / cleaned.width * dimensions[0],
            )
            bottom, top = (
                dimensions[1] * (1 - box[3] / cleaned.height),
                dimensions[1] * (1 - box[1] / cleaned.height),
            )
            result.append(
                (
                    left,
                    bottom,
                    right,
                    top,
                    w.Picture(
                        store.add(stream.getvalue()),
                        right - left,
                        top - bottom,
                        position=(left, dimensions[1] - top),
                    ),
                )
            )
        return tuple(result)
    finally:
        cleaned.close()


def recognize_page(image, dimensions, native, analysis, runtime, store, cancel):
    """Batch candidate regions, then feed word geometry to Goal 5 layout."""
    if (
        len(analysis.regions) > 96
        or sum((r.box[2] - r.box[0]) * (r.box[3] - r.box[1]) for r in analysis.regions)
        > 40_000_000
    ):
        raise VisionLimit("retained region pixel limit")
    sx, sy = image.width / dimensions[0], image.height / dimensions[1]
    digital_boxes = [
        (
            g.left * sx,
            (dimensions[1] - g.top) * sy,
            g.right * sx,
            (dimensions[1] - g.bottom) * sy,
        )
        for g in native
    ]
    crops, regions = [], []
    seconds = 0.0
    peak = 0
    try:
        for region in analysis.regions:
            cancel()
            crop = image.crop(region.box).convert("L")
            draw = ImageDraw.Draw(crop)
            x, y, xx, yy = region.box
            for a, b, aa, bb in digital_boxes:
                if a < xx and aa > x and b < yy and bb > y:
                    draw.rectangle(
                        (a - x - 2, b - y - 2, aa - x + 2, bb - y + 2), fill="white"
                    )
            if analysis.inverted:
                replacement = ImageOps.invert(crop)
                crop.close()
                crop = replacement
            crops.append(crop)
            regions.append(region)
        if not crops:
            return Recognition((), (), (), 0, False, 0, 0, 0)
        # Overlapping candidates never multiply the bounded page raster budget.
        batches = [[] for _ in crops]
        windows_rows = {}
        font = _font()
        engine = "tesseract"
        windows_method = getattr(runtime, "recognize_windows", None)
        windows = (
            windows_method(image, digital_boxes, cancel=cancel)
            if callable(windows_method)
            else None
        )
        if isinstance(windows, OcrBatch):
            engine = "windows-ocr"
            seconds += windows.seconds
            peak = max(peak, windows.peak_memory_bytes)
            for word in windows.pages[0]:
                cancel()
                area = max(1, word.width * word.height)
                choices = []
                for number, region in enumerate(regions):
                    x, y, xx, yy = region.box
                    overlap = max(
                        0, min(xx, word.left + word.width) - max(x, word.left)
                    ) * max(0, min(yy, word.top + word.height) - max(y, word.top))
                    if overlap / area >= 0.5:
                        choices.append((overlap / area, not region.vertical, number))
                if choices:
                    number = max(choices)[2]
                    x, y, _, _ = regions[number].box
                    batches[number].append(
                        replace(word, left=word.left - x, top=word.top - y)
                    )
                    windows_rows.setdefault(word.line, []).append(word)
        windows_baselines = {
            key: median(word.top + word.height for word in row)
            for key, row in windows_rows.items()
        }
        windows_sizes = {}
        for key, row in windows_rows.items():
            widths = [
                word.width / sx / (font.getlength(word.text) / 100)
                for word in row
                if font is not None
                and len(word.text) >= 3
                and font.getlength(word.text) > 0
            ]
            if widths:
                windows_sizes[key] = min(
                    median(widths), median(word.height / sy for word in row) * 1.65
                )
        missing = [
            number for number, words in enumerate(batches) if not _accepted(words)
        ]
        start = 0
        while start < len(missing):
            end, pixels = start, 0
            while (
                end < len(missing)
                and pixels + crops[missing[end]].width * crops[missing[end]].height
                <= 20_000_000
            ):
                pixels += crops[missing[end]].width * crops[missing[end]].height
                end += 1
            if end == start:
                raise VisionLimit("recognition pixel limit")
            batch = runtime.recognize(
                [crops[number] for number in missing[start:end]], cancel=cancel
            )
            if isinstance(windows, OcrBatch):
                engine = "windows-ocr+tesseract"
            for number, words in zip(missing[start:end], batch.pages):
                batches[number] = words
            seconds += batch.seconds
            peak = max(peak, batch.peak_memory_bytes)
            start = end
        chars, erased, seen = [], [], []
        review = False
        rotated_trials = 0
        for number, (region, crop, initial) in enumerate(zip(regions, crops, batches)):
            cancel()
            words, angle = initial, 0
            if (
                region.vertical
                and rotated_trials < 8
                and crop.width * crop.height < 4_000_000
            ):
                rotated_trials += 1
                variants = [
                    crop.rotate(a, expand=True, fillcolor=255) for a in (90, 180, 270)
                ]
                try:
                    factors = []
                    large_card = region.vertical and max(crop.size) > 1800
                    for variant in variants:
                        original_width = variant.width
                        if large_card:
                            variant.thumbnail((1200, 1200))
                        factors.append(original_width / variant.width)
                    try:
                        trial = runtime.recognize(
                            variants,
                            family="best" if large_card else "fast",
                            cancel=cancel,
                        )
                    except OcrUnavailable:
                        trial = runtime.recognize(variants, cancel=cancel)
                    seconds += trial.seconds
                    peak = max(peak, trial.peak_memory_bytes)
                    pages = [
                        tuple(
                            replace(
                                word,
                                left=word.left * factor,
                                top=word.top * factor,
                                width=word.width * factor,
                                height=word.height * factor,
                            )
                            for word in page
                        )
                        for page, factor in zip(trial.pages, factors)
                    ]
                    choices = [(words, 0)] + [
                        (page, a)
                        for page, a in zip(pages, (90, 180, 270))
                        if _accepted(page)
                    ]
                    selected, rotation = max(choices, key=lambda item: _score(item[0]))
                    if (
                        _accepted(selected)
                        and _score(selected) > _score(words) * 1.35 + 60
                    ):
                        words, angle = selected, rotation
                finally:
                    for variant in variants:
                        variant.close()
            if not _accepted(words):
                review = True
                continue
            by_line = {}
            for word in words:
                by_line.setdefault((word.block, word.paragraph, word.line), []).append(
                    word
                )
            valid_lines = {key for key, row in by_line.items() if _accepted(row)}
            if len(valid_lines) < len(by_line):
                review = True
            words = tuple(
                word
                for word in words
                if (word.block, word.paragraph, word.line) in valid_lines
                and _text_token(word.text)
            )
            if not words:
                continue
            review |= angle != 0 or any(
                word.confidence is None or word.confidence < 75 for word in words
            )
            x, y, xx, yy = region.box
            rw, rh = (crop.height, crop.width) if angle in (90, 270) else crop.size
            for key in valid_lines:
                row = by_line[key]
                box = _inverse_box(
                    (
                        min(word.left for word in row),
                        min(word.top for word in row),
                        max(word.left + word.width for word in row),
                        max(word.top + word.height for word in row),
                    ),
                    angle,
                    crop.width,
                    crop.height,
                )
                erased.append((x + box[0], y + box[1], x + box[2], y + box[3]))
            # Rotated cards become horizontal editable text in their own region.
            mx, my = (xx - x) / rw / sx, (yy - y) / rh / sy
            line_sizes, line_bottoms, line_heights = {}, {}, {}
            for word in words:
                key = word.block, word.paragraph, word.line
                baseline = (
                    windows_baselines[word.line] - y
                    if word.confidence is None and word.line in windows_baselines
                    else word.top + word.height
                )
                line_bottoms.setdefault(key, []).append(baseline)
                line_heights.setdefault(key, []).append(word.height * my)
                if (
                    font is not None
                    and len(word.text) >= 3
                    and (word.confidence is None or word.confidence >= 60)
                ):
                    advance = font.getlength(word.text) / 100
                    if advance > 0:
                        line_sizes.setdefault(key, []).append(word.width * mx / advance)
            for word in words:
                cancel()
                text = w.safe_text(unicodedata.normalize("NFC", word.text)).strip()
                if not text or (word.confidence is not None and word.confidence < 35):
                    review = True
                    continue
                if set(text) <= set("|_~"):
                    # Isolated rules/frame edges are not recovered prose.
                    review = True
                    continue
                source_box = _inverse_box(
                    (
                        word.left,
                        word.top,
                        word.left + word.width,
                        word.top + word.height,
                    ),
                    angle,
                    crop.width,
                    crop.height,
                )
                a, b, aa, bb = source_box
                source_box = (x + a, y + b, x + aa, y + bb)
                duplicate = False
                for index, (previous, box) in enumerate(seen):
                    if index % 64 == 0:
                        cancel()
                    if previous.casefold() != text.casefold():
                        continue
                    overlap = max(
                        0, min(box[2], source_box[2]) - max(box[0], source_box[0])
                    ) * max(0, min(box[3], source_box[3]) - max(box[1], source_box[1]))
                    area = max(
                        1,
                        (source_box[2] - source_box[0])
                        * (source_box[3] - source_box[1]),
                    )
                    if overlap / area > 0.5:
                        duplicate = True
                        break
                if duplicate:
                    continue
                seen.append((text, source_box))
                key = word.block, word.paragraph, word.line
                size = (
                    median(line_sizes[key])
                    if key in line_sizes
                    else word.height * my * 1.2
                )
                if word.confidence is None and word.line in windows_sizes:
                    size = windows_sizes[word.line]
                # Sparse/artifact-joined word boxes can be much too wide.
                # Their width must not turn a 5 pt-high worksheet line into
                # 18 pt text and force unrelated questions onto extra pages.
                height_limit = median(line_heights[key]) * 1.65
                review |= size > height_limit * 1.1
                size = min(size, height_limit)
                size = max(6, min(72, round(size * 2) / 2))
                left, right = (
                    x / sx + word.left * mx,
                    x / sx + (word.left + word.width) * mx,
                )
                top = dimensions[1] - y / sy - word.top * my
                bottom = top - word.height * my
                baseline = dimensions[1] - y / sy - median(line_bottoms[key]) * my
                chars.append(
                    layout.Glyph(
                        text,
                        left,
                        bottom,
                        right,
                        top,
                        baseline,
                        w.Run(text, size),
                        True,
                        -(number + 1),
                    )
                )
        segments = tuple(
            (a / sx, dimensions[1] - b / sy, aa / sx, dimensions[1] - bb / sy)
            for a, b, aa, bb in analysis.segments
        )

        def limit_grid(valid):
            if not valid:
                raise VisionLimit("recovered table limit")

        tables, _ = layout.ruled_tables(
            segments, list(native) + chars, cancel, limit_grid
        )
        # A number line, answer rule or diagram stays graphical. Erase only
        # dividers for tables actually recoverable by the shared table engine.
        table_segments = tuple(
            pixel
            for pixel, segment in zip(analysis.segments, segments)
            if any(
                left - 2
                <= min(segment[0], segment[2])
                <= max(segment[0], segment[2])
                <= right + 2
                and bottom - 2
                <= min(segment[1], segment[3])
                <= max(segment[1], segment[3])
                <= top + 2
                for left, bottom, right, top, _ in tables
            )
        )
        graphics = (
            _graphics(
                image,
                erased,
                digital_boxes,
                table_segments,
                dimensions,
                store,
                cancel,
            )
            if chars
            else ()
        )
        return Recognition(
            tuple(chars),
            graphics,
            segments,
            len(chars),
            review,
            seconds,
            peak,
            len(regions),
            engine,
        )
    finally:
        for crop in crops:
            crop.close()


def analyze_page(image, dimensions, chars, cancel):
    sx, sy = image.width / dimensions[0], image.height / dimensions[1]
    boxes = [
        (
            g.left * sx,
            (dimensions[1] - g.top) * sy,
            g.right * sx,
            (dimensions[1] - g.bottom) * sy,
        )
        for g in chars
    ]
    return analyze(image, boxes, cancel=cancel)


def digital_graphics(image, dimensions, chars, store, cancel):
    """An existing text layer needs no OCR; remove its visible raster copy."""
    sx, sy = image.width / dimensions[0], image.height / dimensions[1]
    boxes = [
        (
            g.left * sx,
            (dimensions[1] - g.top) * sy,
            g.right * sx,
            (dimensions[1] - g.bottom) * sy,
        )
        for g in chars
    ]
    return _graphics(image, (), boxes, (), dimensions, store, cancel)
