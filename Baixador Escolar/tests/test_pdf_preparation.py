"""Real export parity, non-destructive rotation, preparation and persisted settings."""

from contextlib import closing
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch, Mock

from PIL import Image, ImageDraw, ImageChops, ImageStat
from pypdf import PdfReader

from pdf_tools import PdfToolsService, PdfToolsError
from pdf_previews import PageRenderer, PreviewSpec, PreviewCancelled
from image_preparation import ImagePreparationReader, PRINT_WARNING_PPI
from print_layout import ImagePageLayout, PaperSize, Orientation, MarginPreset
from tests.test_pdf_previews import native_image
from settings import normalize_settings, save_settings, load_settings
import paths
from pdf_results import (
    PdfResultReader,
    ResultRequest,
    open_pdf_result_file,
    open_pdf_result_folder,
)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="goal4-prepare-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.first = self.root / "Foto ação 你好.png"
        self.second = self.root / "Outra.png"
        with Image.new("RGBA", (360, 180), (255, 0, 0, 180)) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 179, 89), fill=(0, 0, 255, 255))
            image.save(self.first)
        with Image.new("RGB", (120, 260), "green") as image:
            image.save(self.second)
        self.renderer = PageRenderer()
        self.addCleanup(self.renderer.close)
        self.analyzer = ImagePreparationReader()
        self.addCleanup(self.analyzer.close)

    def test_all_angles_exif_alpha_and_reorder_match_real_export_pixels(self):
        exif_path = self.root / "EXIF.jpg"
        with Image.new("RGB", (220, 90), "yellow") as image:
            ImageDraw.Draw(image).rectangle((0, 0, 70, 89), fill="red")
            exif = Image.Exif()
            exif[274] = 6
            image.save(exif_path, exif=exif)
        originals = {p: p.read_bytes() for p in (self.first, self.second, exif_path)}
        for angle in (0, 90, 180, 270):
            layout = ImagePageLayout(images_per_page=2)
            inputs = (exif_path, self.first, self.second)
            rotations = (angle, (angle + 90) % 360, 0)
            output = self.root / f"angle-{angle}.pdf"
            PdfToolsService().images_to_pdf(
                inputs, output, layout=layout, rotations=rotations
            )
            spec = PreviewSpec("images", inputs, layout, rotations=rotations)
            for index in (0, 1):
                raster = self.renderer.render(spec, index, (450, 500))
                with (
                    closing(raster.image()) as preview,
                    closing(native_image(output, index, preview.size)) as exported,
                ):
                    with (
                        exported.resize(preview.size) as resized,
                        ImageChops.difference(preview, resized) as delta,
                    ):
                        self.assertLess(max(ImageStat.Stat(delta).mean), 8)
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})

    def test_invalid_rotations_and_cancel_preserve_output(self):
        output = self.root / "existing.pdf"
        output.write_bytes(b"original-output")
        for rotations in ((45,), (True,), (0, 90), ("90",)):
            with self.subTest(angles=rotations), self.assertRaises(PdfToolsError):
                PdfToolsService().images_to_pdf(
                    (self.first,), output, rotations=rotations, overwrite=True
                )
        cancel = Event()
        cancel.set()
        with self.assertRaises(PdfToolsError):
            PdfToolsService().images_to_pdf(
                (self.first,),
                output,
                rotations=(90,),
                overwrite=True,
                cancel_event=cancel,
            )
        self.assertEqual(output.read_bytes(), b"original-output")
        self.assertEqual(set(self.root.iterdir()), {self.first, self.second, output})

    def test_estimated_range_contains_real_flat_and_photo_outputs(self):
        noise = self.root / "Photo.jpg"
        with Image.effect_noise((1200, 800), 70).convert("RGB") as image:
            image.save(noise, quality=90)
        inputs = (self.first, self.second, noise)
        for n in (1, 2, 4):
            for paper in (PaperSize.A4, PaperSize.LETTER):
                layout = ImagePageLayout(
                    paper=paper, images_per_page=n, orientation=Orientation.AUTO
                )
                spec = PreviewSpec("images", inputs, layout, rotations=(90, 0, 270))
                before = set(self.root.iterdir())
                report = self.analyzer.bundle(spec, 0, (), None)
                self.assertEqual(before, set(self.root.iterdir()))
                self.assertIsNotNone(report.estimated_bytes, report.message)
                output = self.root / f"{n}-{paper.name}.pdf"
                PdfToolsService().images_to_pdf(
                    inputs, output, layout=layout, rotations=spec.rotations
                )
                low, high = report.estimated_bytes
                self.assertLess(low, high)
                self.assertTrue(
                    low <= output.stat().st_size <= high,
                    (low, output.stat().st_size, high),
                )

    def test_print_quality_uses_physical_layout_and_never_blocks_export(self):
        reports = []
        for n in (1, 2, 4):
            spec = PreviewSpec(
                "images",
                (self.first,) * n,
                ImagePageLayout(images_per_page=n, orientation=Orientation.PORTRAIT),
            )
            report = self.analyzer.bundle(spec, 0, (), None)
            reports.append(report.qualities[0].dpi)
            output = self.root / f"low-quality-{n}.pdf"
            PdfToolsService().images_to_pdf(spec.paths, output, layout=spec.layout)
            self.assertEqual(len(PdfReader(output).pages), 1)
        self.assertLess(reports[0], PRINT_WARNING_PPI)
        self.assertGreater(reports[2], reports[0])
        high = self.root / "High.png"
        with Image.new("RGB", (3000, 2400), "blue") as image:
            image.save(high)
        good = self.analyzer.bundle(
            PreviewSpec("images", (high,), ImagePageLayout()), 0, (), None
        )
        self.assertEqual(good.qualities[0].dpi, 150)
        landscape = self.analyzer.bundle(
            PreviewSpec(
                "images",
                (self.first,),
                ImagePageLayout(
                    orientation=Orientation.LANDSCAPE, margin=MarginPreset.NONE
                ),
            ),
            0,
            (),
            None,
        )
        self.assertNotEqual(landscape.qualities[0].dpi, reports[0])

    def test_analysis_limits_missing_sources_cancellation_and_bounded_cache(self):
        spec = PreviewSpec("images", (self.first,), ImagePageLayout())
        token = Event()
        token.set()
        with self.assertRaises(PreviewCancelled):
            self.analyzer.bundle(spec, 0, (), token)
        with patch("image_preparation.MAX_ANALYSIS_IMAGES", 0):
            self.assertIsNone(self.analyzer.bundle(spec, 0, (), None).estimated_bytes)
        with patch("image_preparation.MAX_ESTIMATE_PAGES", 0):
            report = self.analyzer.bundle(spec, 0, (), None)
            self.assertTrue(report.qualities)
            self.assertIsNone(report.estimated_bytes)
        with patch.object(self.analyzer.renderer, "render", side_effect=ValueError):
            report = self.analyzer.bundle(spec, 0, (), None)
            self.assertTrue(report.qualities)
            self.assertIsNone(report.estimated_bytes)
            self.assertIn("indisponível", report.message)
        for angle in (0, 90, 180, 270) * 4:
            self.analyzer.bundle(replace(spec, rotations=(angle,)), 0, (), None)
            self.assertLessEqual(self.analyzer.renderer.cache.bytes, 8 * 1024 * 1024)
        self.analyzer.close()
        self.assertEqual(self.analyzer.renderer.cache.bytes, 0)
        self.first.unlink()
        self.assertIsNone(self.analyzer.bundle(spec, 0, (), None).estimated_bytes)


class PdfPreferencesTests(unittest.TestCase):
    def test_old_invalid_and_corrupt_preferences_preserve_other_settings(self):
        raw = {
            "tema": "Escuro",
            "ultima_qualidade": "720p",
            "dialog_folders": {"pdf.output": "C:/Fixtures"},
            "pdf_preferences": {
                "images_paper": "Carta",
                "images_per_page": "4 por página",
                "poster_crop_marks": True,
                "poster_grid": "bad",
                "paths": ["private"],
                "zoom": 2,
            },
        }
        result = normalize_settings(raw)
        self.assertEqual(
            result["pdf_preferences"],
            {
                "images_paper": "Carta",
                "images_per_page": "4 por página",
                "poster_crop_marks": True,
            },
        )
        self.assertEqual(result["dialog_folders"], raw["dialog_folders"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(raw, path)
            self.assertEqual(load_settings(path), result)
            path.write_text("{broken", encoding="utf-8")
            self.assertNotIn("pdf_preferences", load_settings(path))
            with patch("settings.save_settings", side_effect=PermissionError):
                path.write_text("{broken", encoding="utf-8")
                self.assertIsInstance(load_settings(path), dict)
        self.assertNotIn("pdf_preferences", normalize_settings({}))

    def test_frozen_preferences_are_retained_in_each_users_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / "Protected"
            program.mkdir()
            with (
                patch("paths.sys.frozen", True, create=True),
                patch("paths.sys.executable", str(program / "EduDownloader.exe")),
            ):
                targets = []
                for name, value in (("ProfileA", "A4"), ("ProfileB", "Carta")):
                    profile = root / name
                    profile.mkdir()
                    with patch.dict(os.environ, {"LOCALAPPDATA": str(profile)}):
                        save_settings({"pdf_preferences": {"images_paper": value}})
                        target = paths.get_settings_path()
                        self.assertTrue(target.is_relative_to(profile))
                        self.assertEqual(
                            load_settings()["pdf_preferences"]["images_paper"], value
                        )
                        targets.append(target)
                self.assertNotEqual(*targets)
            self.assertEqual(list(program.iterdir()), [])


class PdfResultTests(unittest.TestCase):
    def test_metadata_open_missing_changed_invalid_type_and_multiple_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "Aula ação 你好.pdf"
            first.write_bytes(b"controlled-pdf")
            second = root / "page.png"
            second.write_bytes(b"controlled-image")
            reader = PdfResultReader()
            info = reader.bundle(ResultRequest((first, second)), 0, (), None)
            self.assertEqual(
                info.size_bytes, first.stat().st_size + second.stat().st_size
            )
            action = Mock(return_value=True)
            opened = reader.bundle(
                ResultRequest((first,), action, info.identity), 0, (), None
            )
            self.assertTrue(opened.opened)
            action.assert_called_once_with(first)
            first.write_bytes(b"changed")
            self.assertTrue(
                reader.bundle(
                    ResultRequest((first,), action, info.identity), 0, (), None
                ).error
            )
            executable = root / "not-a-result.exe"
            executable.write_bytes(b"fixture")
            self.assertTrue(
                reader.bundle(ResultRequest((executable,), action), 0, (), None).error
            )
            first.unlink()
            self.assertTrue(reader.bundle(ResultRequest((first,)), 0, (), None).error)

    def test_windows_launch_uses_validated_arguments_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PDF ação & espaço.pdf"
            path.write_bytes(b"fixture")
            with patch("local_files.os.startfile", create=True) as start:
                self.assertTrue(open_pdf_result_file(path))
                start.assert_called_once_with(str(path))
            with patch("local_files.subprocess.Popen") as popen:
                self.assertTrue(open_pdf_result_folder(path))
                self.assertEqual(
                    popen.call_args.args[0], ["explorer.exe", "/select,", str(path)]
                )
                self.assertFalse(popen.call_args.kwargs["shell"])
            with patch("local_files.os.startfile", side_effect=OSError, create=True):
                with self.assertRaises(Exception):
                    open_pdf_result_file(path)
