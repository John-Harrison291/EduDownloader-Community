"""Testes do fluxo da página PDF sem depender de coordenadas de tela."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from PIL import Image

from print_layout import (
    ImagePageLayout,
    MarginPreset,
    Orientation,
    OverlapPreset,
    PaperSize,
    PpiQuality,
    PosterGrid,
    PosterLayout,
)
from ui_pages import (
    _build_images_pdf_preview,
    _build_poster_preview,
    _poster_quality_message,
)


class ImagesPdfPreviewTests(unittest.TestCase):
    def test_preview_uses_print_contracts_for_counts_orientations_and_margins(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            sizes = ((80, 160), (200, 100), (120, 120), (60, 180), (240, 90))
            paths = []
            for index, size in enumerate(sizes, start=1):
                path = directory / f"imagem ação {index}.png"
                Image.new("RGB", size, (20 * index, 80, 140)).save(path)
                paths.append(path)

            for images_per_page, expected_pages in ((1, 5), (2, 3), (4, 2)):
                preview = _build_images_pdf_preview(
                    tuple(paths),
                    ImagePageLayout(images_per_page=images_per_page),
                )
                self.assertEqual(preview.total_pages, expected_pages)
                self.assertEqual(
                    len(preview.placements), min(images_per_page, len(paths))
                )
                self.assertTrue(all(not failed for failed in preview.failed_items))
                for placement, slot in zip(
                    preview.placements, preview.slots, strict=True
                ):
                    self.assertGreaterEqual(placement.x + 1e-9, slot.x)
                    self.assertGreaterEqual(placement.y + 1e-9, slot.y)
                    self.assertLessEqual(
                        placement.x + placement.width,
                        slot.x + slot.width + 1e-9,
                    )
                    self.assertLessEqual(
                        placement.y + placement.height,
                        slot.y + slot.height + 1e-9,
                    )

            for image_count, expected_pages in ((1, 1), (2, 1), (4, 1), (5, 2)):
                partial = _build_images_pdf_preview(
                    tuple(paths[:image_count]),
                    ImagePageLayout(images_per_page=4),
                )
                self.assertEqual(partial.total_pages, expected_pages)
                self.assertEqual(len(partial.placements), min(image_count, 4))

            portrait = _build_images_pdf_preview(
                (paths[0],),
                ImagePageLayout(orientation=Orientation.AUTO),
            )
            landscape = _build_images_pdf_preview(
                (paths[1],),
                ImagePageLayout(
                    paper=PaperSize.LETTER,
                    orientation=Orientation.AUTO,
                ),
            )
            forced = _build_images_pdf_preview(
                tuple(paths[:4]),
                ImagePageLayout(
                    orientation=Orientation.LANDSCAPE,
                    margin=MarginPreset.NONE,
                    images_per_page=4,
                ),
            )
            normal = _build_images_pdf_preview(
                (paths[2],),
                ImagePageLayout(margin=MarginPreset.NORMAL),
            )
            self.assertIs(portrait.orientation, Orientation.PORTRAIT)
            self.assertIs(landscape.orientation, Orientation.LANDSCAPE)
            self.assertIs(forced.orientation, Orientation.LANDSCAPE)
            self.assertEqual(forced.content_rect.width, forced.page_size.width)
            self.assertEqual(forced.content_rect.height, forced.page_size.height)
            self.assertLess(normal.content_rect.width, normal.page_size.width)
            self.assertLess(normal.content_rect.height, normal.page_size.height)

    def test_preview_failure_uses_placeholder_without_mutating_valid_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            valid = directory / "válida.png"
            Image.new("RGBA", (90, 140), (10, 20, 30, 100)).save(valid)
            original = valid.read_bytes()
            missing = directory / "ausente.jpg"

            preview = _build_images_pdf_preview(
                (valid, missing),
                ImagePageLayout(images_per_page=2),
            )

            self.assertEqual(preview.failed_items, (False, True))
            self.assertEqual(len(preview.placements), 2)
            self.assertEqual(valid.read_bytes(), original)
            self.assertFalse(missing.exists())


class PosterPreviewTests(unittest.TestCase):
    def test_quality_levels_have_plain_language_messages(self) -> None:
        self.assertEqual(
            _poster_quality_message(PpiQuality.OK),
            "Qualidade adequada para este tamanho.",
        )
        self.assertEqual(
            _poster_quality_message(PpiQuality.LOW),
            "A imagem pode perder definição neste tamanho.",
        )
        self.assertEqual(
            _poster_quality_message(PpiQuality.VERY_LOW),
            "A imagem pode ficar bastante pixelada neste tamanho.",
        )

    def test_transparent_preview_is_flattened_on_white(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            source = Path(temporary_dir) / "transparente.png"
            Image.new("RGBA", (40, 20), (10, 20, 30, 0)).save(source)
            preview = _build_poster_preview(source, PosterLayout())
            try:
                self.assertEqual(preview.thumbnail.mode, "RGB")
                self.assertEqual(preview.thumbnail.getpixel((0, 0)), (255, 255, 255))
            finally:
                preview.thumbnail.close()

    def test_exif_orientation_is_applied_to_preview_without_changing_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            source = Path(temporary_dir) / "orientação.jpg"
            image = Image.new("RGB", (800, 400), "green")
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)
            image.close()
            original = source.read_bytes()
            preview = _build_poster_preview(source, PosterLayout())
            try:
                self.assertLess(preview.thumbnail.width, preview.thumbnail.height)
                self.assertIs(preview.plan.orientation, Orientation.PORTRAIT)
                self.assertEqual(source.read_bytes(), original)
            finally:
                preview.thumbnail.close()

    def test_preview_uses_engine_geometry_for_every_grid_and_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            source = Path(temporary_dir) / "imagem ação.png"
            Image.new("RGB", (900, 450), "navy").save(source)

            for grid in PosterGrid:
                for orientation in (
                    Orientation.AUTO,
                    Orientation.PORTRAIT,
                    Orientation.LANDSCAPE,
                ):
                    with self.subTest(grid=grid, orientation=orientation):
                        preview = _build_poster_preview(
                            source,
                            PosterLayout(
                                paper=PaperSize.LETTER,
                                orientation=orientation,
                                grid=grid,
                                overlap=OverlapPreset.SMALL,
                                show_crop_marks=True,
                            ),
                        )
                        try:
                            self.assertEqual(preview.plan.page_count, grid.page_count)
                            self.assertLessEqual(preview.thumbnail.width, 480)
                            self.assertLessEqual(preview.thumbnail.height, 360)
                            self.assertEqual(
                                tuple(tile.page_index for tile in preview.plan.tiles),
                                tuple(range(grid.page_count)),
                            )
                            if orientation is not Orientation.AUTO:
                                self.assertIs(preview.plan.orientation, orientation)
                            placement = preview.plan.image_placement
                            self.assertLessEqual(
                                placement.width, preview.plan.panel_size.width
                            )
                            self.assertLessEqual(
                                placement.height, preview.plan.panel_size.height
                            )
                        finally:
                            preview.thumbnail.close()

    def test_preview_failure_is_controlled_without_mutating_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            source = Path(temporary_dir) / "inválida.png"
            source.write_text("não é imagem", encoding="utf-8")
            original = source.read_bytes()
            with self.assertRaises(Exception):
                _build_poster_preview(source, PosterLayout())
            self.assertEqual(source.read_bytes(), original)


class PdfToolsPageRealTkTests(unittest.TestCase):
    def test_poster_preview_result_is_not_retained_when_close_races_with_publish(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk
                    from PIL import Image

                    from ui_pages import PdfPageActions, PdfToolsPage

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target
                        def start(self):
                            self.target()

                    actions = PdfPageActions(
                        show_info=lambda _message: None,
                        show_warning=lambda _message: None,
                        show_error=lambda _message: None,
                        confirm_overwrite=lambda _message: False,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    with tempfile.TemporaryDirectory() as temporary_dir:
                        source = Path(temporary_dir) / "imagem.png"
                        Image.new("RGB", (40, 20), "blue").save(source)
                        page = PdfToolsPage(
                            root,
                            service=object(),
                            actions=actions,
                            thread_factory=ImmediateThread,
                        )
                        page.pack()
                        page.prepare_poster_source(source)
                        queued_results = page._poster_preview_results
                        original_put = queued_results.put_nowait
                        def close_before_publish(result):
                            page.close()
                            original_put(result)
                        with patch.object(
                            queued_results,
                            "put_nowait",
                            side_effect=close_before_publish,
                        ):
                            page._request_poster_preview()
                        result = {
                            "closed": page._closed,
                            "queue_empty": queued_results.empty(),
                        }
                        page.destroy()
                    root.destroy()
                    print(json.dumps(result))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.stdout.startswith("SKIP_TK:"):
            self.skipTest(completed.stdout.strip())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout.strip().splitlines()[-1]),
            {"closed": True, "queue_empty": True},
        )

    def test_poster_ui_preview_progress_cancel_and_stale_handoff(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import time
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk
                    from PIL import Image

                    from poster_tools import (
                        PosterOperationCancelled,
                        PosterResult,
                        PosterToolsError,
                        plan_poster,
                    )
                    from print_layout import Orientation, PosterLayout, Size
                    from ui_pages import PdfPageActions, PdfToolsPage

                    class PdfService:
                        pass

                    class PosterService:
                        def __init__(self):
                            self.requests = []
                            self.fail_next = False

                        def create(self, request):
                            self.requests.append(request)
                            if self.fail_next:
                                self.fail_next = False
                                raise PosterToolsError("imagem inválida")
                            if request.cancel_event.is_set():
                                raise PosterOperationCancelled("cancelada")
                            total = request.grid.page_count
                            request.progress(type("P", (), {
                                "completed_pages": 0,
                                "total_pages": total,
                            })())
                            request.progress(type("P", (), {
                                "completed_pages": total,
                                "total_pages": total,
                            })())
                            plan = plan_poster(Size(1200, 600), PosterLayout(
                                paper=request.paper,
                                orientation=request.orientation,
                                grid=request.grid,
                                overlap=request.overlap,
                                show_crop_marks=request.show_crop_marks,
                            ))
                            return PosterResult(
                                request.output_path,
                                total,
                                plan.orientation,
                                plan.effective_ppi,
                            )

                    pending_operations = []
                    pending_previews = []
                    class ControlledThread:
                        def __init__(self, *, target, name, **_kwargs):
                            self.target = target
                            self.name = name
                        def start(self):
                            if self.name == "edudownloader-pdf-worker":
                                pending_operations.append(self.target)
                            elif self.name == "edudownloader-poster-preview-worker":
                                pending_previews.append(self.target)
                            else:
                                self.target()

                    def pump(root, rounds=12):
                        for _ in range(rounds):
                            root.update()
                            time.sleep(0.03)

                    messages = []
                    actions = PdfPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(("warning", message)),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda _message: True,
                    )
                    poster_service = PosterService()
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        first = directory / "imagem A.png"
                        second = directory / "imagem B.png"
                        output = directory / "poster.pdf"
                        Image.new("RGB", (120, 60), "red").save(first)
                        Image.new("RGB", (2400, 1200), "blue").save(second)
                        page = PdfToolsPage(
                            root,
                            service=PdfService(),
                            poster_service=poster_service,
                            actions=actions,
                            thread_factory=ControlledThread,
                        )
                        page.pack(fill="both", expand=True)
                        root.geometry("860x600")
                        pump(root)
                        initial = {
                            "run": page.poster_run_button.cget("state"),
                            "grid": page._poster_grid.get(),
                            "paper": page._poster_paper.get(),
                            "orientation": page._poster_orientation.get(),
                            "overlap": page._poster_overlap.get(),
                            "marks": page._poster_crop_marks.get(),
                        }

                        assert page.prepare_poster_source(first)
                        pump(root, 8)
                        assert len(pending_previews) == 1
                        page.prepare_poster_source(second)
                        page._poster_grid.set("4 × 4")
                        page._poster_orientation.set("Paisagem")
                        page._poster_overlap.set("Nenhuma")
                        page._poster_crop_marks.set(True)
                        page._on_poster_options_changed()
                        pump(root, 8)
                        pending_previews.pop(0)()
                        pump(root, 4)
                        assert len(pending_previews) == 1
                        pending_previews.pop(0)()
                        pump(root, 6)
                        preview = {
                            "source": page._poster_source.name,
                            "pages": page._poster_preview.plan.page_count,
                            "orientation": page._poster_preview.plan.orientation.value,
                            "quality": page._poster_quality.get(),
                            "summary": page._poster_summary.get(),
                            "run": page.poster_run_button.cget("state"),
                            "tab": page.tab_view.get(),
                        }
                        canvas = page.poster_preview_canvas
                        preview_numbers = sorted(
                            int(canvas.itemcget(item, "text"))
                            for item in canvas.find_all()
                            if canvas.type(item) == "text"
                            and canvas.itemcget(item, "text").isdecimal()
                        )
                        crop_mark_preview = any(
                            canvas.type(item) == "text"
                            and canvas.itemcget(item, "text") == "⌜"
                            for item in canvas.find_all()
                        )
                        summaries = {}
                        quality_by_grid = {}
                        for grid_value in ("2 × 2", "3 × 3", "4 × 4"):
                            page._poster_grid.set(grid_value)
                            page._on_poster_options_changed()
                            pump(root, 8)
                            pending_previews.pop(0)()
                            pump(root, 6)
                            summaries[grid_value] = page._poster_summary.get()
                            quality_by_grid[grid_value] = page._poster_quality.get()
                        page._poster_grid.set("3 × 3")
                        page._poster_orientation.set("Retrato")
                        page._on_poster_options_changed()
                        pump(root, 8)
                        pending_previews.pop(0)()
                        pump(root, 6)
                        portrait_quality = page._poster_quality.get()
                        page._poster_grid.set("4 × 4")
                        page._poster_orientation.set("Paisagem")
                        page._on_poster_options_changed()
                        pump(root, 8)
                        pending_previews.pop(0)()
                        pump(root, 6)
                        root.deiconify()
                        pump(root, 2)
                        layout = {
                            "select": page.poster_select_button.winfo_manager(),
                            "run": page.poster_run_button.winfo_manager(),
                            "cancel": page.poster_cancel_button.winfo_manager(),
                            "canvas_width": page.poster_preview_canvas.winfo_width(),
                            "canvas_height": page.poster_preview_canvas.winfo_height(),
                        }
                        root.withdraw()

                        output.write_bytes(b"pdf anterior")
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ) as save_dialog:
                            page._start_poster()
                        suggested_output = save_dialog.call_args.kwargs["initialfile"]
                        processing = {
                            "run": page.poster_run_button.cget("state"),
                            "cancel": page.poster_cancel_button.cget("state"),
                            "busy": page.is_busy,
                            "state": page._operation_state.value,
                        }
                        pending_operations.pop(0)()
                        page._apply_latest_operation_progress()
                        progress_during_operation = page._poster_progress_text.get()
                        pump(root)
                        completed_state = {
                            "busy": page.is_busy,
                            "state": page._operation_state.value,
                            "progress": page._poster_progress_text.get(),
                            "status": page._status.get(),
                            "request_grid": poster_service.requests[-1].grid.page_count,
                            "request_marks": poster_service.requests[-1].show_crop_marks,
                            "request_overwrite": poster_service.requests[-1].overwrite,
                        }

                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_poster()
                        page.poster_cancel_button.invoke()
                        cancelling = page._status.get()
                        cancelling_state = page._operation_state.value
                        pending_operations.pop(0)()
                        pump(root)
                        cancelled = {
                            "busy": page.is_busy,
                            "state": page._operation_state.value,
                            "status": page._status.get(),
                            "progress": page._poster_progress_text.get(),
                        }

                        poster_service.fail_next = True
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_poster()
                        pending_operations.pop(0)()
                        pump(root)
                        failed = {
                            "busy": page.is_busy,
                            "state": page._operation_state.value,
                            "status": page._status.get(),
                            "message": messages[-1],
                        }

                        page._poster_overlap.set("Pequena")
                        page._on_poster_options_changed()
                        pump(root, 8)
                        pending_previews.pop(0)()
                        pump(root, 6)
                        overlap_indicators = sum(
                            1
                            for item in canvas.find_all()
                            if canvas.type(item) == "rectangle"
                            and bool(canvas.itemcget(item, "dash"))
                        )

                        ctk.set_appearance_mode("Light")
                        page._set_appearance_mode("Light")
                        pump(root, 2)
                        light_theme = canvas.cget("bg")
                        ctk.set_appearance_mode("Dark")
                        page._set_appearance_mode("Dark")
                        pump(root, 2)
                        theme = page.poster_preview_canvas.cget("bg")
                        result = {
                            "initial": initial,
                            "preview": preview,
                            "preview_numbers": preview_numbers,
                            "crop_mark_preview": crop_mark_preview,
                            "overlap_indicators": overlap_indicators,
                            "suggested_output": suggested_output,
                            "processing": processing,
                            "progress_during_operation": progress_during_operation,
                            "completed": completed_state,
                            "cancelling": cancelling,
                            "cancelling_state": cancelling_state,
                            "cancelled": cancelled,
                            "failed": failed,
                            "theme": theme,
                            "light_theme": light_theme,
                            "messages": messages,
                            "summaries": summaries,
                            "quality_by_grid": quality_by_grid,
                            "portrait_quality": portrait_quality,
                            "layout": layout,
                        }
                        page.close()
                        page.destroy()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if completed.stdout.startswith("SKIP_TK:"):
            self.skipTest(completed.stdout.strip())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(
            result["initial"],
            {
                "run": "disabled",
                "grid": "2 × 2",
                "paper": "A4",
                "orientation": "Automática",
                "overlap": "Pequena",
                "marks": False,
            },
        )
        self.assertEqual(result["preview"]["source"], "imagem B.png")
        self.assertEqual(result["preview"]["pages"], 16)
        self.assertEqual(result["preview"]["orientation"], "landscape")
        self.assertEqual(
            result["preview"]["quality"],
            "A imagem pode ficar bastante pixelada neste tamanho.",
        )
        self.assertEqual(
            result["preview"]["summary"], "16 folhas · Painel: 4 × 4 folhas"
        )
        self.assertEqual(result["preview"]["run"], "normal")
        self.assertEqual(result["preview"]["tab"], "Pôster/Painel")
        self.assertEqual(result["preview_numbers"], list(range(1, 17)))
        self.assertTrue(result["crop_mark_preview"])
        self.assertEqual(result["overlap_indicators"], 16)
        self.assertEqual(result["suggested_output"], "imagem B-poster.pdf")
        self.assertEqual(
            result["summaries"],
            {
                "2 × 2": "4 folhas · Painel: 2 × 2 folhas",
                "3 × 3": "9 folhas · Painel: 3 × 3 folhas",
                "4 × 4": "16 folhas · Painel: 4 × 4 folhas",
            },
        )
        self.assertEqual(
            result["quality_by_grid"],
            {
                "2 × 2": "Qualidade adequada para este tamanho.",
                "3 × 3": "A imagem pode perder definição neste tamanho.",
                "4 × 4": "A imagem pode ficar bastante pixelada neste tamanho.",
            },
        )
        self.assertEqual(
            result["portrait_quality"], "Qualidade adequada para este tamanho."
        )
        self.assertEqual(result["layout"]["select"], "grid")
        self.assertEqual(result["layout"]["run"], "grid")
        self.assertEqual(result["layout"]["cancel"], "grid")
        self.assertGreater(result["layout"]["canvas_width"], 100)
        self.assertGreater(result["layout"]["canvas_height"], 100)
        self.assertEqual(
            result["processing"],
            {
                "run": "disabled",
                "cancel": "normal",
                "busy": True,
                "state": "processing",
            },
        )
        self.assertFalse(result["completed"]["busy"])
        self.assertEqual(result["completed"]["state"], "completed")
        self.assertEqual(result["progress_during_operation"], "Página 16 de 16.")
        self.assertEqual(result["completed"]["progress"], "")
        self.assertEqual(result["completed"]["request_grid"], 16)
        self.assertTrue(result["completed"]["request_marks"])
        self.assertTrue(result["completed"]["request_overwrite"])
        self.assertIn("Pôster gerado com sucesso", result["completed"]["status"])
        self.assertEqual(result["cancelling"], "Cancelando...")
        self.assertEqual(result["cancelling_state"], "cancelling")
        self.assertFalse(result["cancelled"]["busy"])
        self.assertEqual(result["cancelled"]["state"], "cancelled")
        self.assertEqual(result["cancelled"]["status"], "Operação PDF cancelada.")
        self.assertEqual(result["cancelled"]["progress"], "Operação cancelada.")
        self.assertEqual(
            result["failed"],
            {
                "busy": False,
                "state": "error",
                "status": "Operação PDF não concluída. Confira os arquivos e tente novamente.",
                "message": ["error", "imagem inválida"],
            },
        )
        self.assertEqual(result["theme"], "#202124")
        self.assertEqual(result["light_theme"], "#E5E7EB")

    def test_merge_metadata_is_bounded_and_stale_removed_item_is_discarded(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import time
                    import tkinter as tk
                    from pathlib import Path
                    import customtkinter as ctk
                    from ui_pages import PdfPageActions, PdfToolsPage
                    from pdf_tools import PdfToolsService
                    from tests.test_pdf_previews import make_pdf

                    actions = PdfPageActions(
                        show_info=lambda _message: None,
                        show_warning=lambda _message: None,
                        show_error=lambda _message: None,
                        confirm_overwrite=lambda _message: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    page = PdfToolsPage(
                        root, service=PdfToolsService(), actions=actions,
                    )
                    page.pack()
                    with tempfile.TemporaryDirectory() as directory:
                        first = Path(directory) / "removido.pdf"
                        second = Path(directory) / "válido.pdf"
                        protected = Path(directory) / "protegido.pdf"
                        make_pdf(first)
                        make_pdf(second, ((240, 360, (0, 1, 0)),) * 3)
                        make_pdf(protected, password="synthetic-password")
                        page.merge_files.add_paths([first, second, protected])
                        worker = page._page_preview_worker
                        thread = worker.thread
                        page.merge_files._selected.set(0)
                        page.merge_files.remove_selected()
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            root.update()
                            pane = page.merge_page_preview
                            if pane._bundle and pane.total == 2 and pane._poll_id is None:
                                break
                            time.sleep(0.005)
                        assert pane._bundle and pane.total == 2
                        result = {
                            "paths": [path.name for path in page.merge_files.paths],
                            "details": [
                                page._merge_detail_for_path(path)
                                for path in page.merge_files.paths
                            ],
                            "removed_detail": page._merge_detail_for_path(first),
                            "workers": [worker.thread.name],
                            "same_worker": thread is worker.thread,
                            "bounded": len(worker.pending) <= 1 and len(worker.results) <= 1,
                            "actual_pixels": bool(pane._bundle.main.rgb),
                            "protected_unavailable": not pane._bundle.thumbs[1][1].rgb,
                        }
                    page.close()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(result["paths"], ["válido.pdf", "protegido.pdf"])
        self.assertIn("3 páginas", result["details"][0])
        self.assertIn("Prévia indisponível", result["details"][1])
        self.assertIsNone(result["removed_detail"])
        self.assertEqual(
            result["workers"],
            ["edudownloader-pdf-preview"],
        )
        self.assertTrue(result["same_worker"])
        self.assertTrue(result["bounded"])
        self.assertTrue(result["actual_pixels"])
        self.assertTrue(result["protected_unavailable"])

    def test_pdf_export_progress_cancel_and_quality_are_ui_thread_safe(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import threading
                    import time
                    import tkinter as tk
                    from pathlib import Path
                    import customtkinter as ctk
                    from pdf_tools import (
                        PdfImageExportResult, PdfOperationCancelled,
                        PdfOperationProgress,
                    )
                    from ui_pages import PdfPageActions, PdfToolsPage

                    class Service:
                        def __init__(self):
                            self.started = threading.Event()
                            self.release = threading.Event()
                            self.qualities = []
                        def pdf_to_image_output_paths(
                            self, source, selection, image_format,
                            output_directory, *, total_pages=None,
                        ):
                            return tuple(
                                Path(output_directory) / f"page-{index:03d}.png"
                                for index in range(1, total_pages + 1)
                            )
                        def pdf_to_images(
                            self, source, selection, image_format,
                            output_directory, *, overwrite=False,
                            quality=None, cancel_event=None, progress=None,
                        ):
                            self.qualities.append(quality.name)
                            progress(PdfOperationProgress(0, 2))
                            progress(PdfOperationProgress(1, 2))
                            self.started.set()
                            # Keep the worker active while Tk processes queued progress,
                            # even when the full suite briefly delays UI scheduling.
                            self.release.wait(10)
                            if cancel_event.is_set():
                                raise PdfOperationCancelled("cancelado")
                            return PdfImageExportResult(
                                Path(output_directory), (), (1, 2)
                            )

                    def pump(root, predicate):
                        end = time.monotonic() + 3
                        while time.monotonic() < end and not predicate():
                            root.update()
                            time.sleep(0.01)
                        root.update()
                        return predicate()

                    messages = []
                    actions = PdfPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(("warning", message)),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda _message: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    service = Service()
                    page = PdfToolsPage(root, service=service, actions=actions)
                    page.pack()
                    with tempfile.TemporaryDirectory() as directory:
                        page._pdf_images_source = Path(directory) / "origem.pdf"
                        page._pdf_images_page_count = 2
                        page._pdf_images_destination = Path(directory)
                        page._pdf_images_quality.set("Alta")
                        page._refresh_controls()
                        page._start_pdf_to_images()
                        assert pump(root, service.started.is_set)
                        assert pump(root, lambda: "1 de 2" in page._pdf_images_progress_text.get())
                        active = {
                            "state": page._operation_state.value,
                            "cancel": page.pdf_images_cancel_button.cget("state"),
                            "run": page.pdf_images_run_button.cget("state"),
                            "progress": page.progress_bar.get(),
                        }
                        page._cancel_pdf_operation("pdf_images")
                        cancelling = page._operation_state.value
                        service.release.set()
                        assert pump(root, lambda: not page.is_busy)
                        result = {
                            "active": active,
                            "cancelling": cancelling,
                            "terminal": page._operation_state.value,
                            "status": page._status.get(),
                            "quality": service.qualities,
                            "messages": messages,
                        }
                    page.close()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(result["active"]["state"], "processing")
        self.assertEqual(result["active"]["cancel"], "normal")
        self.assertEqual(result["active"]["run"], "disabled")
        self.assertAlmostEqual(result["active"]["progress"], 0.5)
        self.assertEqual(result["cancelling"], "cancelling")
        self.assertEqual(result["terminal"], "cancelled")
        self.assertEqual(result["status"], "Operação PDF cancelada.")
        self.assertEqual(result["quality"], ["HIGH"])
        self.assertFalse(result["messages"])

    def test_selection_order_buttons_workers_and_persistent_page_state(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from pdf_tools import PdfImageExportResult, PdfOperationResult
                    from ui_pages import PdfPageActions, PdfToolsPage

                    worker_names = []

                    class ImmediateThread:
                        def __init__(self, *, target, name, **_kwargs):
                            self.target = target
                            worker_names.append(name)

                        def start(self):
                            self.target()

                    class Service:
                        def __init__(self):
                            self.calls = []

                        def page_count(self, source):
                            self.calls.append(("count", Path(source).name))
                            return 7

                        def merge_pdfs(
                            self,
                            inputs,
                            output,
                            *,
                            overwrite=False,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append((
                                "merge",
                                [path.name for path in inputs],
                                Path(output).name,
                                overwrite,
                            ))
                            return PdfOperationResult(Path(output), 3)

                        def extract_pages(
                            self,
                            source,
                            selection,
                            output,
                            *,
                            overwrite=False,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append((
                                "extract",
                                Path(source).name,
                                selection,
                                Path(output).name,
                                overwrite,
                            ))
                            return PdfOperationResult(Path(output), 2)

                        def images_to_pdf(
                            self,
                            inputs,
                            output,
                            *,
                            overwrite=False,
                            layout=None,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append((
                                "images",
                                [path.name for path in inputs],
                                Path(output).name,
                                overwrite,
                                layout.paper.name,
                                layout.orientation.value,
                                layout.margin.name,
                                layout.images_per_page,
                            ))
                            if progress is not None:
                                from pdf_tools import ImagesToPdfProgress

                                progress(ImagesToPdfProgress(0, len(inputs)))
                                progress(ImagesToPdfProgress(len(inputs), len(inputs)))
                            return PdfOperationResult(Path(output), len(inputs))

                        def pdf_to_image_output_paths(
                            self,
                            source,
                            selection,
                            image_format,
                            output_directory,
                            *,
                            total_pages=None,
                        ):
                            pages = (1, 2, 4) if selection else tuple(
                                range(1, total_pages + 1)
                            )
                            paths = tuple(
                                Path(output_directory)
                                / f"converter-pagina-{page:03d}.{image_format.lower()}"
                                for page in pages
                            )
                            self.calls.append((
                                "plan-images",
                                Path(source).name,
                                selection,
                                image_format,
                                Path(output_directory).name,
                                total_pages,
                            ))
                            return paths

                        def pdf_to_images(
                            self,
                            source,
                            selection,
                            image_format,
                            output_directory,
                            *,
                            overwrite=False,
                            quality=None,
                            cancel_event=None,
                            progress=None,
                        ):
                            pages = (1, 2, 4) if selection else tuple(range(1, 8))
                            paths = tuple(
                                Path(output_directory)
                                / f"converter-pagina-{page:03d}.{image_format.lower()}"
                                for page in pages
                            )
                            self.calls.append((
                                "pdf-images",
                                Path(source).name,
                                selection,
                                image_format,
                                Path(output_directory).name,
                                overwrite,
                            ))
                            return PdfImageExportResult(
                                Path(output_directory), paths, pages
                            )

                    service = Service()
                    messages = []
                    confirmations = []
                    actions = PdfPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(("warning", message)),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda message: not confirmations.append(
                            message
                        ),
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    page = PdfToolsPage(
                        root,
                        service=service,
                        actions=actions,
                        thread_factory=ImmediateThread,
                    )
                    page.pack()
                    root.update_idletasks()

                    initial = {
                        "placeholder": page.is_placeholder,
                        "tools": list(page.tool_names),
                        "merge_select_text": page.merge_select_button.cget("text"),
                        "extract_select_text": page.extract_select_button.cget("text"),
                        "images_select_text": page.images_select_button.cget("text"),
                        "pdf_images_select_text": page.pdf_images_select_button.cget(
                            "text"
                        ),
                        "merge_disabled": page.merge_run_button.cget("state"),
                        "extract_disabled": page.extract_run_button.cget("state"),
                        "images_disabled": page.images_run_button.cget("state"),
                        "pdf_images_disabled": page.pdf_images_run_button.cget(
                            "state"
                        ),
                        "pdf_images_entry_disabled": page.pdf_images_entry.cget(
                            "state"
                        ),
                        "pdf_images_formats": list(
                            page.pdf_images_format_menu.cget("values")
                        ),
                        "pdf_images_qualities": list(
                            page.pdf_images_quality_menu.cget("values")
                        ),
                        "pdf_images_quality": page._pdf_images_quality.get(),
                        "merge_remove_disabled": page.merge_remove_button.cget("state"),
                        "images_remove_disabled": page.images_remove_button.cget("state"),
                        "images_defaults": {
                            "paper": page._images_paper.get(),
                            "orientation": page._images_orientation.get(),
                            "margin": page._images_margin.get(),
                            "per_page": page._images_per_page.get(),
                        },
                        "images_cancel_disabled": page.images_cancel_button.cget(
                            "state"
                        ),
                        "images_order_width": (
                            page.images_up_button.master.winfo_reqwidth()
                        ),
                        "images_preview_width": (
                            page.images_preview_canvas.master.winfo_reqwidth()
                        ),
                    }

                    with patch(
                        "ui_pages.filedialog.askopenfilenames",
                        return_value=("C:/Temp/primeiro.pdf", "C:/Temp/segundo.pdf"),
                    ):
                        page._select_merge_files()
                    merge_first_selection = [
                        path.name for path in page.merge_files.paths
                    ]
                    with patch(
                        "ui_pages.filedialog.askopenfilenames",
                        return_value=(
                            "c:/temp/PRIMEIRO.pdf",
                            "C:/Outra/terceiro.pdf",
                        ),
                    ):
                        page._select_merge_files()
                    merge_cumulative = [path.name for path in page.merge_files.paths]
                    page.merge_files._selected.set(0)
                    page.merge_files._row_controls[2].master.buttons[-1].invoke()
                    merge_after_move_up = [path.name for path in page.merge_files.paths]
                    page.merge_files._row_controls[1].master.buttons[1].invoke()
                    merge_after_move_down = [path.name for path in page.merge_files.paths]
                    page.merge_files.remove_selected()
                    merge_after_remove = [path.name for path in page.merge_files.paths]
                    merge_enabled = page.merge_run_button.cget("state")
                    with tempfile.TemporaryDirectory() as output_dir:
                        existing_output = Path(output_dir) / "unido.pdf"
                        existing_output.write_text("resultado anterior")
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(existing_output),
                        ):
                            page._start_merge()
                        page._poll_worker()

                    with patch(
                        "ui_pages.filedialog.askopenfilename",
                        return_value="C:/Temp/origem.pdf",
                    ):
                        page._select_extract_source()
                    page._poll_worker()

                    with patch(
                        "ui_pages.filedialog.askopenfilename",
                        return_value="C:/Temp/converter.pdf",
                    ):
                        page._select_pdf_images_source()
                    page._poll_worker()
                    pdf_images_all_scope = page._pdf_images_scope.get()
                    pdf_images_all_hides_range = not page.pdf_images_range.grid_info()
                    page._pdf_images_scope.set("Páginas específicas")
                    pdf_images_specific_shows_range = bool(page.pdf_images_range.grid_info())
                    pdf_images_specific_entry = page.pdf_images_entry.cget("state")
                    page._pdf_images_selection.set("0")
                    pdf_images_invalid = page.pdf_images_run_button.cget("state")
                    page._pdf_images_selection.set("1-2,4")
                    page._pdf_images_format.set("JPG")
                    with tempfile.TemporaryDirectory() as image_output_dir:
                        existing_image = (
                            Path(image_output_dir) / "converter-pagina-001.jpg"
                        )
                        existing_image.write_bytes(b"resultado anterior")
                        with patch(
                            "ui_pages.filedialog.askdirectory",
                            return_value=image_output_dir,
                        ):
                            page._select_pdf_images_destination()
                        pdf_images_enabled = page.pdf_images_run_button.cget("state")
                        page._start_pdf_to_images()
                        page._poll_worker()
                        page.tab_view.set("Juntar PDFs")
                        page.tab_view.set("PDF → Imagens")
                        pdf_images_persistent = {
                            "selection": page._pdf_images_selection.get(),
                            "format": page._pdf_images_format.get(),
                            "quality": page._pdf_images_quality.get(),
                            "destination": page._pdf_images_destination_text.get(),
                        }
                    page._extract_selection.set("0")
                    extract_invalid = page.extract_run_button.cget("state")
                    extract_invalid_text = page._extract_validation_text.get()
                    page._extract_selection.set("1-2")
                    extract_enabled = page.extract_run_button.cget("state")
                    extract_valid_text = page._extract_validation_text.get()
                    extract_summary = page._extract_summary_text.get()
                    with patch(
                        "ui_pages.filedialog.asksaveasfilename",
                        return_value="C:/Temp/extraido.pdf",
                    ):
                        page._start_extract()
                    page._poll_worker()

                    with patch(
                        "ui_pages.filedialog.askopenfilenames",
                        return_value=("C:/Temp/a.png", "C:/Temp/b.jpg"),
                    ):
                        page._select_images()
                    image_first_selection = [
                        path.name for path in page.image_files.paths
                    ]
                    with patch(
                        "ui_pages.filedialog.askopenfilenames",
                        return_value=("c:/temp/A.PNG", "C:/Outra/c.png"),
                    ):
                        page._select_images()
                    image_cumulative = [path.name for path in page.image_files.paths]
                    page.image_files._selected.set(2)
                    page.image_files.move_selected(-1)
                    image_after_move_up = [path.name for path in page.image_files.paths]
                    page.image_files.move_selected(1)
                    image_after_move_down = [path.name for path in page.image_files.paths]
                    page.image_files.remove_selected()
                    image_after_remove = [path.name for path in page.image_files.paths]
                    images_enabled = page.images_run_button.cget("state")
                    with patch(
                        "ui_pages.filedialog.asksaveasfilename",
                        return_value="C:/Temp/imagens.pdf",
                    ):
                        page._start_images()
                    page._poll_worker()

                    def unexpected_failure():
                        raise RuntimeError("DETALHE-INTERNO-NAO-EXIBIR")

                    page._start_worker(
                        unexpected_failure,
                        lambda _value: None,
                        "Testando erro controlado...",
                    )
                    page._poll_worker()

                    result = {
                        "initial": initial,
                        "merge_first_selection": merge_first_selection,
                        "merge_cumulative": merge_cumulative,
                        "merge_after_move_up": merge_after_move_up,
                        "merge_after_move_down": merge_after_move_down,
                        "merge_after_remove": merge_after_remove,
                        "merge_enabled": merge_enabled,
                        "extract_invalid": extract_invalid,
                        "extract_invalid_text": extract_invalid_text,
                        "extract_enabled": extract_enabled,
                        "extract_valid_text": extract_valid_text,
                        "extract_summary": extract_summary,
                        "images_enabled": images_enabled,
                        "pdf_images_all_scope": pdf_images_all_scope,
                        "pdf_images_all_hides_range": pdf_images_all_hides_range,
                        "pdf_images_specific_shows_range": pdf_images_specific_shows_range,
                        "pdf_images_specific_entry": pdf_images_specific_entry,
                        "pdf_images_invalid": pdf_images_invalid,
                        "pdf_images_enabled": pdf_images_enabled,
                        "pdf_images_persistent": pdf_images_persistent,
                        "image_first_selection": image_first_selection,
                        "image_cumulative": image_cumulative,
                        "image_after_move_up": image_after_move_up,
                        "image_after_move_down": image_after_move_down,
                        "image_after_remove": image_after_remove,
                        "source_name": page._extract_source_text.get(),
                        "page_count": page._extract_pages_text.get(),
                        "calls": service.calls,
                        "message_kinds": [kind for kind, _message in messages],
                        "last_message": messages[-1][1],
                        "status_after_error": page._status.get(),
                        "images_terminal_state": page._images_state.value,
                        "confirmations": confirmations,
                        "busy": page.is_busy,
                        "worker_names": worker_names,
                    }
                    page.close()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertFalse(result["initial"]["placeholder"])
        self.assertEqual(
            result["initial"]["tools"],
            [
                "Juntar PDFs",
                "Extrair páginas",
                "Imagens → PDF",
                "PDF → Imagens",
                "Pôster/Painel",
                "PDF para Word",
            ],
        )
        self.assertEqual(result["initial"]["merge_disabled"], "disabled")
        self.assertEqual(result["initial"]["extract_disabled"], "disabled")
        self.assertEqual(result["initial"]["images_disabled"], "disabled")
        self.assertEqual(result["initial"]["pdf_images_disabled"], "disabled")
        self.assertEqual(result["initial"]["pdf_images_entry_disabled"], "disabled")
        self.assertEqual(result["initial"]["pdf_images_formats"], ["PNG", "JPG"])
        self.assertEqual(
            result["initial"]["pdf_images_qualities"],
            ["Padrão", "Alta"],
        )
        self.assertEqual(result["initial"]["pdf_images_quality"], "Padrão")
        self.assertEqual(result["initial"]["merge_select_text"], "Adicionar PDFs")
        self.assertEqual(result["initial"]["extract_select_text"], "Selecionar PDF")
        self.assertEqual(result["initial"]["images_select_text"], "Adicionar imagens")
        self.assertEqual(result["initial"]["pdf_images_select_text"], "Selecionar PDF")
        self.assertEqual(result["initial"]["merge_remove_disabled"], "disabled")
        self.assertEqual(result["initial"]["images_remove_disabled"], "disabled")
        self.assertEqual(
            result["initial"]["images_defaults"],
            {
                "paper": "A4",
                "orientation": "Automática",
                "margin": "Normal",
                "per_page": "1 por página",
            },
        )
        self.assertEqual(result["initial"]["images_cancel_disabled"], "disabled")
        self.assertLessEqual(result["initial"]["images_order_width"], 300)
        self.assertLessEqual(result["initial"]["images_preview_width"], 280)
        self.assertEqual(
            result["merge_first_selection"],
            ["primeiro.pdf", "segundo.pdf"],
        )
        self.assertEqual(
            result["merge_cumulative"],
            ["primeiro.pdf", "segundo.pdf", "terceiro.pdf"],
        )
        self.assertEqual(
            result["merge_after_move_up"],
            ["primeiro.pdf", "terceiro.pdf", "segundo.pdf"],
        )
        self.assertEqual(
            result["merge_after_move_down"],
            ["primeiro.pdf", "segundo.pdf", "terceiro.pdf"],
        )
        self.assertEqual(result["merge_after_remove"], ["primeiro.pdf", "segundo.pdf"])
        self.assertEqual(
            result["image_first_selection"],
            ["a.png", "b.jpg"],
        )
        self.assertEqual(
            result["image_cumulative"],
            ["a.png", "b.jpg", "c.png"],
        )
        self.assertEqual(result["image_after_move_up"], ["a.png", "c.png", "b.jpg"])
        self.assertEqual(result["image_after_move_down"], ["a.png", "b.jpg", "c.png"])
        self.assertEqual(result["image_after_remove"], ["a.png", "b.jpg"])
        self.assertEqual(result["merge_enabled"], "normal")
        self.assertEqual(result["extract_invalid"], "disabled")
        self.assertIn("inválida", result["extract_invalid_text"])
        self.assertEqual(result["extract_enabled"], "normal")
        self.assertEqual(result["extract_valid_text"], "Seleção válida.")
        self.assertIn("Resultado: 2 páginas", result["extract_summary"])
        self.assertEqual(result["images_enabled"], "normal")
        self.assertEqual(result["pdf_images_all_scope"], "Todas as páginas")
        self.assertTrue(result["pdf_images_all_hides_range"])
        self.assertTrue(result["pdf_images_specific_shows_range"])
        self.assertEqual(result["pdf_images_specific_entry"], "normal")
        self.assertEqual(result["pdf_images_invalid"], "disabled")
        self.assertEqual(result["pdf_images_enabled"], "normal")
        self.assertEqual(result["pdf_images_persistent"]["selection"], "1-2,4")
        self.assertEqual(result["pdf_images_persistent"]["format"], "JPG")
        self.assertEqual(result["pdf_images_persistent"]["quality"], "Padrão")
        self.assertTrue(result["pdf_images_persistent"]["destination"])
        self.assertEqual(result["source_name"], "origem.pdf")
        self.assertEqual(result["page_count"], "Quantidade de páginas: 7")
        self.assertEqual(
            [call[0] for call in result["calls"]],
            [
                "merge",
                "count",
                "count",
                "plan-images",
                "pdf-images",
                "extract",
                "images",
            ],
        )
        self.assertEqual(
            result["message_kinds"],
            ["error"],
        )
        self.assertEqual(
            result["last_message"], "Não foi possível concluir a operação PDF."
        )
        self.assertNotIn("DETALHE-INTERNO-NAO-EXIBIR", result["last_message"])
        self.assertEqual(
            result["status_after_error"],
            "Operação PDF não concluída. Confira os arquivos e tente novamente.",
        )
        self.assertEqual(result["images_terminal_state"], "completed")
        self.assertEqual(len(result["confirmations"]), 2)
        self.assertIn("unido.pdf", result["confirmations"][0])
        self.assertIn("1 imagem já existe", result["confirmations"][1])
        self.assertTrue(result["calls"][0][3])
        self.assertTrue(result["calls"][4][5])
        self.assertTrue(result["worker_names"])
        self.assertEqual(set(result["worker_names"]), {"edudownloader-pdf-worker"})
        self.assertFalse(result["busy"])

    def test_public_file_handoffs_prepare_tools_and_reject_busy_state(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import time
                    import tkinter as tk
                    from pathlib import Path

                    import customtkinter as ctk
                    from PIL import Image

                    from ui_pages import PdfPageActions, PdfToolsPage

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    class Service:
                        def __init__(self):
                            self.calls = []

                        def page_count(self, source):
                            self.calls.append(("count", Path(source).name))
                            return 5

                    warnings = []
                    actions = PdfPageActions(
                        show_info=lambda _message: None,
                        show_warning=warnings.append,
                        show_error=lambda _message: None,
                        confirm_overwrite=lambda _message: False,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    service = Service()
                    page = PdfToolsPage(
                        root,
                        service=service,
                        actions=actions,
                        thread_factory=ImmediateThread,
                    )
                    page.pack()
                    root.update_idletasks()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        first_pdf = directory / "primeiro.pdf"
                        second_pdf = directory / "novo arquivo ação.PDF"
                        first_image = directory / "primeira.jpg"
                        second_image = directory / "imagem ação.PNG"
                        wrong_file = directory / "incompatível.txt"
                        pdf_directory = directory / "pasta.pdf"
                        for path in (
                            first_pdf,
                            second_pdf,
                            first_image,
                            second_image,
                            wrong_file,
                        ):
                            path.write_bytes(b"fixture")
                        Image.new("RGB", (320, 180), "navy").save(first_image)
                        Image.new("RGBA", (180, 320), (20, 80, 160, 120)).save(
                            second_image
                        )
                        pdf_directory.mkdir()
                        missing_pdf = directory / "ausente.pdf"

                        invalid_results = {
                            "extract_missing": page.prepare_extract_source(missing_pdf),
                            "extract_wrong": page.prepare_extract_source(wrong_file),
                            "extract_directory": page.prepare_extract_source(
                                pdf_directory
                            ),
                            "pdf_images_missing": (
                                page.prepare_pdf_to_images_source(missing_pdf)
                            ),
                            "pdf_images_wrong": (
                                page.prepare_pdf_to_images_source(wrong_file)
                            ),
                            "pdf_images_directory": (
                                page.prepare_pdf_to_images_source(pdf_directory)
                            ),
                            "image_missing": page.add_image_to_pdf(
                                directory / "ausente.png"
                            ),
                            "image_wrong": page.add_image_to_pdf(wrong_file),
                            "image_directory": page.add_image_to_pdf(pdf_directory),
                            "poster_missing": page.prepare_poster_source(
                                directory / "ausente.png"
                            ),
                            "poster_wrong": page.prepare_poster_source(wrong_file),
                            "poster_directory": page.prepare_poster_source(
                                pdf_directory
                            ),
                        }

                        extract_first = page.prepare_extract_source(first_pdf)
                        busy_snapshot = {
                            "tab": page.tab_view.get(),
                            "source_text": page._extract_source_text.get(),
                            "status": page._status.get(),
                            "images": [path.name for path in page.image_files.paths],
                        }
                        busy_results = {
                            "extract": page.prepare_extract_source(second_pdf),
                            "pdf_images": page.prepare_pdf_to_images_source(second_pdf),
                            "image": page.add_image_to_pdf(first_image),
                            "poster": page.prepare_poster_source(first_image),
                        }
                        busy_unchanged = busy_snapshot == {
                            "tab": page.tab_view.get(),
                            "source_text": page._extract_source_text.get(),
                            "status": page._status.get(),
                            "images": [path.name for path in page.image_files.paths],
                        }
                        page._poll_worker()
                        extract_after_first = {
                            "source": page._extract_source.name,
                            "count": page._extract_page_count,
                        }

                        extract_second = page.prepare_extract_source(second_pdf)
                        extract_second_tab = page.tab_view.get()
                        page._poll_worker()
                        extract_after_second = page._extract_source.name

                        pdf_images_first = page.prepare_pdf_to_images_source(first_pdf)
                        page._poll_worker()
                        page._pdf_images_format.set("JPG")
                        page._pdf_images_scope.set("Páginas específicas")
                        page._pdf_images_selection.set("1-2")
                        page._pdf_images_destination = directory
                        page._pdf_images_destination_text.set(directory.name)
                        pdf_images_second = page.prepare_pdf_to_images_source(
                            second_pdf
                        )
                        pdf_images_prepared = {
                            "tab": page.tab_view.get(),
                            "source_text": page._pdf_images_source_text.get(),
                            "selection": page._pdf_images_selection.get(),
                            "format": page._pdf_images_format.get(),
                            "scope": page._pdf_images_scope.get(),
                            "destination": page._pdf_images_destination.name,
                        }
                        page._poll_worker()
                        pdf_images_after_second = page._pdf_images_source.name

                        image_first = page.add_image_to_pdf(first_image)
                        image_second = page.add_image_to_pdf(second_image)
                        image_duplicate = page.add_image_to_pdf(first_image)
                        image_state = {
                            "tab": page.tab_view.get(),
                            "paths": [path.name for path in page.image_files.paths],
                            "status": page._status.get(),
                        }

                        poster_first = page.prepare_poster_source(first_image)
                        for _ in range(10):
                            root.update()
                            time.sleep(0.03)
                        poster_state = {
                            "tab": page.tab_view.get(),
                            "source": page._poster_source.name,
                            "source_text": page._poster_source_text.get(),
                            "run": page.poster_run_button.cget("state"),
                        }

                    result = {
                        "invalid_results": invalid_results,
                        "extract_first": extract_first,
                        "busy_results": busy_results,
                        "busy_unchanged": busy_unchanged,
                        "extract_after_first": extract_after_first,
                        "extract_second": extract_second,
                        "extract_second_tab": extract_second_tab,
                        "extract_after_second": extract_after_second,
                        "pdf_images_first": pdf_images_first,
                        "pdf_images_second": pdf_images_second,
                        "pdf_images_prepared": pdf_images_prepared,
                        "pdf_images_after_second": pdf_images_after_second,
                        "image_results": [
                            image_first,
                            image_second,
                            image_duplicate,
                        ],
                        "image_state": image_state,
                        "poster_first": poster_first,
                        "poster_state": poster_state,
                        "calls": service.calls,
                        "warnings": warnings,
                        "busy": page.is_busy,
                    }
                    page.close()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertFalse(any(result["invalid_results"].values()))
        self.assertTrue(result["extract_first"])
        self.assertFalse(any(result["busy_results"].values()))
        self.assertTrue(result["busy_unchanged"])
        self.assertEqual(
            result["extract_after_first"], {"source": "primeiro.pdf", "count": 5}
        )
        self.assertTrue(result["extract_second"])
        self.assertEqual(result["extract_second_tab"], "Extrair páginas")
        self.assertEqual(result["extract_after_second"], "novo arquivo ação.PDF")
        self.assertTrue(result["pdf_images_first"])
        self.assertTrue(result["pdf_images_second"])
        self.assertEqual(result["pdf_images_prepared"]["tab"], "PDF → Imagens")
        self.assertEqual(
            result["pdf_images_prepared"]["source_text"], "novo arquivo ação.PDF"
        )
        self.assertEqual(result["pdf_images_prepared"]["selection"], "")
        self.assertEqual(result["pdf_images_prepared"]["format"], "JPG")
        self.assertEqual(result["pdf_images_prepared"]["scope"], "Páginas específicas")
        self.assertTrue(result["pdf_images_prepared"]["destination"])
        self.assertEqual(result["pdf_images_after_second"], "novo arquivo ação.PDF")
        self.assertEqual(result["image_results"], [True, True, True])
        self.assertEqual(result["image_state"]["tab"], "Imagens → PDF")
        self.assertEqual(
            result["image_state"]["paths"], ["primeira.jpg", "imagem ação.PNG"]
        )
        self.assertIn("já está", result["image_state"]["status"])
        self.assertTrue(result["poster_first"])
        self.assertEqual(
            result["poster_state"],
            {
                "tab": "Pôster/Painel",
                "source": "primeira.jpg",
                "source_text": "primeira.jpg",
                "run": "normal",
            },
        )
        self.assertEqual(
            [call[0] for call in result["calls"]],
            ["count", "count", "count", "count"],
        )
        self.assertFalse(result["busy"])
        self.assertGreaterEqual(len(result["warnings"]), 12)

    def test_images_layout_controls_debounce_stale_preview_and_handoff(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import time
                    import tkinter as tk
                    from pathlib import Path

                    import customtkinter as ctk
                    from PIL import Image

                    from ui_pages import PdfPageActions, PdfToolsPage

                    import threading
                    from pdf_previews import PageRenderer
                    from ui_pages import _build_images_pdf_preview

                    class ControlledRenderer(PageRenderer):
                        def __init__(self):
                            super().__init__()
                            self.calls = []
                            self.started = threading.Event()
                            self.release = threading.Event()
                        def bundle(self, *args):
                            self.calls.append(args)
                            if len(self.calls) == 1:
                                self.started.set()
                                assert self.release.wait(5)
                            return super().bundle(*args)

                    class Service:
                        calls = []

                    def pump(root, seconds):
                        deadline = time.monotonic() + seconds
                        while time.monotonic() < deadline:
                            root.update()
                            time.sleep(0.01)

                    actions = PdfPageActions(
                        show_info=lambda _message: None,
                        show_warning=lambda _message: None,
                        show_error=lambda _message: None,
                        confirm_overwrite=lambda _message: False,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    page = PdfToolsPage(
                        root,
                        service=Service(),
                        actions=actions,
                    )
                    page.pack(fill="both", expand=True)
                    root.update_idletasks()
                    renderer = ControlledRenderer()
                    page._page_preview_worker.renderer = renderer
                    initial = {
                        "paper": page._images_paper.get(),
                        "orientation": page._images_orientation.get(),
                        "margin": page._images_margin.get(),
                        "per_page": page._images_per_page.get(),
                        "run": page.images_run_button.cget("state"),
                        "summary": page._images_summary.get(),
                        "empty": [
                            page.images_preview_canvas.itemcget(item, "text")
                            for item in page.images_preview_canvas.find_all()
                            if page.images_preview_canvas.type(item) == "text"
                        ],
                    }

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        paths = []
                        for index, size in enumerate(
                            ((80, 160), (180, 90), (100, 100), (70, 150), (200, 80)),
                            start=1,
                        ):
                            path = directory / f"imagem {index} ação.png"
                            Image.new("RGB", size, (20 * index, 90, 150)).save(path)
                            paths.append(path)
                            assert page.add_image_to_pdf(path)

                        pump(root, 0.18)
                        assert renderer.started.wait(2)
                        first_thread_count = len(renderer.calls)
                        thread = page._page_preview_worker.thread
                        page._images_paper.set("Carta")
                        page._on_images_layout_changed()
                        page._images_orientation.set("Paisagem")
                        page._on_images_layout_changed()
                        page._images_margin.set("Sem margem")
                        page._on_images_layout_changed()
                        page._images_per_page.set("4 por página")
                        page._on_images_layout_changed()
                        page.image_files._selected.set(4)
                        page.image_files.move_selected(-1)
                        pump(root, 0.18)

                        pane = page.images_page_preview
                        stale_discarded = pane._bundle is None
                        assert len(page._page_preview_worker.pending) == 1
                        renderer.release.set()
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            pump(root, 0.01)
                            if pane._bundle and pane._photo and pane._poll_id is None:
                                break
                        assert pane._bundle and pane._photo
                        second_thread_count = len(renderer.calls)
                        preview = _build_images_pdf_preview(
                            page.image_files.paths, page._current_images_layout()
                        )
                        final = {
                            "tab": page.tab_view.get(),
                            "paper": page._images_paper.get(),
                            "orientation": page._images_orientation.get(),
                            "margin": page._images_margin.get(),
                            "per_page": page._images_per_page.get(),
                            "margin_help": page._images_margin_help.get(),
                            "summary": page._images_summary.get(),
                            "paths": [path.name for path in page.image_files.paths],
                            "run": page.images_run_button.cget("state"),
                            "preview_orientation": preview.orientation.value,
                            "preview_pages": preview.total_pages,
                            "page_size": [preview.page_size.width, preview.page_size.height],
                            "placements": len(preview.placements),
                            "failed": list(preview.failed_items),
                            "actual_pages": pane.total,
                            "actual_pixels": bool(pane._bundle.main.rgb),
                            "same_worker": thread is page._page_preview_worker.thread,
                        }
                        ctk.set_appearance_mode("dark")
                        pump(root, 0.04)
                        final["dark_background"] = page.images_preview_canvas.cget("bg")
                        ctk.set_appearance_mode("light")
                        pump(root, 0.04)
                        final["light_background"] = page.images_preview_canvas.cget("bg")

                    result = {
                        "initial": initial,
                        "first_thread_count": first_thread_count,
                        "second_thread_count": second_thread_count,
                        "stale_discarded": stale_discarded,
                        "worker_names": [page._page_preview_worker.thread.name],
                        "final": final,
                    }
                    page.close()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(
            result["initial"],
            {
                "paper": "A4",
                "orientation": "Automática",
                "margin": "Normal",
                "per_page": "1 por página",
                "run": "disabled",
                "summary": "Nenhuma página será gerada.",
                "empty": ["Adicione imagens para visualizar o resultado."],
            },
        )
        self.assertEqual(result["first_thread_count"], 1)
        self.assertEqual(result["second_thread_count"], 2)
        self.assertTrue(result["stale_discarded"])
        self.assertEqual(set(result["worker_names"]), {"edudownloader-pdf-preview"})
        final = result["final"]
        self.assertEqual(final["tab"], "Imagens → PDF")
        self.assertEqual(final["paper"], "Carta")
        self.assertEqual(final["orientation"], "Paisagem")
        self.assertEqual(final["margin"], "Sem margem")
        self.assertEqual(final["per_page"], "4 por página")
        self.assertEqual(
            final["margin_help"], "Algumas impressoras podem cortar as bordas."
        )
        self.assertEqual(final["summary"], "2 páginas serão geradas.")
        self.assertEqual(final["run"], "normal")
        self.assertEqual(final["preview_orientation"], "landscape")
        self.assertEqual(final["preview_pages"], 2)
        self.assertEqual(final["actual_pages"], 2)
        self.assertTrue(final["actual_pixels"])
        self.assertTrue(final["same_worker"])
        self.assertGreater(final["page_size"][0], final["page_size"][1])
        self.assertEqual(final["placements"], 4)
        self.assertEqual(final["failed"], [False, False, False, False])
        self.assertEqual(final["dark_background"], "#24394D")
        self.assertEqual(final["light_background"], "#EBF3FA")
        self.assertEqual(
            final["paths"],
            [
                "imagem 1 ação.png",
                "imagem 2 ação.png",
                "imagem 3 ação.png",
                "imagem 5 ação.png",
                "imagem 4 ação.png",
            ],
        )

    def test_images_progress_cancel_responsiveness_and_cancel_wins_late_result(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import threading
                    import time
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk
                    from PIL import Image

                    from pdf_tools import (
                        ImagesToPdfProgress,
                        PdfOperationCancelled,
                        PdfOperationResult,
                        PdfToolsError,
                    )
                    from ui_pages import PdfPageActions, PdfToolsPage

                    class Service:
                        def __init__(self):
                            self.calls = []
                            self.started = threading.Event()
                            self.release = threading.Event()
                            self.ignore_cancel = False
                            self.fail = False

                        def images_to_pdf(
                            self,
                            inputs,
                            output,
                            *,
                            overwrite=False,
                            layout=None,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append({
                                "paper": layout.paper.name,
                                "orientation": layout.orientation.value,
                                "margin": layout.margin.name,
                                "per_page": layout.images_per_page,
                            })
                            progress(ImagesToPdfProgress(0, 2))
                            progress(ImagesToPdfProgress(1, 2))
                            self.started.set()
                            self.release.wait(3)
                            if cancel_event.is_set() and not self.ignore_cancel:
                                raise PdfOperationCancelled("cancelado")
                            if self.fail:
                                raise PdfToolsError("Falha pública controlada.")
                            return PdfOperationResult(Path(output), 2)

                    def pump(root, predicate, timeout=3):
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline and not predicate():
                            root.update()
                            time.sleep(0.01)
                        root.update()
                        return predicate()

                    messages = []
                    actions = PdfPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(("warning", message)),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda _message: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    service = Service()
                    page = PdfToolsPage(root, service=service, actions=actions)
                    page.pack()
                    root.update_idletasks()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        image = directory / "entrada ação.png"
                        Image.new("RGB", (100, 180), (30, 80, 130)).save(image)
                        page.add_image_to_pdf(image)
                        page._images_paper.set("Carta")
                        page._images_orientation.set("Retrato")
                        page._images_margin.set("Pequena")
                        page._images_per_page.set("2 por página")
                        page._on_images_layout_changed()

                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(directory / "primeiro.pdf"),
                        ):
                            page._start_images()
                        assert pump(root, service.started.is_set)
                        assert pump(root, lambda: "1 de 2" in page._images_progress_text.get())
                        responsive = {"value": False}
                        root.after(0, lambda: responsive.__setitem__("value", True))
                        assert pump(root, lambda: responsive["value"])
                        processing = {
                            "state": page._images_state.value,
                            "run": page.images_run_button.cget("state"),
                            "cancel": page.images_cancel_button.cget("state"),
                            "paper": page.images_paper_menu.cget("state"),
                            "progress": page.progress_bar.get(),
                            "text": page._images_progress_text.get(),
                        }
                        started_cancel = time.monotonic()
                        page._cancel_images()
                        cancel_elapsed = time.monotonic() - started_cancel
                        cancelling = {
                            "state": page._images_state.value,
                            "status": page._status.get(),
                            "cancel": page.images_cancel_button.cget("state"),
                        }
                        service.release.set()
                        assert pump(root, lambda: not page.is_busy)
                        cancelled = {
                            "state": page._images_state.value,
                            "status": page._status.get(),
                            "run": page.images_run_button.cget("state"),
                            "cancel": page.images_cancel_button.cget("state"),
                        }

                        service.started.clear()
                        service.release.clear()
                        service.ignore_cancel = True
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(directory / "segundo.pdf"),
                        ):
                            page._start_images()
                        assert pump(root, service.started.is_set)
                        page._cancel_images()
                        service.release.set()
                        assert pump(root, lambda: not page.is_busy)
                        late_result = {
                            "state": page._images_state.value,
                            "status": page._status.get(),
                            "messages": list(messages),
                        }

                        service.started.clear()
                        service.release.clear()
                        service.ignore_cancel = False
                        service.fail = True
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(directory / "erro.pdf"),
                        ):
                            page._start_images()
                        assert pump(root, service.started.is_set)
                        service.release.set()
                        assert pump(root, lambda: not page.is_busy)
                        error_result = {
                            "state": page._images_state.value,
                            "status": page._status.get(),
                            "run": page.images_run_button.cget("state"),
                            "last_message": messages[-1],
                        }

                        service.started.clear()
                        service.release.clear()
                        service.fail = False
                        service.ignore_cancel = True
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(directory / "terceiro.pdf"),
                        ):
                            page._start_images()
                        assert pump(root, service.started.is_set)
                        messages_before_close = list(messages)
                        page.close()
                        service.release.set()
                        time.sleep(0.08)
                        root.update()
                        close_safe = messages == messages_before_close

                    result = {
                        "processing": processing,
                        "responsive": responsive["value"],
                        "cancel_elapsed": cancel_elapsed,
                        "cancelling": cancelling,
                        "cancelled": cancelled,
                        "late_result": late_result,
                        "error_result": error_result,
                        "calls": service.calls,
                        "close_safe": close_safe,
                    }
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(result["processing"]["state"], "processing")
        self.assertEqual(result["processing"]["run"], "disabled")
        self.assertEqual(result["processing"]["cancel"], "normal")
        self.assertEqual(result["processing"]["paper"], "disabled")
        self.assertAlmostEqual(result["processing"]["progress"], 0.5, places=2)
        self.assertIn("1 de 2", result["processing"]["text"])
        self.assertTrue(result["responsive"])
        self.assertLess(result["cancel_elapsed"], 0.2)
        self.assertEqual(result["cancelling"]["state"], "cancelling")
        self.assertEqual(result["cancelling"]["status"], "Cancelando...")
        self.assertEqual(result["cancelling"]["cancel"], "disabled")
        self.assertEqual(result["cancelled"]["state"], "cancelled")
        self.assertEqual(result["cancelled"]["status"], "Criação do PDF cancelada.")
        self.assertEqual(result["cancelled"]["run"], "normal")
        self.assertEqual(result["cancelled"]["cancel"], "disabled")
        self.assertEqual(result["late_result"]["state"], "cancelled")
        self.assertEqual(result["late_result"]["status"], "Criação do PDF cancelada.")
        self.assertFalse(
            any(kind == "info" for kind, _message in result["late_result"]["messages"])
        )
        self.assertEqual(result["error_result"]["state"], "error")
        self.assertEqual(
            result["error_result"]["status"],
            "Operação PDF não concluída. Confira os arquivos e tente novamente.",
        )
        self.assertEqual(result["error_result"]["run"], "normal")
        self.assertEqual(
            result["error_result"]["last_message"],
            ["error", "Falha pública controlada."],
        )
        self.assertEqual(
            result["calls"][0],
            {
                "paper": "LETTER",
                "orientation": "portrait",
                "margin": "SMALL",
                "per_page": 2,
            },
        )
        self.assertTrue(result["close_safe"])

    def test_worker_start_failure_restores_all_pdf_flows_and_allows_retry(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import Mock, patch

                    import customtkinter as ctk

                    from pdf_tools import PdfImageExportResult, PdfOperationResult
                    from ui_pages import PdfPageActions, PdfToolsPage

                    class ControlledThread:
                        fail_next = False

                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            if type(self).fail_next:
                                type(self).fail_next = False
                                raise RuntimeError(
                                    "detalhe interno C:/Usuário/privado.pdf"
                                )
                            self.target()

                    class Service:
                        def __init__(self):
                            self.calls = []

                        def page_count(self, source):
                            self.calls.append(("count", Path(source).name))
                            return 4

                        def merge_pdfs(
                            self,
                            inputs,
                            output,
                            *,
                            overwrite=False,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append(("merge", Path(output).name))
                            return PdfOperationResult(Path(output), len(inputs))

                        def extract_pages(
                            self,
                            source,
                            selection,
                            output,
                            *,
                            overwrite=False,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append(("extract", Path(output).name))
                            return PdfOperationResult(Path(output), 2)

                        def images_to_pdf(
                            self,
                            inputs,
                            output,
                            *,
                            overwrite=False,
                            layout=None,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append(("images", Path(output).name))
                            return PdfOperationResult(Path(output), len(inputs))

                        def pdf_to_image_output_paths(
                            self,
                            source,
                            selection,
                            image_format,
                            output_directory,
                            *,
                            total_pages=None,
                        ):
                            self.calls.append(("plan", Path(source).name))
                            return (Path(output_directory) / "pagina-001.png",)

                        def pdf_to_images(
                            self,
                            source,
                            selection,
                            image_format,
                            output_directory,
                            *,
                            overwrite=False,
                            quality=None,
                            cancel_event=None,
                            progress=None,
                        ):
                            self.calls.append(("pdf-images", Path(source).name))
                            path = Path(output_directory) / "pagina-001.png"
                            return PdfImageExportResult(
                                Path(output_directory), (path,), (1,)
                            )

                    messages = []
                    actions = PdfPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(
                            ("warning", message)
                        ),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda _message: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    service = Service()
                    page = PdfToolsPage(
                        root,
                        service=service,
                        actions=actions,
                        thread_factory=ControlledThread,
                    )
                    page.pack()
                    root.update_idletasks()
                    after_calls = []
                    page.after = lambda delay, callback: after_calls.append(
                        (delay, callback.__name__)
                    )
                    page.progress_bar.start = Mock(wraps=page.progress_bar.start)
                    page.progress_bar.stop = Mock(wraps=page.progress_bar.stop)

                    def exercise(label, start, button, selection):
                        calls_before = sum(
                            call[0] == label for call in service.calls
                        )
                        after_before = len(after_calls)
                        errors_before = len(
                            [kind for kind, _message in messages if kind == "error"]
                        )
                        ControlledThread.fail_next = True
                        start()
                        failure = {
                            "busy": page.is_busy,
                            "button": button.cget("state"),
                            "selection": selection(),
                            "progress": page.progress_bar.get(),
                            "queue_empty": page._results.empty(),
                            "polls": len(after_calls) - after_before,
                            "calls": sum(
                                call[0] == label for call in service.calls
                            ) - calls_before,
                            "status": page._status.get(),
                            "new_errors": len(
                                [
                                    kind
                                    for kind, _message in messages
                                    if kind == "error"
                                ]
                            ) - errors_before,
                        }
                        start()
                        busy_on_retry = page.is_busy
                        polls_on_retry = len(after_calls) - after_before
                        page._poll_worker()
                        return {
                            "failure": failure,
                            "busy_on_retry": busy_on_retry,
                            "busy_after_retry": page.is_busy,
                            "polls_on_retry": polls_on_retry,
                            "calls_after_retry": sum(
                                call[0] == label for call in service.calls
                            ) - calls_before,
                        }

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        save_dialog = lambda **kwargs: str(
                            directory / kwargs["initialfile"]
                        )

                        extract_source = directory / "fonte ação.pdf"
                        pdf_images_source = directory / "imagens ação.pdf"

                        ControlledThread.fail_next = True
                        page._prepare_extract_source(extract_source)
                        extract_inspection_failure = {
                            "busy": page.is_busy,
                            "source_text": page._extract_source_text.get(),
                            "source": page._extract_source.name,
                            "select_button": page.extract_select_button.cget("state"),
                            "queue_empty": page._results.empty(),
                            "polls": len(after_calls),
                            "count_calls": sum(
                                call[0] == "count" for call in service.calls
                            ),
                        }
                        page._prepare_extract_source(extract_source)
                        page._poll_worker()
                        extract_inspection_retry = {
                            "source": page._extract_source.name,
                            "count": page._extract_page_count,
                            "busy": page.is_busy,
                        }

                        polls_before_pdf_images = len(after_calls)
                        count_before_pdf_images = sum(
                            call[0] == "count" for call in service.calls
                        )
                        ControlledThread.fail_next = True
                        page._prepare_pdf_images_source(pdf_images_source)
                        pdf_images_inspection_failure = {
                            "busy": page.is_busy,
                            "source_text": page._pdf_images_source_text.get(),
                            "source": page._pdf_images_source.name,
                            "select_button": page.pdf_images_select_button.cget(
                                "state"
                            ),
                            "queue_empty": page._results.empty(),
                            "polls": len(after_calls) - polls_before_pdf_images,
                            "count_calls": sum(
                                call[0] == "count" for call in service.calls
                            ) - count_before_pdf_images,
                        }
                        page._prepare_pdf_images_source(pdf_images_source)
                        page._poll_worker()
                        pdf_images_inspection_retry = {
                            "source": page._pdf_images_source.name,
                            "count": page._pdf_images_page_count,
                            "busy": page.is_busy,
                        }

                        page.merge_files.add_paths(
                            [directory / "a.pdf", directory / "b.pdf"]
                        )
                        page.image_files.add_paths(
                            [directory / "a.png", directory / "b.jpg"]
                        )
                        page._extract_selection.set("1-2")
                        page._pdf_images_destination = directory
                        page._pdf_images_destination_text.set(directory.name)
                        page._refresh_controls()

                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            side_effect=save_dialog,
                        ):
                            merge = exercise(
                                "merge",
                                page._start_merge,
                                page.merge_run_button,
                                lambda: [path.name for path in page.merge_files.paths],
                            )
                            extract = exercise(
                                "extract",
                                page._start_extract,
                                page.extract_run_button,
                                lambda: page._extract_source.name,
                            )
                            images = exercise(
                                "images",
                                page._start_images,
                                page.images_run_button,
                                lambda: [path.name for path in page.image_files.paths],
                            )
                        pdf_images = exercise(
                            "pdf-images",
                            page._start_pdf_to_images,
                            page.pdf_images_run_button,
                            lambda: page._pdf_images_source.name,
                        )

                        outputs = [
                            path.name for path in directory.iterdir() if path.is_file()
                        ]

                    result = {
                        "extract_inspection_failure": extract_inspection_failure,
                        "extract_inspection_retry": extract_inspection_retry,
                        "pdf_images_inspection_failure": (
                            pdf_images_inspection_failure
                        ),
                        "pdf_images_inspection_retry": pdf_images_inspection_retry,
                        "operations": [merge, extract, images, pdf_images],
                        "outputs": outputs,
                        "errors": [
                            message for kind, message in messages if kind == "error"
                        ],
                        "progress_starts": page.progress_bar.start.call_count,
                        "progress_stops": page.progress_bar.stop.call_count,
                        "closed_before": page._closed,
                    }
                    page.close()
                    result["closed_after"] = page._closed
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        for key, expected_source in (
            ("extract_inspection_failure", "fonte ação.pdf"),
            ("pdf_images_inspection_failure", "imagens ação.pdf"),
        ):
            failure = result[key]
            self.assertFalse(failure["busy"])
            self.assertEqual(failure["source_text"], expected_source)
            self.assertEqual(failure["source"], expected_source)
            self.assertEqual(failure["select_button"], "normal")
            self.assertTrue(failure["queue_empty"])
            self.assertEqual(failure["polls"], 0)
            self.assertEqual(failure["count_calls"], 0)
        self.assertEqual(
            result["extract_inspection_retry"],
            {"source": "fonte ação.pdf", "count": 4, "busy": False},
        )
        self.assertEqual(
            result["pdf_images_inspection_retry"],
            {"source": "imagens ação.pdf", "count": 4, "busy": False},
        )
        for operation in result["operations"]:
            failure = operation["failure"]
            self.assertFalse(failure["busy"])
            self.assertEqual(failure["button"], "normal")
            self.assertEqual(failure["progress"], 0)
            self.assertTrue(failure["queue_empty"])
            self.assertEqual(failure["polls"], 0)
            self.assertEqual(failure["calls"], 0)
            self.assertEqual(failure["new_errors"], 1)
            self.assertEqual(
                failure["status"],
                "Não foi possível iniciar a operação. Tente novamente.",
            )
            self.assertTrue(operation["busy_on_retry"])
            self.assertFalse(operation["busy_after_retry"])
            self.assertEqual(operation["polls_on_retry"], 1)
            self.assertEqual(operation["calls_after_retry"], 1)
        self.assertEqual(result["outputs"], [])
        self.assertEqual(len(result["errors"]), 6)
        self.assertTrue(
            all(
                message == "Não foi possível iniciar a operação. Tente novamente."
                for message in result["errors"]
            )
        )
        self.assertGreaterEqual(result["progress_stops"], result["progress_starts"])
        self.assertFalse(result["closed_before"])
        self.assertTrue(result["closed_after"])

    def test_shutdown_waits_for_pdf_workers_without_cancelling_or_showing_modals(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path

                    import customtkinter as ctk

                    from pdf_tools import PdfToolsError
                    from ui_pages import PdfPageActions, PdfToolsPage

                    class DeferredThread:
                        def __init__(self, *, target, name, daemon):
                            self.target = target
                            self.name = name
                            self.daemon = daemon
                            self.started = False

                        def start(self):
                            self.started = True

                    class DeferredFactory:
                        def __init__(self):
                            self.threads = []

                        def __call__(self, **kwargs):
                            thread = DeferredThread(**kwargs)
                            self.threads.append(thread)
                            return thread

                    class Service:
                        def page_count(self, _source):
                            return 4

                    def make_page(root, messages):
                        factory = DeferredFactory()
                        polls = []
                        page = PdfToolsPage(
                            root,
                            service=Service(),
                            actions=PdfPageActions(
                                show_info=lambda message: messages.append(
                                    ("info", message)
                                ),
                                show_warning=lambda message: messages.append(
                                    ("warning", message)
                                ),
                                show_error=lambda message: messages.append(
                                    ("error", message)
                                ),
                                confirm_overwrite=lambda _message: True,
                            ),
                            thread_factory=factory,
                        )
                        page.pack()
                        root.update_idletasks()
                        page.after = lambda delay, callback: polls.append(
                            (delay, callback.__name__)
                        )
                        return page, factory, polls

                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    messages = []

                    idle, idle_factory, _idle_polls = make_page(root, messages)
                    idle.begin_shutdown()
                    idle_snapshot = {
                        "ready": idle.is_shutdown_ready,
                        "button": idle.merge_select_button.cget("state"),
                    }
                    idle._start_worker(lambda: 1, lambda _value: None, "ignorado")
                    idle_snapshot["threads"] = len(idle_factory.threads)
                    idle.cancel_shutdown()
                    idle_snapshot["restored_button"] = (
                        idle.merge_select_button.cget("state")
                    )

                    success_callbacks = []
                    success, success_factory, success_polls = make_page(
                        root, messages
                    )
                    success._start_worker(
                        lambda: "resultado",
                        success_callbacks.append,
                        "Executando PDF...",
                    )
                    success.begin_shutdown()
                    success_before = {
                        "busy": success.is_busy,
                        "ready": success.is_shutdown_ready,
                        "button": success.merge_select_button.cget("state"),
                        "thread_has_kill": hasattr(success_factory.threads[0], "kill"),
                    }
                    success._poll_worker()
                    success_before["polls_before_result"] = len(success_polls)
                    success_factory.threads[0].target()
                    success._poll_worker()
                    success_after = {
                        "busy": success.is_busy,
                        "ready": success.is_shutdown_ready,
                        "callbacks": success_callbacks,
                        "status": success._status.get(),
                    }

                    def fail_pdf():
                        raise PdfToolsError("falha PDF sintética")

                    failure, failure_factory, _failure_polls = make_page(
                        root, messages
                    )
                    failure._start_worker(fail_pdf, lambda _value: None, "Executando")
                    failure.begin_shutdown()
                    failure_factory.threads[0].target()
                    failure._poll_worker()
                    failure_after = {
                        "busy": failure.is_busy,
                        "ready": failure.is_shutdown_ready,
                        "status": failure._status.get(),
                    }

                    preparation, preparation_factory, _preparation_polls = make_page(
                        root, messages
                    )
                    with tempfile.TemporaryDirectory() as temporary_dir:
                        source = Path(temporary_dir) / "apostila ação.pdf"
                        source.write_bytes(b"synthetic-pdf-fixture")
                        accepted = preparation.prepare_extract_source(source)
                        preparation.begin_shutdown()
                        preparation_before = {
                            "accepted": accepted,
                            "busy": preparation.is_busy,
                            "ready": preparation.is_shutdown_ready,
                        }
                        preparation_factory.threads[0].target()
                        preparation._poll_worker()
                        preparation_after = {
                            "busy": preparation.is_busy,
                            "ready": preparation.is_shutdown_ready,
                            "page_count": preparation._extract_page_count,
                        }

                    result = {
                        "idle": idle_snapshot,
                        "success_before": success_before,
                        "success_after": success_after,
                        "failure_after": failure_after,
                        "preparation_before": preparation_before,
                        "preparation_after": preparation_after,
                        "messages": messages,
                    }
                    for page in (idle, success, failure, preparation):
                        page.close()
                    root.destroy()
                    print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(
            result["idle"],
            {
                "ready": True,
                "button": "disabled",
                "threads": 0,
                "restored_button": "normal",
            },
        )
        self.assertEqual(
            result["success_before"],
            {
                "busy": True,
                "ready": False,
                "button": "disabled",
                "thread_has_kill": False,
                "polls_before_result": 2,
            },
        )
        self.assertEqual(result["success_after"]["callbacks"], [])
        self.assertFalse(result["success_after"]["busy"])
        self.assertTrue(result["success_after"]["ready"])
        self.assertIn("segurança", result["success_after"]["status"])
        self.assertFalse(result["failure_after"]["busy"])
        self.assertTrue(result["failure_after"]["ready"])
        self.assertIn("não concluída", result["failure_after"]["status"])
        self.assertEqual(
            result["preparation_before"],
            {"accepted": True, "busy": True, "ready": False},
        )
        self.assertEqual(
            result["preparation_after"],
            {"busy": False, "ready": True, "page_count": None},
        )
        self.assertEqual(result["messages"], [])


if __name__ == "__main__":
    unittest.main()
