"""Serialize native PDFium access shared by independent UI workers."""

from functools import wraps
from threading import RLock
from contextlib import contextmanager
from dataclasses import dataclass
import math

import pypdfium2 as pdfium
import pypdfium2.raw as raw

# PDFium is process-global and not thread-safe, even across documents.
PDFIUM_LOCK = RLock()


@dataclass(frozen=True)
class PageObject:
    """Page-owned native object and its geometry in page coordinates."""

    object: object
    matrix: pdfium.PdfMatrix
    bounds: tuple[float, float, float, float]


def page_matrix(page):
    """Map absolute PDF coordinates into the visible page's bottom-left frame."""
    left, bottom, right, top = page.get_bbox()
    if not all(math.isfinite(value) for value in (left, bottom, right, top)):
        raise ValueError("invalid page box")
    width, height = right - left, top - bottom
    matrix = pdfium.PdfMatrix().translate(-left, -bottom)
    rotation = page.get_rotation()
    # Exact quarter-turn coefficients avoid trigonometric rounding at edges.
    rotations = {
        0: pdfium.PdfMatrix(),
        90: pdfium.PdfMatrix(0, -1, 1, 0, 0, width),
        180: pdfium.PdfMatrix(-1, 0, 0, -1, width, height),
        270: pdfium.PdfMatrix(0, 1, -1, 0, height, 0),
    }
    if rotation not in rotations or width <= 0 or height <= 0:
        raise ValueError("invalid page frame")
    return matrix.multiply(rotations[rotation])


@contextmanager
def page_objects(page, *, textpage=None, cancel=lambda: None, limit=None):
    """Bounded traversal; keep Form wrappers alive until children are consumed.

    The caller owns PDFIUM_LOCK. Closing a yielded Form in PdfPage.get_objects
    invalidates the wrapper before that generator recurses into it. Walking one
    level at a time also lets us compose parent transforms instead of treating
    nested image/path bounds as page coordinates.
    """
    records, wrappers = [], []

    def check(condition):
        if limit is not None:
            limit(condition)
        elif not condition:
            raise ValueError("PDF object traversal limit")

    def visit(form, parent_matrix, depth):
        check(depth < 16)
        for obj in page.get_objects(max_depth=1, form=form, textpage=textpage):
            wrappers.append(obj)
            cancel()
            check(len(wrappers) <= 10_000)
            matrix = obj.get_matrix().multiply(parent_matrix)
            bounds = parent_matrix.on_rect(*obj.get_bounds())
            records.append(PageObject(obj, matrix, bounds))
            if obj.type == raw.FPDF_PAGEOBJ_FORM:
                visit(obj, matrix, depth + 1)

    try:
        visit(None, page_matrix(page), 0)
        yield tuple(records)
    finally:
        for obj in reversed(wrappers):
            obj.close()


def serialized_pdfium(function):
    """Keep each existing native operation and its finalizers in one lock."""

    @wraps(function)
    def call(*args, **kwargs):
        with PDFIUM_LOCK:
            return function(*args, **kwargs)

    return call
