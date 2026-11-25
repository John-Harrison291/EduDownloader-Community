"""Testes puros dos contratos físicos da preparação de impressão."""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError

from print_layout import (
    MAX_CONVERSION_IMAGE_PIXELS,
    MAX_PDF_EXPORT_PAGES,
    MAX_PDF_PAGE_POINTS,
    MAX_POSTER_GRID_DIMENSION,
    MAX_POSTER_PAGES,
    PDF_EXPORT_PAGE_WARNING_THRESHOLD,
    ContainPlacement,
    ImagePageLayout,
    MarginPreset,
    Orientation,
    OverlapPreset,
    PaperSize,
    PdfImageQuality,
    PosterGrid,
    PosterLayout,
    PpiQuality,
    PrintLayoutError,
    Rect,
    Size,
    cell_spacing,
    choose_image_page_orientation,
    choose_poster_orientation,
    classify_ppi,
    contain_image,
    effective_poster_ppi,
    estimate_raster_bytes,
    image_slots,
    millimetres_to_points,
    page_content_rect,
    page_dimensions,
    paginate_images,
    pdf_export_requires_warning,
    pdfium_scale,
    poster_page_index,
    poster_page_position,
    poster_panel_size,
    raster_dimensions,
    validate_conversion_image_dimensions,
    validate_pdf_page_dimensions,
)


class PaperAndMarginTests(unittest.TestCase):
    def test_a4_and_letter_have_physical_portrait_and_landscape_dimensions(
        self,
    ) -> None:
        a4 = page_dimensions(PaperSize.A4, Orientation.PORTRAIT)
        self.assertAlmostEqual(a4.width, millimetres_to_points(210), places=6)
        self.assertAlmostEqual(a4.height, millimetres_to_points(297), places=6)
        self.assertEqual(
            page_dimensions(PaperSize.A4, Orientation.LANDSCAPE),
            Size(a4.height, a4.width),
        )
        self.assertEqual(
            page_dimensions(PaperSize.LETTER, Orientation.PORTRAIT),
            Size(612.0, 792.0),
        )

    def test_auto_must_be_resolved_before_page_geometry(self) -> None:
        with self.assertRaises(PrintLayoutError):
            page_dimensions(PaperSize.A4, Orientation.AUTO)

    def test_physical_measure_rejects_non_numeric_and_boolean_values(self) -> None:
        for value in (True, "15"):
            with self.subTest(value=value), self.assertRaises(PrintLayoutError):
                millimetres_to_points(value)  # type: ignore[arg-type]

    def test_margin_presets_are_symmetric_and_keep_positive_content(self) -> None:
        page = page_dimensions(PaperSize.A4, Orientation.PORTRAIT)
        expected_millimetres = {
            MarginPreset.NONE: 0.0,
            MarginPreset.SMALL: 7.5,
            MarginPreset.NORMAL: 15.0,
        }
        for preset, millimetres in expected_millimetres.items():
            with self.subTest(preset=preset):
                content = page_content_rect(PaperSize.A4, Orientation.PORTRAIT, preset)
                margin = millimetres_to_points(millimetres)
                self.assertAlmostEqual(content.x, margin)
                self.assertAlmostEqual(content.y, margin)
                self.assertAlmostEqual(content.width, page.width - 2 * margin)
                self.assertAlmostEqual(content.height, page.height - 2 * margin)
                self.assertGreater(content.width, 0)
                self.assertGreater(content.height, 0)
                self.assertLessEqual(content.x + content.width, page.width)
                self.assertLessEqual(content.y + content.height, page.height)

    def test_layout_requests_are_immutable_and_reject_invalid_contracts(self) -> None:
        request = ImagePageLayout(images_per_page=4)
        poster = PosterLayout()
        with self.assertRaises(FrozenInstanceError):
            request.images_per_page = 2  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            poster.show_crop_marks = True  # type: ignore[misc]
        with self.assertRaises(PrintLayoutError):
            ImagePageLayout(images_per_page=6)
        with self.assertRaises(PrintLayoutError):
            PosterLayout(show_crop_marks=1)  # type: ignore[arg-type]


class ImageGridTests(unittest.TestCase):
    def test_one_two_and_four_slots_are_positive_ordered_and_inside_content(
        self,
    ) -> None:
        for orientation in (Orientation.PORTRAIT, Orientation.LANDSCAPE):
            for count in (1, 2, 4):
                with self.subTest(orientation=orientation, count=count):
                    content = page_content_rect(
                        PaperSize.A4, orientation, MarginPreset.NORMAL
                    )
                    slots = image_slots(
                        PaperSize.A4,
                        orientation,
                        MarginPreset.NORMAL,
                        count,
                    )
                    self.assertEqual(len(slots), count)
                    for slot in slots:
                        self.assertGreater(slot.width, 0)
                        self.assertGreater(slot.height, 0)
                        self.assertGreaterEqual(slot.x, content.x)
                        self.assertGreaterEqual(slot.y, content.y)
                        self.assertLessEqual(
                            slot.x + slot.width,
                            content.x + content.width + 1e-9,
                        )
                        self.assertLessEqual(
                            slot.y + slot.height,
                            content.y + content.height + 1e-9,
                        )
                    self._assert_no_overlap(slots)
                    self.assertEqual(
                        slots,
                        tuple(sorted(slots, key=lambda slot: (slot.y, slot.x))),
                    )

    def test_two_images_use_rows_in_portrait_and_columns_in_landscape(self) -> None:
        portrait = image_slots(
            PaperSize.A4, Orientation.PORTRAIT, MarginPreset.SMALL, 2
        )
        landscape = image_slots(
            PaperSize.A4, Orientation.LANDSCAPE, MarginPreset.SMALL, 2
        )
        self.assertEqual(portrait[0].x, portrait[1].x)
        self.assertLess(portrait[0].y, portrait[1].y)
        self.assertEqual(landscape[0].y, landscape[1].y)
        self.assertLess(landscape[0].x, landscape[1].x)

    def test_spacing_is_small_positive_and_deterministic(self) -> None:
        spacings = [cell_spacing(preset) for preset in MarginPreset]
        self.assertTrue(all(spacing > 0 for spacing in spacings))
        self.assertEqual(spacings, sorted(spacings))
        self.assertEqual(cell_spacing(MarginPreset.NORMAL), spacings[-1])

    @staticmethod
    def _assert_no_overlap(slots: tuple[Rect, ...]) -> None:
        for index, first in enumerate(slots):
            for second in slots[index + 1 :]:
                separated = (
                    first.x + first.width <= second.x
                    or second.x + second.width <= first.x
                    or first.y + first.height <= second.y
                    or second.y + second.height <= first.y
                )
                if not separated:
                    raise AssertionError(f"Células sobrepostas: {first!r} e {second!r}")


class ContainTests(unittest.TestCase):
    def test_poster_panel_float_rounding_never_places_image_outside_cell(self) -> None:
        for grid in (PosterGrid.TWO_BY_TWO, PosterGrid.FOUR_BY_FOUR):
            with self.subTest(grid=grid):
                panel = poster_panel_size(
                    PaperSize.A4,
                    Orientation.PORTRAIT,
                    MarginPreset.NORMAL,
                    grid,
                    OverlapPreset.NONE,
                )
                placed = contain_image(
                    (1200, 800), Rect(0, 0, panel.width, panel.height)
                )
                self.assertGreaterEqual(placed.x, 0)
                self.assertGreaterEqual(placed.y, 0)
                self.assertLessEqual(placed.x + placed.width, panel.width)
                self.assertLessEqual(placed.y + placed.height, panel.height)

    def test_portrait_landscape_square_and_extreme_ratios_are_contained(self) -> None:
        cell = Rect(10, 20, 300, 200)
        cases = (
            Size(100, 200),
            Size(200, 100),
            Size(100, 100),
            Size(10_000, 1),
            Size(1, 10_000),
        )
        for image in cases:
            with self.subTest(image=image):
                placed = contain_image(image, cell)
                self.assertGreater(placed.width, 0)
                self.assertGreater(placed.height, 0)
                self.assertGreaterEqual(placed.x, cell.x)
                self.assertGreaterEqual(placed.y, cell.y)
                self.assertLessEqual(placed.x + placed.width, cell.x + cell.width)
                self.assertLessEqual(placed.y + placed.height, cell.y + cell.height)
                self.assertAlmostEqual(
                    placed.width / placed.height,
                    image.width / image.height,
                    places=9,
                )
                self.assertAlmostEqual(
                    placed.x + placed.width / 2,
                    cell.x + cell.width / 2,
                )
                self.assertAlmostEqual(
                    placed.y + placed.height / 2,
                    cell.y + cell.height / 2,
                )

    def test_small_images_can_be_enlarged_and_policy_can_disable_upscale(self) -> None:
        cell = Rect(0, 0, 200, 200)
        enlarged = contain_image((20, 10), cell)
        original = contain_image((20, 10), cell, allow_upscale=False)
        self.assertGreater(enlarged.scale, 1)
        self.assertEqual(original, ContainPlacement(90, 95, 20, 10, 1.0))

    def test_large_image_is_reduced(self) -> None:
        placed = contain_image((2_000, 1_000), Rect(0, 0, 200, 200))
        self.assertLess(placed.scale, 1)
        self.assertEqual((placed.width, placed.height), (200, 100))


class AutoOrientationAndPaginationTests(unittest.TestCase):
    def test_auto_orientation_has_objective_cases_for_one_two_and_four(self) -> None:
        one = ImagePageLayout(images_per_page=1)
        two = ImagePageLayout(images_per_page=2)
        four = ImagePageLayout(images_per_page=4)
        self.assertIs(
            choose_image_page_orientation([(100, 200)], one), Orientation.PORTRAIT
        )
        self.assertIs(
            choose_image_page_orientation([(200, 100)], one), Orientation.LANDSCAPE
        )
        self.assertIs(
            choose_image_page_orientation([(100, 200)] * 2, two),
            Orientation.LANDSCAPE,
        )
        self.assertIs(
            choose_image_page_orientation([(200, 100)] * 2, two),
            Orientation.PORTRAIT,
        )
        self.assertIs(
            choose_image_page_orientation([(100, 200)] * 4, four),
            Orientation.PORTRAIT,
        )
        self.assertIs(
            choose_image_page_orientation([(200, 100)] * 4, four),
            Orientation.LANDSCAPE,
        )

    def test_auto_orientation_tie_is_always_portrait(self) -> None:
        for count in (1, 2, 4):
            with self.subTest(count=count):
                layout = ImagePageLayout(images_per_page=count)
                self.assertIs(
                    choose_image_page_orientation([(100, 100)] * count, layout),
                    Orientation.PORTRAIT,
                )

    def test_explicit_orientation_is_preserved(self) -> None:
        layout = ImagePageLayout(orientation=Orientation.LANDSCAPE, images_per_page=4)
        self.assertIs(
            choose_image_page_orientation([(100, 200)], layout),
            Orientation.LANDSCAPE,
        )

    def test_pagination_preserves_order_without_duplication_or_loss(self) -> None:
        self.assertEqual(paginate_images(tuple(range(5)), 4), ((0, 1, 2, 3), (4,)))
        self.assertEqual(paginate_images(tuple(range(5)), 2), ((0, 1), (2, 3), (4,)))
        self.assertEqual(paginate_images((), 1), ())
        with self.assertRaises(PrintLayoutError):
            paginate_images((1,), 6)


class QualityAndResourceLimitTests(unittest.TestCase):
    def test_quality_presets_map_to_dpi_and_pdfium_scale(self) -> None:
        self.assertEqual(PdfImageQuality.STANDARD.dpi, 150)
        self.assertEqual(PdfImageQuality.HIGH.dpi, 300)
        self.assertAlmostEqual(pdfium_scale(PdfImageQuality.STANDARD), 150 / 72)
        self.assertAlmostEqual(pdfium_scale(PdfImageQuality.HIGH), 300 / 72)

    def test_raster_dimensions_and_rgba_cost_are_synthetic(self) -> None:
        a4 = page_dimensions(PaperSize.A4, Orientation.PORTRAIT)
        width, height = raster_dimensions(a4, PdfImageQuality.STANDARD.dpi)
        self.assertEqual((width, height), (1240, 1754))
        self.assertEqual(estimate_raster_bytes(width, height), width * height * 4)
        self.assertEqual(
            estimate_raster_bytes(10_000, 8_000),
            MAX_CONVERSION_IMAGE_PIXELS * 4,
        )

    def test_high_quality_poster_cost_is_estimated_without_large_allocation(
        self,
    ) -> None:
        a4 = page_dimensions(PaperSize.A4, Orientation.PORTRAIT)
        width, height = raster_dimensions(a4, PdfImageQuality.HIGH.dpi)
        one_page = estimate_raster_bytes(width, height)
        sixteen_pages = one_page * MAX_POSTER_PAGES
        self.assertEqual((width, height), (2480, 3508))
        self.assertGreater(one_page, 30 * 1024 * 1024)
        self.assertGreater(sixteen_pages, 500 * 1024 * 1024)

    def test_conversion_pixel_limit_accepts_boundary_and_rejects_above(self) -> None:
        self.assertEqual(
            validate_conversion_image_dimensions(10_000, 8_000),
            MAX_CONVERSION_IMAGE_PIXELS,
        )
        with self.assertRaises(PrintLayoutError):
            validate_conversion_image_dimensions(10_001, 8_000)

    def test_page_warning_and_hard_limit_are_distinct(self) -> None:
        self.assertFalse(pdf_export_requires_warning(PDF_EXPORT_PAGE_WARNING_THRESHOLD))
        self.assertTrue(
            pdf_export_requires_warning(PDF_EXPORT_PAGE_WARNING_THRESHOLD + 1)
        )
        self.assertTrue(pdf_export_requires_warning(MAX_PDF_EXPORT_PAGES))
        with self.assertRaises(PrintLayoutError):
            pdf_export_requires_warning(MAX_PDF_EXPORT_PAGES + 1)

    def test_pdf_page_dimensions_reject_non_finite_empty_and_absurd_values(
        self,
    ) -> None:
        self.assertEqual(
            validate_pdf_page_dimensions(MAX_PDF_PAGE_POINTS, 792),
            Size(MAX_PDF_PAGE_POINTS, 792),
        )
        for dimensions in (
            (math.nan, 100),
            (math.inf, 100),
            (100, -1),
            (0, 100),
            (MAX_PDF_PAGE_POINTS + 1, 100),
        ):
            with (
                self.subTest(dimensions=dimensions),
                self.assertRaises(PrintLayoutError),
            ):
                validate_pdf_page_dimensions(*dimensions)


class PosterContractTests(unittest.TestCase):
    def test_only_two_three_and_four_square_grids_are_available(self) -> None:
        expected = {
            PosterGrid.TWO_BY_TWO: (2, 2, 4),
            PosterGrid.THREE_BY_THREE: (3, 3, 9),
            PosterGrid.FOUR_BY_FOUR: (4, 4, 16),
        }
        for grid, values in expected.items():
            self.assertEqual((grid.rows, grid.columns, grid.page_count), values)
        self.assertEqual(MAX_POSTER_GRID_DIMENSION, 4)
        self.assertEqual(MAX_POSTER_PAGES, 16)
        with self.assertRaises(ValueError):
            PosterGrid((1, 1))
        with self.assertRaises(ValueError):
            PosterGrid((5, 5))

    def test_page_order_is_left_to_right_then_top_to_bottom(self) -> None:
        grid = PosterGrid.THREE_BY_THREE
        positions = tuple(
            poster_page_position(grid, index) for index in range(grid.page_count)
        )
        self.assertEqual(
            positions,
            (
                (0, 0),
                (0, 1),
                (0, 2),
                (1, 0),
                (1, 1),
                (1, 2),
                (2, 0),
                (2, 1),
                (2, 2),
            ),
        )
        for index, (row, column) in enumerate(positions):
            self.assertEqual(poster_page_index(grid, row, column), index)
        with self.assertRaises(PrintLayoutError):
            poster_page_position(grid, grid.page_count)

    def test_overlap_is_applied_only_between_internal_page_edges(self) -> None:
        grid = PosterGrid.THREE_BY_THREE
        content = page_content_rect(
            PaperSize.A4, Orientation.PORTRAIT, MarginPreset.NORMAL
        )
        without = poster_panel_size(
            PaperSize.A4,
            Orientation.PORTRAIT,
            MarginPreset.NORMAL,
            grid,
            OverlapPreset.NONE,
        )
        with_overlap = poster_panel_size(
            PaperSize.A4,
            Orientation.PORTRAIT,
            MarginPreset.NORMAL,
            grid,
            OverlapPreset.SMALL,
        )
        self.assertAlmostEqual(without.width, content.width * 3)
        self.assertAlmostEqual(without.height, content.height * 3)
        self.assertAlmostEqual(
            with_overlap.width,
            without.width - OverlapPreset.SMALL.points * 2,
        )
        self.assertAlmostEqual(
            with_overlap.height,
            without.height - OverlapPreset.SMALL.points * 2,
        )

    def test_poster_auto_orientation_and_tie_break_are_deterministic(self) -> None:
        layout = PosterLayout(grid=PosterGrid.TWO_BY_TWO)
        self.assertIs(
            choose_poster_orientation((2_000, 1_000), layout), Orientation.LANDSCAPE
        )
        self.assertIs(
            choose_poster_orientation((1_000, 2_000), layout), Orientation.PORTRAIT
        )
        self.assertIs(
            choose_poster_orientation((1_000, 1_000), layout), Orientation.PORTRAIT
        )

    def test_effective_ppi_uses_contained_physical_image_and_thresholds(self) -> None:
        panel = Size(720, 720)
        self.assertIs(
            effective_poster_ppi((1_000, 1_000), panel).quality, PpiQuality.OK
        )
        low = effective_poster_ppi((999, 999), panel)
        very_low = effective_poster_ppi((719, 719), panel)
        self.assertAlmostEqual(low.conservative, 99.9)
        self.assertIs(low.quality, PpiQuality.LOW)
        self.assertLess(very_low.conservative, 72)
        self.assertIs(very_low.quality, PpiQuality.VERY_LOW)
        self.assertIs(classify_ppi(100), PpiQuality.OK)
        self.assertIs(classify_ppi(72), PpiQuality.LOW)


if __name__ == "__main__":
    unittest.main()
