from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

import poster_tools
from poster_tools import (
    POSTER_MARGIN,
    POSTER_RENDER_DPI,
    InvalidPosterImageError,
    NormalizedCrop,
    PosterOperationCancelled,
    PosterProgress,
    PosterRequest,
    PosterService,
    PosterToolsError,
    _crop_mark_segments,
    _load_normalized_image,
    _normalized_crop_to_pixels,
    _render_poster_page,
    plan_poster,
)
from print_layout import (
    MarginPreset,
    Orientation,
    OverlapPreset,
    PaperSize,
    PpiQuality,
    PosterGrid,
    PosterLayout,
    page_dimensions,
    raster_dimensions,
)


class PosterPlanningTests(unittest.TestCase):
    def test_grid_paper_orientation_and_overlap_matrix_has_full_coverage(
        self,
    ) -> None:
        for grid in PosterGrid:
            for paper in PaperSize:
                for orientation in Orientation:
                    for overlap in OverlapPreset:
                        with self.subTest(
                            grid=grid,
                            paper=paper,
                            orientation=orientation,
                            overlap=overlap,
                        ):
                            layout = PosterLayout(
                                paper=paper,
                                orientation=orientation,
                                grid=grid,
                                overlap=overlap,
                            )
                            plan = plan_poster((1200, 800), layout)
                            self.assertEqual(plan.page_count, grid.page_count)
                            self.assertEqual(plan.tiles[0].panel_viewport.x, 0)
                            self.assertEqual(plan.tiles[0].panel_viewport.y, 0)
                            last = plan.tiles[-1].panel_viewport
                            self.assertAlmostEqual(
                                last.x + last.width, plan.panel_size.width
                            )
                            self.assertAlmostEqual(
                                last.y + last.height, plan.panel_size.height
                            )
                            for row in range(grid.rows):
                                for column in range(grid.columns - 1):
                                    left = plan.tiles[row * grid.columns + column]
                                    right = plan.tiles[row * grid.columns + column + 1]
                                    self.assertAlmostEqual(
                                        left.panel_viewport.x
                                        + left.panel_viewport.width
                                        - right.panel_viewport.x,
                                        overlap.points,
                                    )
                            for row in range(grid.rows - 1):
                                for column in range(grid.columns):
                                    top = plan.tiles[row * grid.columns + column]
                                    bottom = plan.tiles[
                                        (row + 1) * grid.columns + column
                                    ]
                                    self.assertAlmostEqual(
                                        top.panel_viewport.y
                                        + top.panel_viewport.height
                                        - bottom.panel_viewport.y,
                                        overlap.points,
                                    )

    def test_request_is_frozen_and_uses_only_approved_defaults(self) -> None:
        request = PosterRequest(Path("C:/entrada.png"), Path("C:/saida.pdf"))
        self.assertIs(request.paper, PaperSize.A4)
        self.assertIs(request.orientation, Orientation.AUTO)
        self.assertIs(request.grid, PosterGrid.TWO_BY_TWO)
        self.assertIs(request.overlap, OverlapPreset.SMALL)
        self.assertFalse(request.show_crop_marks)
        self.assertIs(POSTER_MARGIN, MarginPreset.NORMAL)
        self.assertEqual(POSTER_RENDER_DPI, 150)
        with self.assertRaises((AttributeError, TypeError)):
            request.grid = PosterGrid.FOUR_BY_FOUR  # type: ignore[misc]

    def test_only_exact_square_grids_produce_four_nine_or_sixteen_pages(self) -> None:
        for grid, expected in (
            (PosterGrid.TWO_BY_TWO, 4),
            (PosterGrid.THREE_BY_THREE, 9),
            (PosterGrid.FOUR_BY_FOUR, 16),
        ):
            with self.subTest(grid=grid):
                plan = self._matching_plan(grid, OverlapPreset.NONE)
                self.assertEqual(plan.page_count, expected)
                self.assertEqual(
                    tuple((tile.row, tile.column) for tile in plan.tiles),
                    tuple(
                        (row, column)
                        for row in range(grid.rows)
                        for column in range(grid.columns)
                    ),
                )

    def test_overlap_is_present_only_on_internal_edges_for_every_grid(self) -> None:
        for grid in PosterGrid:
            without = self._matching_plan(grid, OverlapPreset.NONE)
            with_overlap = self._matching_plan(grid, OverlapPreset.SMALL)
            overlap = OverlapPreset.SMALL.points
            self.assertAlmostEqual(
                without.panel_size.width - with_overlap.panel_size.width,
                overlap * (grid.columns - 1),
            )
            self.assertAlmostEqual(
                without.panel_size.height - with_overlap.panel_size.height,
                overlap * (grid.rows - 1),
            )
            first = with_overlap.tiles[0].panel_viewport
            second = with_overlap.tiles[1].panel_viewport
            below = with_overlap.tiles[grid.columns].panel_viewport
            self.assertAlmostEqual(first.x + first.width - second.x, overlap)
            self.assertAlmostEqual(first.y + first.height - below.y, overlap)
            self.assertEqual(first.x, 0)
            self.assertEqual(first.y, 0)
            last = with_overlap.tiles[-1].panel_viewport
            self.assertAlmostEqual(last.x + last.width, with_overlap.panel_size.width)
            self.assertAlmostEqual(last.y + last.height, with_overlap.panel_size.height)

    def test_no_overlap_has_exact_adjacent_source_crops(self) -> None:
        plan = self._matching_plan(PosterGrid.TWO_BY_TWO, OverlapPreset.NONE)
        crops = tuple(tile.source_crop for tile in plan.tiles)
        self.assertTrue(all(crop is not None for crop in crops))
        first, second, third, fourth = crops
        assert first and second and third and fourth
        self.assertAlmostEqual(first.left, 0)
        self.assertAlmostEqual(first.top, 0)
        self.assertAlmostEqual(first.right, second.left)
        self.assertAlmostEqual(first.bottom, third.top)
        self.assertAlmostEqual(fourth.right, 1)
        self.assertAlmostEqual(fourth.bottom, 1)

    def test_overlap_repeats_a_deliberate_strip_between_adjacent_pages(self) -> None:
        plan = self._matching_plan(PosterGrid.TWO_BY_TWO, OverlapPreset.SMALL)
        first = plan.tiles[0].source_crop
        second = plan.tiles[1].source_crop
        third = plan.tiles[2].source_crop
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        assert first and second and third
        self.assertGreater(first.right, second.left)
        self.assertGreater(first.bottom, third.top)

    def test_three_and_four_grids_cover_corners_and_center(self) -> None:
        for grid in (PosterGrid.THREE_BY_THREE, PosterGrid.FOUR_BY_FOUR):
            with self.subTest(grid=grid):
                plan = self._matching_plan(grid, OverlapPreset.NONE)
                first = plan.tiles[0].source_crop
                last = plan.tiles[-1].source_crop
                assert first and last
                self.assertAlmostEqual(first.left, 0)
                self.assertAlmostEqual(first.top, 0)
                self.assertAlmostEqual(last.right, 1)
                self.assertAlmostEqual(last.bottom, 1)
                central = tuple(
                    tile.source_crop
                    for tile in plan.tiles
                    if tile.source_crop
                    and tile.source_crop.left <= 0.5 <= tile.source_crop.right
                    and tile.source_crop.top <= 0.5 <= tile.source_crop.bottom
                )
                self.assertTrue(central)

    def test_contain_preserves_ratio_centers_and_never_crops(self) -> None:
        plan = plan_poster(
            (4_000, 500),
            PosterLayout(
                orientation=Orientation.PORTRAIT,
                grid=PosterGrid.THREE_BY_THREE,
                overlap=OverlapPreset.SMALL,
            ),
        )
        placement = plan.image_placement
        self.assertAlmostEqual(placement.width / placement.height, 8.0)
        self.assertAlmostEqual(placement.x * 2 + placement.width, plan.panel_size.width)
        self.assertAlmostEqual(
            placement.y * 2 + placement.height, plan.panel_size.height
        )
        self.assertLessEqual(placement.width, plan.panel_size.width)
        self.assertLessEqual(placement.height, plan.panel_size.height)
        self.assertTrue(any(tile.source_crop is None for tile in plan.tiles))

    def test_orientation_auto_and_explicit_contracts_are_preserved(self) -> None:
        wide = plan_poster((2_000, 1_000), PosterLayout())
        tall = plan_poster((1_000, 2_000), PosterLayout())
        explicit = plan_poster(
            (2_000, 1_000), PosterLayout(orientation=Orientation.PORTRAIT)
        )
        self.assertIs(wide.orientation, Orientation.LANDSCAPE)
        self.assertIs(tall.orientation, Orientation.PORTRAIT)
        self.assertIs(explicit.orientation, Orientation.PORTRAIT)

    def test_ppi_result_is_structured_and_low_quality_does_not_block(self) -> None:
        low = plan_poster(
            (100, 100),
            PosterLayout(
                orientation=Orientation.PORTRAIT,
                grid=PosterGrid.FOUR_BY_FOUR,
            ),
        )
        good = plan_poster(
            (10_000, 10_000),
            PosterLayout(orientation=Orientation.PORTRAIT),
        )
        self.assertIs(low.effective_ppi.quality, PpiQuality.VERY_LOW)
        self.assertGreater(low.page_count, 0)
        self.assertIs(good.effective_ppi.quality, PpiQuality.OK)

    def test_pixel_crop_uses_floor_ceil_and_clamps(self) -> None:
        crop = NormalizedCrop(0.101, 0.201, 0.899, 0.799)
        self.assertEqual(
            _normalized_crop_to_pixels(crop, (100, 100)),
            (10, 20, 90, 80),
        )
        edge = NormalizedCrop(0.0, 0.0, 1.0, 1.0)
        self.assertEqual(_normalized_crop_to_pixels(edge, (3, 5)), (0, 0, 3, 5))

    def test_crop_marks_stay_in_margins_and_never_cross_art(self) -> None:
        plan = self._matching_plan(PosterGrid.TWO_BY_TWO, OverlapPreset.NONE)
        page_pixels = raster_dimensions(plan.page_size, POSTER_RENDER_DPI)
        segments = _crop_mark_segments(plan.content_rect, page_pixels)
        scale = POSTER_RENDER_DPI / 72
        left = math.floor(plan.content_rect.x * scale)
        top = math.floor(plan.content_rect.y * scale)
        right = math.ceil((plan.content_rect.x + plan.content_rect.width) * scale)
        bottom = math.ceil((plan.content_rect.y + plan.content_rect.height) * scale)
        self.assertEqual(len(segments), 8)
        for start, end in segments:
            for x, y in (start, end):
                self.assertFalse(left < x < right and top < y < bottom)

    @staticmethod
    def _matching_plan(grid: PosterGrid, overlap: OverlapPreset):
        layout = PosterLayout(
            orientation=Orientation.PORTRAIT,
            grid=grid,
            overlap=overlap,
        )
        provisional = plan_poster((1, 1), layout)
        return plan_poster(
            (provisional.panel_size.width, provisional.panel_size.height), layout
        )


class PosterRenderingTests(unittest.TestCase):
    def test_quadrant_markers_follow_row_major_order_without_overlap(self) -> None:
        layout = PosterLayout(
            orientation=Orientation.PORTRAIT,
            grid=PosterGrid.TWO_BY_TWO,
            overlap=OverlapPreset.NONE,
        )
        provisional = plan_poster((1, 1), layout)
        width = 400
        height = round(
            width * provisional.panel_size.height / provisional.panel_size.width
        )
        image = Image.new("RGB", (width, height), "white")
        colors = ((255, 0, 0), (0, 128, 0), (0, 0, 255), (255, 255, 0))
        half_width = width // 2
        half_height = height // 2
        for box, color in zip(
            (
                (0, 0, half_width, half_height),
                (half_width, 0, width, half_height),
                (0, half_height, half_width, height),
                (half_width, half_height, width, height),
            ),
            colors,
            strict=True,
        ):
            marker = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), color)
            image.paste(marker, box[:2])
            marker.close()
        plan = plan_poster(image.size, layout)
        try:
            for tile, expected in zip(plan.tiles, colors, strict=True):
                page = _render_poster_page(image, plan, tile, show_crop_marks=False)
                try:
                    center = (
                        page.width // 2,
                        page.height // 2,
                    )
                    actual = page.getpixel(center)
                    self.assertLessEqual(
                        sum(
                            abs(channel - target)
                            for channel, target in zip(actual, expected)
                        ),
                        10,
                    )
                finally:
                    page.close()
        finally:
            image.close()

    def test_crop_marks_toggle_changes_only_margin_pixels(self) -> None:
        image = Image.new("RGB", (300, 450), "purple")
        plan = plan_poster(
            image.size,
            PosterLayout(
                orientation=Orientation.PORTRAIT,
                overlap=OverlapPreset.NONE,
            ),
        )
        without = _render_poster_page(image, plan, plan.tiles[0], show_crop_marks=False)
        with_marks = _render_poster_page(
            image, plan, plan.tiles[0], show_crop_marks=True
        )
        try:
            self.assertNotEqual(without.tobytes(), with_marks.tobytes())
            center = (with_marks.width // 2, with_marks.height // 2)
            self.assertEqual(without.getpixel(center), with_marks.getpixel(center))
        finally:
            without.close()
            with_marks.close()
            image.close()


class PosterServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "Pôster com espaços 你好"
        self.root.mkdir()
        self.source = self.root / "entrada transparente.png"
        image = Image.new("RGBA", (80, 120), (255, 0, 0, 128))
        image.save(self.source)
        image.close()
        self.output = self.root / "painel final.pdf"
        self.service = PosterService()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def request(self, **changes: object) -> PosterRequest:
        values: dict[str, object] = {
            "input_path": self.source,
            "output_path": self.output,
            "orientation": Orientation.PORTRAIT,
            "grid": PosterGrid.TWO_BY_TWO,
            "overlap": OverlapPreset.NONE,
        }
        values.update(changes)
        return PosterRequest(**values)  # type: ignore[arg-type]

    def test_creates_valid_four_page_pdf_flattens_alpha_and_preserves_input(
        self,
    ) -> None:
        before = self.source.read_bytes()
        progress: list[PosterProgress] = []
        result = self.service.create(self.request(progress=progress.append))
        self.assertEqual(result.page_count, 4)
        self.assertEqual(progress, [PosterProgress(index, 4) for index in range(5)])
        self.assertEqual(self.source.read_bytes(), before)
        reader = PdfReader(self.output)
        self.assertEqual(len(reader.pages), 4)
        expected = page_dimensions(PaperSize.A4, Orientation.PORTRAIT)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), expected.width, delta=1)
            self.assertAlmostEqual(
                float(page.mediabox.height), expected.height, delta=1
            )
        self.assertEqual(tuple(self.root.glob(".*.tmp.pdf")), ())

    def test_file_handles_are_closed_after_success(self) -> None:
        self.service.create(self.request())
        renamed_source = self.source.with_name("renomeada.png")
        renamed_output = self.output.with_name("renomeado.pdf")
        self.source.rename(renamed_source)
        self.output.rename(renamed_output)
        self.assertTrue(renamed_source.is_file())
        self.assertTrue(renamed_output.is_file())

    def test_loader_supports_jpeg_rgb_rgba_palette_transparency_and_exif(self) -> None:
        rgb_path = self.root / "rgb.jpg"
        rgba_path = self.root / "rgba.png"
        palette_path = self.root / "paleta.png"
        exif_path = self.root / "orientada.jpg"

        Image.new("RGB", (12, 8), "blue").save(rgb_path, quality=95)
        Image.new("RGBA", (12, 8), (255, 0, 0, 0)).save(rgba_path)
        palette = Image.new("P", (12, 8))
        palette.putpalette([255, 0, 0] + [0, 0, 0] * 255)
        palette.info["transparency"] = 0
        palette.save(palette_path)
        palette.close()
        oriented = Image.new("RGB", (12, 8), "green")
        exif = oriented.getexif()
        exif[274] = 6
        oriented.save(exif_path, exif=exif)
        oriented.close()

        loaded = tuple(
            _load_normalized_image(path)
            for path in (rgb_path, rgba_path, palette_path, exif_path)
        )
        try:
            self.assertEqual(tuple(image.mode for image in loaded), ("RGB",) * 4)
            self.assertEqual(loaded[1].getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(loaded[2].getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(loaded[3].size, (8, 12))
        finally:
            for image in loaded:
                image.close()

    def test_existing_output_requires_explicit_overwrite(self) -> None:
        self.output.write_bytes(b"anterior")
        with self.assertRaisesRegex(PosterToolsError, "já existe"):
            self.service.create(self.request())
        self.assertEqual(self.output.read_bytes(), b"anterior")
        result = self.service.create(self.request(overwrite=True))
        self.assertEqual(result.output_path, self.output)
        self.assertTrue(self.output.read_bytes().startswith(b"%PDF"))

    def test_cancellation_before_start_creates_nothing(self) -> None:
        cancel = Event()
        cancel.set()
        with self.assertRaises(PosterOperationCancelled):
            self.service.create(self.request(cancel_event=cancel))
        self.assertFalse(self.output.exists())
        self.assertEqual(tuple(self.root.glob(".*.tmp.pdf")), ())

    def test_cancellation_between_pages_rolls_back_existing_output(self) -> None:
        self.output.write_bytes(b"preservar")
        cancel = Event()

        def cancel_after_first(progress: PosterProgress) -> None:
            if progress.completed_pages == 1:
                cancel.set()

        with self.assertRaises(PosterOperationCancelled):
            self.service.create(
                self.request(
                    overwrite=True,
                    cancel_event=cancel,
                    progress=cancel_after_first,
                )
            )
        self.assertEqual(self.output.read_bytes(), b"preservar")
        self.assertEqual(tuple(self.root.glob(".*.tmp.pdf")), ())

    def test_cancellation_after_last_page_prevents_publish(self) -> None:
        cancel = Event()

        def cancel_before_publish(progress: PosterProgress) -> None:
            if progress.completed_pages == progress.total_pages:
                cancel.set()

        with self.assertRaises(PosterOperationCancelled):
            self.service.create(
                self.request(cancel_event=cancel, progress=cancel_before_publish)
            )
        self.assertFalse(self.output.exists())
        self.assertEqual(tuple(self.root.glob(".*.tmp.pdf")), ())

    def test_render_failure_mid_operation_preserves_existing_output(self) -> None:
        self.output.write_bytes(b"resultado anterior")
        original = poster_tools._render_poster_page
        calls = 0

        def fail_on_second(*args: object, **kwargs: object) -> Image.Image:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("falha sintética")
            return original(*args, **kwargs)  # type: ignore[arg-type]

        with (
            patch("poster_tools._render_poster_page", side_effect=fail_on_second),
            self.assertRaisesRegex(PosterToolsError, "Não foi possível criar"),
        ):
            self.service.create(self.request(overwrite=True))
        self.assertEqual(self.output.read_bytes(), b"resultado anterior")
        self.assertEqual(tuple(self.root.glob(".*.tmp.pdf")), ())

    def test_pages_are_closed_before_the_next_page_is_rendered(self) -> None:
        original = poster_tools._render_poster_page
        rendered: list[Image.Image] = []

        def observed(*args: object, **kwargs: object) -> Image.Image:
            if rendered:
                with self.assertRaises(ValueError):
                    rendered[-1].getpixel((0, 0))
            page = original(*args, **kwargs)  # type: ignore[arg-type]
            rendered.append(page)
            return page

        with patch("poster_tools._render_poster_page", side_effect=observed):
            self.service.create(self.request())
        self.assertEqual(len(rendered), 4)
        for page in rendered:
            with self.assertRaises(ValueError):
                page.getpixel((0, 0))

    def test_rejects_relative_unc_unsupported_and_invalid_images(self) -> None:
        cases = (
            PosterRequest(Path("relativa.png"), self.output),
            PosterRequest(Path(r"\\servidor\imagem.png"), self.output),
        )
        for request in cases:
            with (
                self.subTest(source=request.input_path),
                self.assertRaises(InvalidPosterImageError),
            ):
                self.service.create(request)
        text = self.root / "falsa.png"
        text.write_text("não é imagem", encoding="utf-8")
        with self.assertRaises(InvalidPosterImageError):
            self.service.create(
                PosterRequest(text, self.output, orientation=Orientation.PORTRAIT)
            )
        jpg_named_gif = self.root / "falso.jpg"
        Image.new("RGB", (10, 10), "red").save(jpg_named_gif, format="GIF")
        with self.assertRaises(InvalidPosterImageError):
            self.service.create(
                PosterRequest(
                    jpg_named_gif, self.output, orientation=Orientation.PORTRAIT
                )
            )

    def test_rejects_relative_unc_or_non_pdf_outputs(self) -> None:
        outputs = (
            Path("relativo.pdf"),
            Path(r"\\servidor\saida.pdf"),
            self.root / "saida.txt",
        )
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(PosterToolsError):
                self.service.create(self.request(output_path=output))

    def test_reparse_or_missing_input_is_reported_as_controlled_error(self) -> None:
        with patch(
            "poster_tools.validate_local_regular_file",
            side_effect=poster_tools.LocalFilesError("Entrada insegura."),
        ):
            with self.assertRaisesRegex(InvalidPosterImageError, "insegura"):
                self.service.create(self.request())
        self.source.unlink()
        with self.assertRaises(InvalidPosterImageError):
            self.service.create(self.request())

    def test_output_reparse_or_inaccessible_parent_is_controlled(self) -> None:
        with patch(
            "poster_tools.validate_local_output_path",
            side_effect=poster_tools.LocalFilesError("Saída insegura."),
        ):
            with self.assertRaisesRegex(PosterToolsError, "insegura"):
                self.service.create(self.request())

    def test_oversized_image_is_rejected_before_rendering(self) -> None:
        with patch(
            "poster_tools.validate_conversion_image_dimensions",
            side_effect=poster_tools.PrintLayoutError("grande"),
        ):
            with self.assertRaisesRegex(InvalidPosterImageError, "limite seguro"):
                self.service.create(self.request())
        self.assertFalse(self.output.exists())

    def test_invalid_hooks_and_callback_failure_are_controlled(self) -> None:
        with self.assertRaises(PosterToolsError):
            self.request(progress=object())
        with self.assertRaises(PosterToolsError):
            self.request(cancel_event=object())

        def fail(_progress: PosterProgress) -> None:
            raise RuntimeError("detalhe interno")

        with self.assertRaisesRegex(PosterToolsError, "comunicar"):
            self.service.create(self.request(progress=fail))
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
