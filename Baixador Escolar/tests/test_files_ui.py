"""Testes reais de Tk para o hub local Arquivos."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class FavoriteFolderPresentationTests(unittest.TestCase):
    def test_labels_preserve_order_disambiguate_and_hide_absolute_paths(self) -> None:
        from ui_pages import _favorite_folder_choices

        folders = (
            r"C:\Escola A\Material",
            r"D:\Escola B\Material",
            r"E:\João Educação\Ação",
        )

        choices = _favorite_folder_choices(folders)

        self.assertEqual(
            choices,
            (
                ("Material — Escola A", folders[0]),
                ("Material — Escola B", folders[1]),
                ("Ação", folders[2]),
            ),
        )
        self.assertFalse(any(folder == label for label, folder in choices))


class FilesPageRealTkTests(unittest.TestCase):
    def test_worker_filters_selection_actions_routes_and_theme(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import threading
                    import tkinter as tk
                    import unicodedata
                    from pathlib import Path
                    from tkinter import ttk
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from local_files import (
                        LocalFileCategory,
                        LocalFileEntry,
                        LocalFilesError,
                    )
                    from ui_pages import FilesPage, FilesPageActions

                    main_thread = threading.get_ident()
                    worker_threads = []
                    worker_names = []
                    scan_calls = []
                    opened = []
                    revealed = []
                    revalidated = []
                    routed = []
                    warnings = []
                    errors = []

                    class JoinedThread:
                        def __init__(self, *, target, name, daemon):
                            self.target = target
                            self.name = name
                            self.daemon = daemon
                            worker_names.append(name)

                        def start(self):
                            def run():
                                worker_threads.append(threading.get_ident())
                                self.target()

                            thread = threading.Thread(
                                target=run,
                                name=self.name,
                                daemon=self.daemon,
                            )
                            thread.start()
                            thread.join()

                    ctk.set_appearance_mode("Dark")
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir) / "Aulas com espaço ação"
                        directory.mkdir()
                        entries = (
                            LocalFileEntry(
                                directory / "prova2.pdf",
                                LocalFileCategory.PDF,
                                2048,
                                1_700_000_000.0,
                            ),
                            LocalFileEntry(
                                directory / "prova10.pdf",
                                LocalFileCategory.PDF,
                                4096,
                                1_700_000_100.0,
                            ),
                            LocalFileEntry(
                                directory / "foto ação.PNG",
                                LocalFileCategory.IMAGE,
                                1_572_864,
                                1_700_000_200.0,
                            ),
                            LocalFileEntry(
                                directory / "aula.mp4",
                                LocalFileCategory.VIDEO,
                                8_388_608,
                                1_700_000_300.0,
                            ),
                            LocalFileEntry(
                                directory / "trilha.mp3",
                                LocalFileCategory.AUDIO,
                                512_000,
                                1_700_000_400.0,
                            ),
                        )

                        def list_files(selected):
                            scan_calls.append((Path(selected).name, threading.get_ident()))
                            return entries

                        def open_file(entry, selected):
                            opened.append((entry.name, Path(selected).name))
                            return entry.path

                        def reveal_file(entry, selected):
                            revealed.append((entry.name, Path(selected).name))
                            return entry.path

                        def revalidate(entry, selected):
                            revalidated.append((entry.name, Path(selected).name))
                            return entry

                        def route(kind):
                            def callback(path):
                                routed.append((kind, Path(path).name))
                                return True

                            return callback

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=warnings.append,
                                show_error=errors.append,
                                extract_pages=route("extract"),
                                pdf_to_images=route("pdf-images"),
                                image_to_pdf=route("image-pdf"),
                                video_to_mp3=route("video-mp3"),
                                create_poster=route("poster"),
                            ),
                            thread_factory=JoinedThread,
                            list_files=list_files,
                            open_file=open_file,
                            reveal_file=reveal_file,
                            revalidate_file=revalidate,
                        )
                        page.pack(fill="both", expand=True)
                        root.update_idletasks()
                        initial = {
                            "placeholder": page.is_placeholder,
                            "choose": page.choose_button.cget("text"),
                            "refresh": page.refresh_button.cget("text"),
                            "refresh_state": page.refresh_button.cget("state"),
                            "filters": list(page.filter_control.cget("values")),
                            "sorts": list(page.sort_menu.cget("values")),
                            "sort": page._sort_name.get(),
                            "count": page._visible_count_text.get(),
                            "columns": list(page.file_tree.cget("columns")),
                            "tree_children": len(page.file_tree.winfo_children()),
                            "folder": page._folder_text.get(),
                            "status": page._status.get(),
                            "detail_heading": page._detail_heading.get(),
                            "remove_favorite": page.remove_favorite_button.cget("text"),
                            "double_click_bound": bool(
                                page.file_tree.bind("<Double-1>")
                            ),
                            "video_action": page.video_mp3_button.cget("text"),
                            "heading_background": ttk.Style(page).lookup(
                                page._HEADING_STYLE, "background"
                            ),
                        }

                        with patch(
                            "ui_pages.filedialog.askdirectory",
                            return_value=str(directory),
                        ):
                            page._choose_directory()
                        loading_before_poll = page.is_loading
                        tree_before_poll = len(page.file_tree.get_children())
                        second_scan = page._start_scan(
                            directory, replace_directory=False
                        )
                        page._poll_scan()
                        loaded_status = page._status.get()
                        loaded_names = [
                            page.file_tree.item(item, "values")[0]
                            for item in page.file_tree.get_children()
                        ]
                        page._sort_name.set("Mais recentes")
                        page._on_sort_change("Mais recentes")
                        recent_names = [
                            page.file_tree.item(item, "values")[0]
                            for item in page.file_tree.get_children()
                        ]
                        page._sort_name.set("Nome")
                        page._on_sort_change("Nome")

                        page._query.set(unicodedata.normalize("NFD", "AÇÃO"))
                        page._apply_search_now()
                        unicode_query_names = [
                            page.file_tree.item(item, "values")[0]
                            for item in page.file_tree.get_children()
                        ]
                        page._query.set("prova")
                        page.filter_control.set("PDF")
                        page._on_filter_change("PDF")
                        combined_names = [
                            page.file_tree.item(item, "values")[0]
                            for item in page.file_tree.get_children()
                        ]
                        scans_after_filters = len(scan_calls)
                        page._query.set("")
                        page.filter_control.set("Todos")
                        page._on_filter_change("Todos")

                        def select_name(name):
                            item = next(
                                item
                                for item in page.file_tree.get_children()
                                if page._entry_by_item[item].name == name
                            )
                            page.file_tree.selection_set(item)
                            page._on_tree_selection()

                        select_name("foto ação.PNG")
                        image_details = {
                            "name": page._detail_name.get(),
                            "type": page._detail_type.get(),
                            "size": page._detail_size.get(),
                            "modified": page._detail_modified.get(),
                            "image_action_visible": bool(
                                page.image_pdf_button.winfo_manager()
                            ),
                            "poster_action_visible": bool(
                                page.poster_button.winfo_manager()
                            ),
                            "extract_hidden": not bool(
                                page.extract_button.winfo_manager()
                            ),
                        }
                        page._open_selected()
                        page._reveal_selected()
                        page.image_pdf_button.invoke()
                        page.poster_button.invoke()

                        select_name("prova2.pdf")
                        page.extract_button.invoke()
                        page.pdf_images_button.invoke()
                        select_name("aula.mp4")
                        page.video_mp3_button.invoke()
                        select_name("trilha.mp3")
                        audio_state = {
                            "text": page._edu_action_text.get(),
                            "visible_actions": sum(
                                bool(button.winfo_manager())
                                for button in page._context_buttons
                            ),
                        }

                        style = ttk.Style(page)
                        theme_state_before = {
                            "tree_id": str(page.file_tree),
                            "directory": page.directory.name,
                            "snapshot": [entry.name for entry in page.snapshot],
                            "selected": page._detail_name.get(),
                            "query": page._query.get(),
                            "filter": page.filter_control.get(),
                        }
                        page.apply_theme("Escuro")
                        assert style.layout(page._TREE_STYLE)[0][0] == page._TREE_FIELD_ELEMENT
                        assert "fieldbackground" in style.element_options(page._TREE_FIELD_ELEMENT)
                        dark_style = {
                            "tree_background": style.lookup(
                                page._TREE_STYLE, "background"
                            ),
                            "tree_foreground": style.lookup(
                                page._TREE_STYLE, "foreground"
                            ),
                            "tree_field": style.lookup(
                                page._TREE_STYLE, "fieldbackground"
                            ),
                            "heading_background": style.lookup(
                                page._HEADING_STYLE, "background"
                            ),
                            "heading_foreground": style.lookup(
                                page._HEADING_STYLE, "foreground"
                            ),
                            "heading_active": style.lookup(
                                page._HEADING_STYLE,
                                "background",
                                ("active",),
                            ),
                            "heading_element": style.layout(
                                page._HEADING_STYLE
                            )[0][0],
                            "selection_background": style.lookup(
                                page._TREE_STYLE,
                                "background",
                                ("selected",),
                            ),
                            "selection_foreground": style.lookup(
                                page._TREE_STYLE,
                                "foreground",
                                ("selected",),
                            ),
                        }
                        page.apply_theme("Claro")
                        light_style = {
                            "tree_background": style.lookup(
                                page._TREE_STYLE, "background"
                            ),
                            "tree_foreground": style.lookup(
                                page._TREE_STYLE, "foreground"
                            ),
                            "tree_field": style.lookup(
                                page._TREE_STYLE, "fieldbackground"
                            ),
                            "heading_background": style.lookup(
                                page._HEADING_STYLE, "background"
                            ),
                            "heading_foreground": style.lookup(
                                page._HEADING_STYLE, "foreground"
                            ),
                            "heading_active": style.lookup(
                                page._HEADING_STYLE,
                                "background",
                                ("active",),
                            ),
                            "heading_element": style.layout(
                                page._HEADING_STYLE
                            )[0][0],
                            "selection_background": style.lookup(
                                page._TREE_STYLE,
                                "background",
                                ("selected",),
                            ),
                            "selection_foreground": style.lookup(
                                page._TREE_STYLE,
                                "foreground",
                                ("selected",),
                            ),
                        }
                        page.apply_theme("Escuro")
                        dark_reapplied = style.lookup(
                            page._HEADING_STYLE, "background"
                        )
                        theme_state_after = {
                            "tree_id": str(page.file_tree),
                            "directory": page.directory.name,
                            "snapshot": [entry.name for entry in page.snapshot],
                            "selected": page._detail_name.get(),
                            "query": page._query.get(),
                            "filter": page.filter_control.get(),
                        }

                        select_name("foto ação.PNG")

                        def stale_action(_entry, _directory):
                            raise LocalFilesError(
                                "O arquivo selecionado não está mais disponível."
                            )

                        page._open_file = stale_action
                        page._revalidate_file = stale_action
                        stale_result = page._open_selected()
                        names_after_stale = [entry.name for entry in page.snapshot]
                        displayed_values = [
                            value
                            for item in page.file_tree.get_children()
                            for value in page.file_tree.item(item, "values")
                        ]

                        result = {
                            "initial": initial,
                            "loading_before_poll": loading_before_poll,
                            "tree_before_poll": tree_before_poll,
                            "second_scan": second_scan,
                            "loaded_names": loaded_names,
                            "recent_names": recent_names,
                            "loaded_status": loaded_status,
                            "unicode_query_names": unicode_query_names,
                            "combined_names": combined_names,
                            "scans_after_filters": scans_after_filters,
                            "scan_calls": scan_calls,
                            "worker_names": worker_names,
                            "worker_threads": worker_threads,
                            "main_thread": main_thread,
                            "image_details": image_details,
                            "opened": opened,
                            "revealed": revealed,
                            "routed": routed,
                            "revalidated": revalidated,
                            "audio_state": audio_state,
                            "dark_style": dark_style,
                            "light_style": light_style,
                            "dark_reapplied": dark_reapplied,
                            "theme_state_before": theme_state_before,
                            "theme_state_after": theme_state_after,
                            "stale_result": stale_result,
                            "names_after_stale": names_after_stale,
                            "errors": errors,
                            "warnings": warnings,
                            "absolute_path_displayed": any(
                                str(directory) in str(value)
                                for value in displayed_values
                            ),
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
        self.assertEqual(result["initial"]["choose"], "Escolher pasta")
        self.assertEqual(result["initial"]["refresh"], "Atualizar")
        self.assertEqual(result["initial"]["refresh_state"], "disabled")
        self.assertEqual(
            result["initial"]["filters"],
            ["Todos", "Documentos", "PDF", "Imagens", "Vídeos", "Áudios"],
        )
        self.assertEqual(result["initial"]["sorts"], ["Nome", "Mais recentes"])
        self.assertEqual(result["initial"]["sort"], "Nome")
        self.assertEqual(result["initial"]["count"], "Mostrando 0 de 0")
        self.assertEqual(
            result["initial"]["columns"], ["name", "type", "size", "modified"]
        )
        self.assertEqual(result["initial"]["tree_children"], 0)
        self.assertEqual(result["initial"]["folder"], "Nenhuma pasta selecionada")
        self.assertEqual(
            result["initial"]["status"], "Escolha uma pasta para ver seus arquivos."
        )
        self.assertEqual(
            result["initial"]["detail_heading"], "Nenhum arquivo selecionado"
        )
        self.assertEqual(result["initial"]["remove_favorite"], "Remover dos favoritos")
        self.assertTrue(result["initial"]["double_click_bound"])
        self.assertEqual(result["initial"]["video_action"], "Extrair áudio do vídeo")
        self.assertEqual(result["initial"]["heading_background"], "#24394D")
        self.assertTrue(result["loading_before_poll"])
        self.assertEqual(result["tree_before_poll"], 0)
        self.assertFalse(result["second_scan"])
        self.assertEqual(
            result["loaded_names"],
            ["aula.mp4", "foto ação.PNG", "prova2.pdf", "prova10.pdf", "trilha.mp3"],
        )
        self.assertEqual(
            result["recent_names"],
            ["trilha.mp3", "aula.mp4", "foto ação.PNG", "prova10.pdf", "prova2.pdf"],
        )
        self.assertEqual(result["loaded_status"], "5 arquivos encontrados.")
        self.assertEqual(result["unicode_query_names"], ["foto ação.PNG"])
        self.assertEqual(result["combined_names"], ["prova2.pdf", "prova10.pdf"])
        self.assertEqual(result["scans_after_filters"], 1)
        self.assertEqual(len(result["scan_calls"]), 1)
        self.assertEqual(result["worker_names"], ["edudownloader-files-worker"])
        self.assertTrue(
            all(
                thread_id != result["main_thread"]
                for thread_id in result["worker_threads"]
            )
        )
        self.assertEqual(result["image_details"]["name"], "foto ação.PNG")
        self.assertIn("Imagem", result["image_details"]["type"])
        self.assertEqual(result["image_details"]["size"], "1.5 MB")
        self.assertTrue(result["image_details"]["modified"])
        self.assertTrue(result["image_details"]["image_action_visible"])
        self.assertTrue(result["image_details"]["poster_action_visible"])
        self.assertTrue(result["image_details"]["extract_hidden"])
        self.assertEqual(result["opened"][0][0], "foto ação.PNG")
        self.assertEqual(result["revealed"][0][0], "foto ação.PNG")
        self.assertEqual(
            result["routed"],
            [
                ["image-pdf", "foto ação.PNG"],
                ["poster", "foto ação.PNG"],
                ["extract", "prova2.pdf"],
                ["pdf-images", "prova2.pdf"],
                ["video-mp3", "aula.mp4"],
            ],
        )
        self.assertGreaterEqual(len(result["revalidated"]), 4)
        self.assertIn("Nenhuma conversão", result["audio_state"]["text"])
        self.assertEqual(result["audio_state"]["visible_actions"], 0)
        self.assertEqual(
            result["dark_style"],
            {
                "tree_background": "#17283B",
                "tree_foreground": "#F1F7FF",
                "tree_field": "#17283B",
                "heading_background": "#24394D",
                "heading_foreground": "#F1F7FF",
                "heading_active": "#314C65",
                "heading_element": "EduDownloader.Files.Treeheading.cell",
                "selection_background": "#314C65",
                "selection_foreground": "#F1F7FF",
            },
        )
        self.assertEqual(
            result["light_style"],
            {
                "tree_background": "#FFFFFF",
                "tree_foreground": "#152A40",
                "tree_field": "#FFFFFF",
                "heading_background": "#EBF3FA",
                "heading_foreground": "#152A40",
                "heading_active": "#DDEAF5",
                "heading_element": "EduDownloader.Files.Treeheading.cell",
                "selection_background": "#DDEAF5",
                "selection_foreground": "#152A40",
            },
        )
        self.assertEqual(result["dark_reapplied"], "#24394D")
        self.assertEqual(result["theme_state_after"], result["theme_state_before"])
        self.assertFalse(result["stale_result"])
        self.assertNotIn("foto ação.PNG", result["names_after_stale"])
        self.assertTrue(result["errors"])
        self.assertFalse(result["absolute_path_displayed"])

    def test_documents_filter_types_actions_preview_and_layout(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    r"""
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path

                    import customtkinter as ctk

                    from local_files import LocalFileCategory, LocalFileEntry
                    from ui_pages import FilesPage, FilesPageActions

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs): self.target = target
                        def start(self): self.target()

                    routed = []
                    opened = []
                    revealed = []
                    preview_calls = []

                    class PreviewMustNotRun:
                        def create_preview(self, *_args):
                            preview_calls.append(True)
                            raise AssertionError("document preview worker must not run")

                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.geometry("860x600")
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir) / "Favorita Ação 你好"
                        directory.mkdir()
                        definitions = (
                            ("Aula ação 你好.DOCX", ".docx"),
                            ("Legado.DOC", ".doc"),
                            ("Plano.ODT", ".odt"),
                            ("Notas.TXT", ".txt"),
                        )
                        entries = []
                        for index, (name, _suffix) in enumerate(definitions):
                            path = directory / name
                            path.write_text("fixture", encoding="utf-8")
                            entries.append(LocalFileEntry(
                                path, LocalFileCategory.DOCUMENT, index + 1,
                                1_700_000_000.0 + index,
                            ))
                        pdf = directory / "separado.pdf"
                        pdf.write_bytes(b"%PDF")
                        entries.append(LocalFileEntry(
                            pdf, LocalFileCategory.PDF, 4, 1_699_999_999.0
                        ))
                        entries = tuple(entries)

                        def route(path):
                            routed.append(Path(path).name)
                            return True

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=lambda _message: None,
                                show_error=lambda _message: None,
                                extract_pages=lambda _path: True,
                                pdf_to_images=lambda _path: True,
                                image_to_pdf=lambda _path: True,
                                video_to_mp3=lambda _path: True,
                                docx_to_pdf=route,
                                odt_to_pdf=route,
                                txt_to_pdf=route,
                            ),
                            thread_factory=ImmediateThread,
                            list_files=lambda _directory: entries,
                            open_file=lambda entry, _directory: opened.append(entry.name) or entry.path,
                            reveal_file=lambda entry, _directory: revealed.append(entry.name) or entry.path,
                            revalidate_file=lambda entry, _directory: entry,
                            preview_service=PreviewMustNotRun(),
                            get_favorites=lambda: (str(directory),),
                        )
                        page.pack(fill="both", expand=True)
                        root.deiconify()
                        root.update_idletasks()
                        page._start_scan(directory, replace_directory=True)
                        page._poll_scan()
                        page.filter_control.set("Documentos")
                        page._on_filter_change("Documentos")
                        root.update_idletasks()

                        def select_name(name):
                            item = next(
                                item for item in page.file_tree.get_children()
                                if page._entry_by_item[item].name == name
                            )
                            page.file_tree.selection_set(item)
                            page._on_tree_selection()

                        documents = [
                            list(page.file_tree.item(item, "values")[:2])
                            for item in page.file_tree.get_children()
                        ]
                        states = {}
                        for name, _suffix in definitions:
                            select_name(name)
                            states[name] = {
                                "type": page._detail_type.get(),
                                "preview": page._preview_text.get(),
                                "convert": bool(page.docx_pdf_button.winfo_manager()),
                                "actions": sum(
                                    bool(button.winfo_manager())
                                    for button in page._context_buttons
                                ),
                            }
                            if _suffix != ".doc":
                                page.docx_pdf_button.invoke()
                        select_name(definitions[0][0])
                        page._open_selected()
                        page._reveal_selected()

                        page._query.set("inexistente")
                        page._apply_search_now()
                        search_empty = page._status.get()
                        page._query.set("")
                        page._apply_search_now()
                        page._set_snapshot((entries[-1],))
                        page.filter_control.set("Documentos")
                        page._on_filter_change("Documentos")
                        filter_empty = page._status.get()

                        page._set_snapshot(entries)
                        page.filter_control.set("Documentos")
                        page._on_filter_change("Documentos")
                        page._sort_name.set("Mais recentes")
                        page._on_sort_change("Mais recentes")
                        recent = [
                            page.file_tree.item(item, "values")[0]
                            for item in page.file_tree.get_children()
                        ]
                        page.apply_theme("Claro")
                        light_type = page._type_label(entries[0])
                        page.apply_theme("Escuro")
                        dark_type = page._type_label(entries[0])
                        root.update_idletasks()
                        layout = {
                            "page_width": page.winfo_width(),
                            "filter_width": page.filter_control.winfo_reqwidth(),
                            "sort_visible": bool(page.sort_menu.winfo_manager()),
                            "horizontal_scrollbars": sum(
                                getattr(widget, "cget", lambda _key: "")("orient") == "horizontal"
                                for widget in page.winfo_children()
                                if widget.winfo_class() == "TScrollbar"
                            ),
                        }
                        favorite_values = list(page.favorite_menu.cget("values"))
                        root.withdraw(); page.close(); root.destroy()
                        print(json.dumps({
                            "filters": list(page.filter_names),
                            "documents": documents,
                            "states": states,
                            "routed": routed,
                            "opened": opened,
                            "revealed": revealed,
                            "preview_calls": preview_calls,
                            "search_empty": search_empty,
                            "filter_empty": filter_empty,
                            "recent": recent,
                            "light_type": light_type,
                            "dark_type": dark_type,
                            "layout": layout,
                            "favorite_values": favorite_values,
                        }, ensure_ascii=True))
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
            result["filters"],
            ["Todos", "Documentos", "PDF", "Imagens", "Vídeos", "Áudios"],
        )
        self.assertEqual(
            result["documents"],
            [
                ["Aula ação 你好.DOCX", "Documento do Word"],
                ["Legado.DOC", "Documento do Word (antigo)"],
                ["Notas.TXT", "Arquivo de texto"],
                ["Plano.ODT", "Documento OpenDocument"],
            ],
        )
        states = result["states"]
        self.assertTrue(states["Aula ação 你好.DOCX"]["convert"])
        self.assertEqual(states["Aula ação 你好.DOCX"]["actions"], 1)
        for name in ("Plano.ODT", "Notas.TXT"):
            self.assertTrue(states[name]["convert"])
            self.assertEqual(states[name]["actions"], 1)
        self.assertFalse(states["Legado.DOC"]["convert"])
        self.assertEqual(states["Legado.DOC"]["actions"], 0)
        self.assertEqual(
            {name: state["preview"] for name, state in states.items()},
            {
                "Aula ação 你好.DOCX": "Carregando prévia...",
                "Legado.DOC": "Prévia de .doc não disponível. Use Abrir.",
                "Plano.ODT": "Carregando prévia...",
                "Notas.TXT": "Prévia visual não disponível.",
            },
        )
        self.assertEqual(
            result["routed"],
            ["Aula ação 你好.DOCX", "Plano.ODT", "Notas.TXT"],
        )
        self.assertEqual(result["opened"], ["Aula ação 你好.DOCX"])
        self.assertEqual(result["revealed"], ["Aula ação 你好.DOCX"])
        self.assertEqual(result["preview_calls"], [])
        self.assertEqual(
            result["search_empty"],
            "Nenhum arquivo corresponde à busca. Tente outro termo.",
        )
        self.assertEqual(
            result["filter_empty"],
            "Nenhum documento encontrado. Escolha outro filtro ou pasta.",
        )
        self.assertEqual(
            result["recent"],
            ["Notas.TXT", "Plano.ODT", "Legado.DOC", "Aula ação 你好.DOCX"],
        )
        self.assertEqual(result["light_type"], "Documento do Word")
        self.assertEqual(result["dark_type"], "Documento do Word")
        self.assertLess(
            result["layout"]["filter_width"], result["layout"]["page_width"]
        )
        self.assertTrue(result["layout"]["sort_visible"])
        self.assertEqual(result["layout"]["horizontal_scrollbars"], 0)
        self.assertEqual(len(result["favorite_values"]), 2)

    def test_list_layout_remains_visible_when_resized_or_empty(self) -> None:
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

                    from local_files import LocalFileCategory, LocalFileEntry
                    from ui_pages import FilesPage, FilesPageActions

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    ctk.set_appearance_mode("Light")
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        entries = tuple(
                            LocalFileEntry(
                                directory / f"arquivo {index:02d}.pdf",
                                LocalFileCategory.PDF,
                                1024 + index,
                                1_700_000_000.0 + index,
                            )
                            for index in range(15)
                        )
                        current_entries = [()]

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=lambda _message: None,
                                show_error=lambda _message: None,
                                extract_pages=lambda _path: True,
                                pdf_to_images=lambda _path: True,
                                image_to_pdf=lambda _path: True,
                                video_to_mp3=lambda _path: True,
                            ),
                            thread_factory=ImmediateThread,
                            list_files=lambda _directory: current_entries[0],
                        )
                        page.pack(fill="both", expand=True)

                        def layout_at(size):
                            root.geometry(size)
                            root.deiconify()
                            root.update_idletasks()
                            root.update()
                            return {
                                "page_height": page.winfo_height(),
                                "wide": page._files_wide,
                                "list_right": page.file_list_frame.winfo_x() + page.file_list_frame.winfo_width(),
                                "context_x": page.context_frame.winfo_x(),
                                "list_y": page.file_list_frame.winfo_y(),
                                "list_height": page.file_list_frame.winfo_height(),
                                "tree_height": page.file_tree.winfo_height(),
                                "tree_mapped": bool(page.file_tree.winfo_ismapped()),
                                "context_y": page.context_frame.winfo_y(),
                                "context_height": page.context_frame.winfo_height(),
                                "status_y": page.status_frame.winfo_y(),
                                "status_height": page.status_frame.winfo_height(),
                            }

                        root.geometry("860x600")
                        root.deiconify()
                        root.update()
                        first_use = (
                            bool(page.initial_choose_button.winfo_ismapped())
                            and not page.file_tree.winfo_ismapped()
                        )
                        page._start_scan(directory, replace_directory=True)
                        page._poll_scan()
                        empty = layout_at("860x600")

                        current_entries[0] = entries
                        page._refresh_directory()
                        page._poll_scan()
                        populated = {
                            size: layout_at(size)
                            for size in ("1040x720", "860x600", "1200x800")
                        }

                        first_item = page.file_tree.get_children()[0]
                        page.file_tree.selection_set(first_item)
                        page._on_tree_selection()
                        selected_minimum = layout_at("860x600")

                        page._query.set("resultado inexistente")
                        page._apply_search_now()
                        filtered_empty = layout_at("860x600")

                        tree_id = str(page.file_tree)
                        page.apply_theme("Escuro")
                        dark_heading = page.file_tree.cget("style")
                        page.apply_theme("Claro")
                        theme_preserved = tree_id == str(page.file_tree)

                        page._query.set("")
                        page._apply_search_now()
                        page.file_tree.yview_moveto(1.0)
                        root.update_idletasks()
                        result = {
                            "empty": empty,
                            "first_use": first_use,
                            "populated": populated,
                            "selected_minimum": selected_minimum,
                            "filtered_empty": filtered_empty,
                            "tree_children": len(page.file_tree.get_children()),
                            "list_grid": {
                                key: int(value)
                                for key, value in page.file_list_frame.grid_info().items()
                                if key in {"row", "column"}
                            },
                            "tree_grid": {
                                key: int(value)
                                for key, value in page.file_tree.grid_info().items()
                                if key in {"row", "column"}
                            },
                            "scrollbar_grid": {
                                key: int(value)
                                for key, value in page.file_scrollbar.grid_info().items()
                                if key in {"row", "column"}
                            },
                            "same_list_parent": (
                                page.file_tree.master is page.file_list_frame
                                and page.file_scrollbar.master is page.file_list_frame
                            ),
                            "scroll_commands": bool(
                                str(page.file_tree.cget("yscrollcommand"))
                                and str(page.file_scrollbar.cget("command"))
                            ),
                            "scroll_moved": page.file_tree.yview()[0] > 0,
                            "list_row": {
                                "weight": int(page.grid_rowconfigure(4)["weight"]),
                                "minsize": int(page.grid_rowconfigure(4)["minsize"]),
                            },
                            "context_row_weight": int(
                                page.grid_rowconfigure(5)["weight"]
                            ),
                            "theme_style": dark_heading,
                            "theme_preserved": theme_preserved,
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

        for state in (
            result["empty"],
            *result["populated"].values(),
            result["selected_minimum"],
            result["filtered_empty"],
        ):
            self.assertTrue(state["tree_mapped"])
            self.assertGreaterEqual(state["list_height"], 130)
            self.assertGreaterEqual(state["tree_height"], 110)
            if state["wide"]:
                self.assertEqual(state["list_y"], state["context_y"])
                self.assertLess(state["list_right"], state["context_x"])
            else:
                self.assertLess(
                    state["list_y"] + state["list_height"],
                    state["context_y"],
                )
            self.assertLess(
                state["context_y"] + state["context_height"],
                state["status_y"],
            )
            self.assertLessEqual(
                state["status_y"] + state["status_height"],
                state["page_height"],
            )

        self.assertTrue(result["first_use"])
        self.assertFalse(result["populated"]["860x600"]["wide"])
        self.assertTrue(result["populated"]["1200x800"]["wide"])
        self.assertEqual(result["tree_children"], 15)
        self.assertEqual(result["list_grid"], {"row": 0, "column": 0})
        self.assertEqual(result["tree_grid"], {"row": 1, "column": 0})
        self.assertEqual(result["scrollbar_grid"], {"row": 1, "column": 1})
        self.assertTrue(result["same_list_parent"])
        self.assertTrue(result["scroll_commands"])
        self.assertTrue(result["scroll_moved"])
        self.assertEqual(result["theme_style"], "EduDownloader.Files.Treeview")
        self.assertTrue(result["theme_preserved"])

    def test_empty_large_refresh_error_and_session_state(self) -> None:
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
                    from tkinter import ttk

                    import customtkinter as ctk

                    from local_files import LocalFileCategory, LocalFileEntry, LocalFilesError
                    from ui_pages import FilesPage, FilesPageActions

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    mode = ["empty"]
                    errors = []

                    ctk.set_appearance_mode("Light")
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        large_entries = tuple(
                            LocalFileEntry(
                                directory / f"arquivo{index}.pdf",
                                LocalFileCategory.PDF,
                                index + 1,
                                1_700_000_000.0 + index,
                            )
                            for index in range(500)
                        )

                        def list_files(_directory):
                            if mode[0] == "empty":
                                return ()
                            if mode[0] == "large":
                                return large_entries
                            if mode[0] == "small":
                                return large_entries[:2]
                            raise LocalFilesError("A pasta selecionada não está disponível.")

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=lambda _message: None,
                                show_error=errors.append,
                                extract_pages=lambda _path: True,
                                pdf_to_images=lambda _path: True,
                                image_to_pdf=lambda _path: True,
                                video_to_mp3=lambda _path: True,
                            ),
                            thread_factory=ImmediateThread,
                            list_files=list_files,
                        )
                        page.pack(fill="both", expand=True)
                        root.update_idletasks()
                        page._RENDER_BATCH_SIZE = 1_000

                        page._start_scan(directory, replace_directory=True)
                        page._poll_scan()
                        empty_state = {
                            "snapshot": len(page.snapshot),
                            "tree": len(page.file_tree.get_children()),
                            "status": page._status.get(),
                            "heading_background": ttk.Style(page).lookup(
                                page._HEADING_STYLE, "background"
                            ),
                        }
                        mode[0] = "large"
                        page._refresh_directory()
                        page._poll_scan()
                        native_children_before = len(page.file_tree.winfo_children())
                        first_tree_item = page.file_tree.get_children()[0]
                        page.file_tree.selection_set(first_tree_item)
                        page._on_tree_selection()
                        page.pack_forget()
                        page.pack(fill="both", expand=True)
                        persistent_state = {
                            "snapshot": len(page.snapshot),
                            "tree": len(page.file_tree.get_children()),
                            "selected": page._detail_name.get(),
                            "native_children": native_children_before,
                        }

                        mode[0] = "small"
                        page._refresh_directory()
                        page._poll_scan()
                        reduced_state = {
                            "snapshot": len(page.snapshot),
                            "selected": page._detail_name.get(),
                        }

                        mode[0] = "error"
                        page._refresh_directory()
                        page._poll_scan()
                        error_state = {
                            "directory": page.directory is None,
                            "snapshot": len(page.snapshot),
                            "tree": len(page.file_tree.get_children()),
                            "selected": page._detail_name.get(),
                            "choose_state": page.choose_button.cget("state"),
                            "refresh_state": page.refresh_button.cget("state"),
                            "status": page._status.get(),
                        }
                        result = {
                            "empty_state": empty_state,
                            "persistent_state": persistent_state,
                            "reduced_state": reduced_state,
                            "error_state": error_state,
                            "errors": errors,
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
        self.assertEqual(result["empty_state"]["snapshot"], 0)
        self.assertEqual(result["empty_state"]["tree"], 0)
        self.assertIn("Nenhum arquivo compatível", result["empty_state"]["status"])
        self.assertEqual(result["empty_state"]["heading_background"], "#EBF3FA")
        self.assertEqual(result["persistent_state"]["snapshot"], 500)
        self.assertEqual(result["persistent_state"]["tree"], 500)
        self.assertEqual(result["persistent_state"]["selected"], "arquivo0.pdf")
        self.assertEqual(result["persistent_state"]["native_children"], 0)
        self.assertEqual(result["reduced_state"]["snapshot"], 2)
        self.assertEqual(result["reduced_state"]["selected"], "arquivo0.pdf")
        self.assertTrue(result["error_state"]["directory"])
        self.assertEqual(result["error_state"]["snapshot"], 0)
        self.assertEqual(result["error_state"]["tree"], 0)
        self.assertEqual(result["error_state"]["selected"], "—")
        self.assertEqual(result["error_state"]["choose_state"], "normal")
        self.assertEqual(result["error_state"]["refresh_state"], "disabled")
        self.assertIn("não está disponível", result["error_state"]["status"])
        self.assertEqual(result["errors"], ["A pasta selecionada não está disponível."])

    def test_projection_debounce_show_more_and_stale_render_are_bounded(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tkinter as tk
                    from pathlib import Path

                    import customtkinter as ctk

                    from local_files import LocalFileCategory, LocalFileEntry
                    from ui_pages import FilesPage, FilesPageActions

                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()

                    page = FilesPage(
                        root,
                        actions=FilesPageActions(
                            show_warning=lambda _message: None,
                            show_error=lambda _message: None,
                            extract_pages=lambda _path: True,
                            pdf_to_images=lambda _path: True,
                            image_to_pdf=lambda _path: True,
                            video_to_mp3=lambda _path: True,
                        ),
                    )
                    page.pack(fill="both", expand=True)
                    root.update_idletasks()

                    page._PROJECTION_WORKER_THRESHOLD = 20_000

                    entries = tuple(
                        LocalFileEntry(
                            Path(f"arquivo{index}.pdf"),
                            LocalFileCategory.PDF,
                            index + 1,
                            float(index),
                        )
                        for index in range(10_000)
                    )
                    scheduled = {}
                    cancelled = []
                    sequence = [0]
                    operation_count = [0]
                    batch_sizes = []

                    def fake_after(delay, callback):
                        sequence[0] += 1
                        token = f"scheduled-{sequence[0]}"
                        scheduled[token] = (delay, callback)
                        return token

                    def fake_after_cancel(token):
                        cancelled.append(token)
                        scheduled.pop(token, None)

                    original_insert = page.file_tree.insert
                    original_delete = page.file_tree.delete

                    def tracked_insert(*args, **kwargs):
                        operation_count[0] += 1
                        return original_insert(*args, **kwargs)

                    def tracked_delete(*args, **kwargs):
                        operation_count[0] += len(args)
                        return original_delete(*args, **kwargs)

                    page.after = fake_after
                    page.after_cancel = fake_after_cancel
                    page.file_tree.insert = tracked_insert
                    page.file_tree.delete = tracked_delete

                    def run_callback(callback):
                        operation_count[0] = 0
                        callback()
                        batch_sizes.append(operation_count[0])

                    def drain_render():
                        while page._render_after_id is not None:
                            token = page._render_after_id
                            _delay, callback = scheduled.pop(token)
                            run_callback(callback)

                    operation_count[0] = 0
                    page._set_snapshot(entries)
                    batch_sizes.append(operation_count[0])
                    initial_tick_rows = len(page.file_tree.get_children())
                    obsolete_token = page._render_after_id
                    obsolete_callback = scheduled[obsolete_token][1]

                    page.file_tree.selection_set(page.file_tree.get_children()[0])
                    page._on_tree_selection()
                    page._query.set("arquivo9999")
                    debounce_delay = scheduled[page._search_after_id][0]
                    page._apply_search_now()
                    stale_before = len(page.file_tree.get_children())
                    run_callback(obsolete_callback)
                    stale_after = len(page.file_tree.get_children())
                    selection_after_projection = page._detail_name.get()
                    drain_render()
                    search_state = {
                        "rows": len(page.file_tree.get_children()),
                        "count": page._visible_count_text.get(),
                    }

                    page._query.set("")
                    page._apply_search_now()
                    drain_render()
                    initial_projection = {
                        "rows": len(page.file_tree.get_children()),
                        "count": page._visible_count_text.get(),
                        "show_more": bool(page.show_more_button.winfo_manager()),
                    }

                    page._sort_name.set("Mais recentes")
                    page._on_sort_change("Mais recentes")
                    drain_render()
                    recent_first = page.file_tree.item(
                        page.file_tree.get_children()[0], "values"
                    )[0]

                    page._show_more()
                    drain_render()
                    expanded = {
                        "rows": len(page.file_tree.get_children()),
                        "count": page._visible_count_text.get(),
                        "limit": page._visible_limit,
                    }

                    page._sort_name.set("Nome")
                    page._on_sort_change("Nome")
                    drain_render()
                    order_reset = {
                        "rows": len(page.file_tree.get_children()),
                        "limit": page._visible_limit,
                    }
                    page._show_more()
                    drain_render()
                    page.filter_control.set("PDF")
                    page._on_filter_change("PDF")
                    drain_render()
                    filter_reset = {
                        "rows": len(page.file_tree.get_children()),
                        "limit": page._visible_limit,
                    }

                    page._query.set("arquivo9")
                    old_debounce = scheduled[page._search_after_id][1]
                    page._query.set("arquivo999")
                    latest_debounce = scheduled[page._search_after_id][1]
                    rows_before_old_debounce = len(page.file_tree.get_children())
                    old_debounce()
                    rows_after_old_debounce = len(page.file_tree.get_children())
                    latest_debounce()
                    drain_render()
                    debounced = {
                        "rows": len(page.file_tree.get_children()),
                        "count": page._visible_count_text.get(),
                        "limit": page._visible_limit,
                    }

                    result = {
                        "batch_limit": page._RENDER_BATCH_SIZE,
                        "max_batch": max(batch_sizes),
                        "initial_tick_rows": initial_tick_rows,
                        "scheduled_batches": len(batch_sizes) > 1,
                        "stale_unchanged": stale_before == stale_after,
                        "selection_after_projection": selection_after_projection,
                        "search_state": search_state,
                        "initial_projection": initial_projection,
                        "recent_first": recent_first,
                        "expanded": expanded,
                        "order_reset": order_reset,
                        "filter_reset": filter_reset,
                        "debounce_delay": debounce_delay,
                        "old_debounce_ignored": (
                            rows_before_old_debounce == rows_after_old_debounce
                        ),
                        "debounced": debounced,
                        "cancelled_callbacks": len(cancelled),
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

        self.assertEqual(result["batch_limit"], 100)
        self.assertLessEqual(result["max_batch"], 100)
        self.assertEqual(result["initial_tick_rows"], 100)
        self.assertTrue(result["scheduled_batches"])
        self.assertTrue(result["stale_unchanged"])
        self.assertEqual(result["selection_after_projection"], "—")
        self.assertEqual(
            result["search_state"], {"rows": 1, "count": "Mostrando 1 de 1"}
        )
        self.assertEqual(
            result["initial_projection"],
            {
                "rows": 500,
                "count": "Mostrando 500 de 10000",
                "show_more": True,
            },
        )
        self.assertEqual(result["recent_first"], "arquivo9999.pdf")
        self.assertEqual(
            result["expanded"],
            {"rows": 1_000, "count": "Mostrando 1000 de 10000", "limit": 1_000},
        )
        self.assertEqual(result["order_reset"], {"rows": 500, "limit": 500})
        self.assertEqual(result["filter_reset"], {"rows": 500, "limit": 500})
        self.assertEqual(result["debounce_delay"], 250)
        self.assertTrue(result["old_debounce_ignored"])
        self.assertEqual(result["debounced"]["limit"], 500)
        self.assertGreater(result["debounced"]["rows"], 0)
        self.assertIn("Mostrando", result["debounced"]["count"])
        self.assertGreater(result["cancelled_callbacks"], 0)

    def test_close_neutralizes_late_scan_result_without_blocking_shutdown(
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

                    from local_files import LocalFileCategory, LocalFileEntry
                    from ui_pages import FilesPage, FilesPageActions

                    class DeferredThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            return None

                    threads = []

                    def thread_factory(**kwargs):
                        thread = DeferredThread(**kwargs)
                        threads.append(thread)
                        return thread

                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    errors = []

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        entry = LocalFileEntry(
                            directory / "resultado tardio.pdf",
                            LocalFileCategory.PDF,
                            123,
                            1_700_000_000.0,
                        )
                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=lambda _message: None,
                                show_error=errors.append,
                                extract_pages=lambda _path: True,
                                pdf_to_images=lambda _path: True,
                                image_to_pdf=lambda _path: True,
                                video_to_mp3=lambda _path: True,
                            ),
                            thread_factory=thread_factory,
                            list_files=lambda _directory: (entry,),
                        )
                        page.pack()
                        root.update_idletasks()
                        polls = []
                        page.after = lambda delay, callback: polls.append(
                            (delay, callback.__name__)
                        )

                        started = page._start_scan(
                            directory, replace_directory=True
                        )
                        page.close()
                        threads[0].target()
                        page._poll_scan()
                        result = {
                            "started": started,
                            "closed": page._closed,
                            "polls": polls,
                            "snapshot": len(page.snapshot),
                            "tree": len(page.file_tree.get_children()),
                            "folder": page._folder_text.get(),
                            "errors": errors,
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
        self.assertTrue(result["started"])
        self.assertTrue(result["closed"])
        self.assertEqual(
            [entry for entry in result["polls"] if entry[1] == "_poll_scan"],
            [[80, "_poll_scan"]],
        )
        self.assertEqual(result["snapshot"], 0)
        self.assertEqual(result["tree"], 0)
        self.assertEqual(result["folder"], "Nenhuma pasta selecionada")
        self.assertEqual(result["errors"], [])

    def test_favorite_shortcuts_use_settings_without_automatic_catalog(self) -> None:
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

                    from local_files import LocalFileCategory, LocalFileEntry, LocalFilesError
                    from settings import (
                        FavoriteFolderResult,
                        add_favorite_folder,
                        get_favorite_folders,
                        is_favorite_folder,
                        remove_favorite_folder,
                    )
                    from ui_pages import FilesPage, FilesPageActions

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.geometry("660x600")
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        base = Path(temporary_dir)
                        first = base / "Escola A" / "Material"
                        second = base / "Escola B" / "Material"
                        unicode_folder = base / "João — Educação 你好"
                        unavailable = base / "Unidade ausente"
                        inaccessible = base / "Pasta inacessível"
                        candidate = base / "Limite atingido"
                        for folder in (first, second, unicode_folder, candidate):
                            folder.mkdir(parents=True)
                        settings_path = base / "settings.json"
                        scan_calls = []
                        routed = []
                        opened = []
                        warnings = []
                        errors = []

                        def list_files(directory):
                            directory = Path(directory)
                            scan_calls.append(str(directory))
                            if directory == unavailable:
                                raise LocalFilesError("detalhe interno ausente")
                            if directory == inaccessible:
                                raise PermissionError("detalhe interno inacessível")
                            return (
                                LocalFileEntry(
                                    directory / "arquivo.pdf",
                                    LocalFileCategory.PDF,
                                    123,
                                    1_700_000_000.0,
                                ),
                            )

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=warnings.append,
                                show_error=errors.append,
                                extract_pages=lambda path: routed.append(Path(path).name) or True,
                                pdf_to_images=lambda _path: True,
                                image_to_pdf=lambda _path: True,
                                video_to_mp3=lambda _path: True,
                            ),
                            thread_factory=ImmediateThread,
                            list_files=list_files,
                            open_file=lambda entry, _directory: opened.append(entry.name) or entry.path,
                            revalidate_file=lambda entry, _directory: entry,
                            get_favorites=lambda: get_favorite_folders(settings_path),
                            add_favorite=lambda folder: add_favorite_folder(folder, settings_path),
                            remove_favorite=lambda folder: remove_favorite_folder(folder, settings_path),
                            is_favorite=lambda folder: is_favorite_folder(folder, settings_path),
                        )
                        page.pack(fill="both", expand=True)
                        root.deiconify()
                        root.update_idletasks()
                        root.update()
                        root.withdraw()
                        initial = {
                            "scan_calls": list(scan_calls),
                            "button_state": page.favorite_button.cget("state"),
                            "menu_state": page.favorite_menu.cget("state"),
                            "menu_values": list(page.favorite_menu.cget("values")),
                        }

                        add_favorite_folder(first, settings_path)
                        page._reload_favorites()
                        page._refresh_controls()
                        one_favorite_count = len(page.favorite_menu.cget("values")) - 1
                        for folder in (second, unicode_folder, unavailable, inaccessible):
                            add_favorite_folder(folder, settings_path)
                        page._reload_favorites()
                        page._refresh_controls()
                        labels = list(page.favorite_menu.cget("values"))[1:]
                        path_by_label = dict(page._favorite_path_by_label)
                        order = [path_by_label[label] for label in labels]
                        scans_after_render = list(scan_calls)

                        first_label = next(
                            label for label, folder in path_by_label.items() if folder == str(first)
                        )
                        page._favorite_choice.set(first_label)
                        page._select_favorite(first_label)
                        page._poll_scan()
                        first_loaded = {
                            "directory": str(page.directory),
                            "favorite_text": page.favorite_button.cget("text"),
                            "snapshot": len(page.snapshot),
                        }
                        item = page.file_tree.get_children()[0]
                        page.file_tree.selection_set(item)
                        page._on_tree_selection()
                        page.extract_button.invoke()
                        page._open_selected()

                        snapshot_before_toggle = page.snapshot
                        page._toggle_current_favorite()
                        removed_current = {
                            "directory": str(page.directory),
                            "snapshot_preserved": page.snapshot == snapshot_before_toggle,
                            "still_favorite": is_favorite_folder(first, settings_path),
                            "button_text": page.favorite_button.cget("text"),
                        }
                        page._toggle_current_favorite()
                        readded_current = is_favorite_folder(first, settings_path)
                        duplicate_result = add_favorite_folder(str(first).swapcase(), settings_path)

                        page._query.set("arquivo")
                        page.filter_control.set("PDF")
                        page._on_filter_change("PDF")
                        page._sort_name.set("Mais recentes")
                        page._on_sort_change("Mais recentes")
                        generation_before = page._render_generation
                        second_label = next(
                            label for label, folder in page._favorite_path_by_label.items()
                            if folder == str(second)
                        )
                        page._favorite_choice.set(second_label)
                        page._select_favorite(second_label)
                        page._poll_scan()
                        second_loaded = {
                            "directory": str(page.directory),
                            "generation_advanced": page._render_generation > generation_before,
                            "query": page._query.get(),
                            "filter": page.filter_control.get(),
                            "sort": page._sort_name.get(),
                            "rows": len(page.file_tree.get_children()),
                        }

                        unavailable_label = next(
                            label for label, folder in page._favorite_path_by_label.items()
                            if folder == str(unavailable)
                        )
                        page._favorite_choice.set(unavailable_label)
                        page._select_favorite(unavailable_label)
                        page._poll_scan()
                        unavailable_state = {
                            "directory_preserved": page.directory == second,
                            "error": errors[-1],
                            "remove_state": page.remove_favorite_button.cget("state"),
                        }
                        scans_before_remove = len(scan_calls)
                        page._remove_selected_favorite()
                        unavailable_removed = (
                            str(unavailable) not in get_favorite_folders(settings_path)
                            and len(scan_calls) == scans_before_remove
                        )

                        inaccessible_label = next(
                            label for label, folder in page._favorite_path_by_label.items()
                            if folder == str(inaccessible)
                        )
                        page._favorite_choice.set(inaccessible_label)
                        page._select_favorite(inaccessible_label)
                        page._poll_scan()
                        inaccessible_error = errors[-1]
                        page._remove_selected_favorite()

                        current_favorites = get_favorite_folders(settings_path)
                        needed = 10 - len(current_favorites)
                        for index in range(needed):
                            add_favorite_folder(base / f"Extra {index}", settings_path)
                        page._reload_favorites()
                        page._directory = candidate
                        page._folder_text.set(f"Pasta: {candidate.name}")
                        page._refresh_controls()
                        page._toggle_current_favorite()
                        limit_state = {
                            "count": len(get_favorite_folders(settings_path)),
                            "menu_count": len(page.favorite_menu.cget("values")) - 1,
                            "warning": warnings[-1],
                            "candidate_favorite": is_favorite_folder(candidate, settings_path),
                        }

                        root.update_idletasks()
                        summary_row = page.favorite_menu.master
                        folder_row = page.favorite_button.master
                        layout = {
                            "page_width": page.winfo_width(),
                            "favorite_visible": bool(page.favorite_button.winfo_manager()),
                            "menu_visible": bool(page.favorite_menu.winfo_manager()),
                            "remove_visible": bool(page.remove_favorite_button.winfo_manager()),
                            "search_visible": bool(page.search_entry.winfo_manager()),
                            "sort_visible": bool(page.sort_menu.winfo_manager()),
                            "show_more_exists": bool(page.show_more_button.winfo_exists()),
                            "favorites_fit": (
                                page.remove_favorite_button.winfo_x()
                                + page.remove_favorite_button.winfo_width()
                                <= summary_row.winfo_width()
                            ),
                            "folder_actions_fit": (
                                page.refresh_button.winfo_x()
                                + page.refresh_button.winfo_width()
                                <= folder_row.winfo_width()
                            ),
                        }
                        result = {
                            "initial": initial,
                            "one_favorite_count": one_favorite_count,
                            "labels": labels,
                            "full_paths_exposed": any(label in order for label in labels),
                            "order_preserved": order == [
                                str(first),
                                str(second),
                                str(unicode_folder),
                                str(unavailable),
                                str(inaccessible),
                            ],
                            "scans_after_render": scans_after_render,
                            "first_loaded": first_loaded,
                            "routed": routed,
                            "opened": opened,
                            "removed_current": removed_current,
                            "readded_current": readded_current,
                            "duplicate_result": duplicate_result,
                            "second_loaded": second_loaded,
                            "unavailable_state": unavailable_state,
                            "unavailable_removed": unavailable_removed,
                            "inaccessible_error": inaccessible_error,
                            "limit_state": limit_state,
                            "layout": layout,
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
        self.assertEqual(result["initial"]["scan_calls"], [])
        self.assertEqual(result["initial"]["button_state"], "disabled")
        self.assertEqual(result["initial"]["menu_state"], "disabled")
        self.assertEqual(result["initial"]["menu_values"], ["Pastas favoritas"])
        self.assertEqual(result["one_favorite_count"], 1)
        self.assertEqual(len(result["labels"]), 5)
        self.assertTrue(result["labels"][0].startswith("Material — "))
        self.assertTrue(result["labels"][1].startswith("Material — "))
        self.assertNotEqual(result["labels"][0], result["labels"][1])
        self.assertIn("João — Educação 你好", result["labels"])
        self.assertFalse(result["full_paths_exposed"])
        self.assertTrue(result["order_preserved"])
        self.assertEqual(result["scans_after_render"], [])
        self.assertEqual(
            result["first_loaded"]["favorite_text"], "Remover dos favoritos"
        )
        self.assertEqual(result["first_loaded"]["snapshot"], 1)
        self.assertEqual(result["routed"], ["arquivo.pdf"])
        self.assertEqual(result["opened"], ["arquivo.pdf"])
        self.assertTrue(result["removed_current"]["snapshot_preserved"])
        self.assertFalse(result["removed_current"]["still_favorite"])
        self.assertEqual(result["removed_current"]["button_text"], "Favoritar pasta")
        self.assertTrue(result["readded_current"])
        self.assertEqual(result["duplicate_result"], "already_exists")
        self.assertTrue(result["second_loaded"]["generation_advanced"])
        self.assertEqual(result["second_loaded"]["query"], "arquivo")
        self.assertEqual(result["second_loaded"]["filter"], "PDF")
        self.assertEqual(result["second_loaded"]["sort"], "Mais recentes")
        self.assertEqual(result["second_loaded"]["rows"], 1)
        self.assertTrue(result["unavailable_state"]["directory_preserved"])
        self.assertEqual(
            result["unavailable_state"]["error"],
            "Esta pasta favorita não está disponível.",
        )
        self.assertEqual(result["unavailable_state"]["remove_state"], "normal")
        self.assertTrue(result["unavailable_removed"])
        self.assertEqual(
            result["inaccessible_error"], "Esta pasta favorita não está disponível."
        )
        self.assertEqual(result["limit_state"]["count"], 10)
        self.assertEqual(result["limit_state"]["menu_count"], 10)
        self.assertEqual(
            result["limit_state"]["warning"], "Você pode favoritar até 10 pastas."
        )
        self.assertFalse(result["limit_state"]["candidate_favorite"])
        self.assertGreaterEqual(result["layout"]["page_width"], 640)
        self.assertLessEqual(result["layout"]["page_width"], 660)
        self.assertTrue(
            all(value for key, value in result["layout"].items() if key != "page_width")
        )

    def test_empty_states_double_click_and_folder_choice_consistency(self) -> None:
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
                    from types import SimpleNamespace

                    import customtkinter as ctk

                    from file_preview import FilePreviewResult, PreviewKind, PreviewStatus
                    from local_files import LocalFileCategory, LocalFileEntry, LocalFilesError
                    from ui_pages import FilesPage, FilesPageActions

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    preview_started = threading.Event()
                    preview_release = threading.Event()
                    opened = []
                    errors = []
                    failed_directories = set()

                    class PreviewService:
                        def create_preview(self, entry, _directory):
                            if entry.name == "preview-lento.png":
                                preview_started.set()
                                preview_release.wait(3)
                            if entry.name == "preview-indisponivel.png":
                                return FilePreviewResult(PreviewStatus.UNAVAILABLE)
                            return FilePreviewResult(
                                PreviewStatus.SUCCESS,
                                kind=PreviewKind.IMAGE,
                                width=2,
                                height=2,
                                rgba=bytes((20, 80, 160, 255)) * 4,
                            )

                    ctk.set_appearance_mode("Light")
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        base = Path(temporary_dir)
                        empty_folder = base / "Pasta vazia"
                        first_favorite = base / "Escola A" / "Material"
                        second_favorite = base / "Escola B" / "Material"
                        manual_folder = base / "Pasta manual João 你好"
                        unavailable_favorite = base / "Favorita removida"
                        for directory in (
                            empty_folder,
                            first_favorite,
                            second_favorite,
                            manual_folder,
                        ):
                            directory.mkdir(parents=True)

                        def entry(directory, name, category):
                            return LocalFileEntry(
                                directory / name,
                                category,
                                1024,
                                1_700_000_000.0,
                            )

                        entries_by_directory = {
                            empty_folder: (),
                            first_favorite: (
                                entry(first_favorite, "abrir.pdf", LocalFileCategory.PDF),
                                entry(
                                    first_favorite,
                                    "arquivo-removido.pdf",
                                    LocalFileCategory.PDF,
                                ),
                                entry(
                                    first_favorite,
                                    "preview-indisponivel.png",
                                    LocalFileCategory.IMAGE,
                                ),
                                entry(
                                    first_favorite,
                                    "preview-lento.png",
                                    LocalFileCategory.IMAGE,
                                ),
                            ),
                            second_favorite: (
                                entry(second_favorite, "segundo.pdf", LocalFileCategory.PDF),
                            ),
                            manual_folder: (
                                entry(manual_folder, "manual.pdf", LocalFileCategory.PDF),
                            ),
                        }
                        favorites = (
                            str(first_favorite),
                            str(second_favorite),
                            *(str(base / f"Favorita {index}") for index in range(8)),
                        )

                        def list_files(directory):
                            directory = Path(directory)
                            if directory in failed_directories:
                                raise LocalFilesError(
                                    "A pasta selecionada não está disponível."
                                )
                            if directory == unavailable_favorite:
                                raise LocalFilesError("detalhe técnico não público")
                            return entries_by_directory[directory]

                        def open_file(selected, _directory):
                            if selected.name == "arquivo-removido.pdf":
                                raise LocalFilesError(
                                    "O arquivo selecionado não está mais disponível."
                                )
                            opened.append(selected.name)
                            return selected.path

                        def revalidate(selected, _directory):
                            if selected.name == "arquivo-removido.pdf":
                                raise LocalFilesError(
                                    "O arquivo selecionado não está mais disponível."
                                )
                            return selected

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=lambda _message: None,
                                show_error=errors.append,
                                extract_pages=lambda _path: True,
                                pdf_to_images=lambda _path: True,
                                image_to_pdf=lambda _path: True,
                                video_to_mp3=lambda _path: True,
                            ),
                            thread_factory=ImmediateThread,
                            list_files=list_files,
                            open_file=open_file,
                            revalidate_file=revalidate,
                            preview_service=PreviewService(),
                            get_favorites=lambda: favorites,
                        )
                        page.pack(fill="both", expand=True)
                        root.geometry("860x600")
                        root.deiconify()
                        root.update_idletasks()
                        root.update()

                        def spin_until(predicate, timeout=3):
                            deadline = time.monotonic() + timeout
                            while time.monotonic() < deadline:
                                root.update_idletasks()
                                root.update()
                                if predicate():
                                    return True
                                time.sleep(0.005)
                            return False

                        def load(directory, *, replace=True, unavailable_error=None):
                            page._start_scan(
                                directory,
                                replace_directory=replace,
                                unavailable_error=unavailable_error,
                            )
                            page._poll_scan()
                            root.update_idletasks()
                            root.update()

                        def item_for(name):
                            return next(
                                item
                                for item in page.file_tree.get_children()
                                if page._entry_by_item[item].name == name
                            )

                        def select(name):
                            item = item_for(name)
                            page.file_tree.selection_set(item)
                            page._on_tree_selection()
                            return item

                        def double_click(item):
                            root.update_idletasks()
                            bounds = page.file_tree.bbox(item)
                            return page._on_tree_double_click(
                                SimpleNamespace(y=bounds[1] + max(1, bounds[3] // 2))
                            )

                        initial = {
                            "status": page._status.get(),
                            "details": page._detail_heading.get(),
                            "favorites": len(page.favorite_menu.cget("values")) - 1,
                        }

                        load(empty_folder)
                        empty_status = page._status.get()

                        load(first_favorite)
                        no_selection = page._detail_heading.get()
                        first_label = page._favorite_choice.get()

                        page._query.set("resultado inexistente")
                        page._apply_search_now()
                        search_status = page._status.get()

                        page._query.set("")
                        page.filter_control.set("Vídeos")
                        page._on_filter_change("Vídeos")
                        filter_status = page._status.get()

                        page.filter_control.set("Todos")
                        page._on_filter_change("Todos")
                        unavailable_item = select("preview-indisponivel.png")
                        preview_unavailable = spin_until(
                            lambda: page._preview_state.value == "unavailable"
                        )
                        preview_unavailable_text = page._preview_text.get()
                        opened_after_single_click = list(opened)

                        open_item = item_for("abrir.pdf")
                        open_result = double_click(open_item)
                        open_details = page._detail_heading.get()
                        invalid_result = page._on_tree_double_click(
                            SimpleNamespace(y=-20)
                        )
                        opened_after_invalid = list(opened)

                        removed_item = item_for("arquivo-removido.pdf")
                        removed_result = double_click(removed_item)
                        removed_names = [candidate.name for candidate in page.snapshot]
                        removed_status = page._status.get()

                        slow_item = select("preview-lento.png")
                        preview_active = spin_until(preview_started.is_set)
                        generation_before_open = page._preview_generation
                        slow_open_result = double_click(slow_item)
                        opened_while_loading = opened[-1] == "preview-lento.png"
                        generation_after_open = page._preview_generation
                        preview_release.set()
                        preview_ready = spin_until(
                            lambda: page._preview_state.value == "available"
                        )

                        load(second_favorite)
                        second_label = page._favorite_choice.get()
                        load(manual_folder)
                        manual_choice = page._favorite_choice.get()

                        load(
                            unavailable_favorite,
                            unavailable_error="Esta pasta favorita não está disponível.",
                        )
                        favorite_unavailable = {
                            "status": page._status.get(),
                            "directory_preserved": page.directory == manual_folder,
                        }

                        failed_directories.add(manual_folder)
                        page._refresh_directory()
                        page._poll_scan()
                        folder_unavailable = {
                            "status": page._status.get(),
                            "directory_cleared": page.directory is None,
                            "favorite_choice": page._favorite_choice.get(),
                        }

                        public_messages = (
                            initial["status"],
                            initial["details"],
                            empty_status,
                            no_selection,
                            search_status,
                            filter_status,
                            preview_unavailable_text,
                            removed_status,
                            favorite_unavailable["status"],
                            folder_unavailable["status"],
                        )
                        result = {
                            "initial": initial,
                            "empty_status": empty_status,
                            "no_selection": no_selection,
                            "search_status": search_status,
                            "filter_status": filter_status,
                            "preview_unavailable": preview_unavailable,
                            "preview_unavailable_text": preview_unavailable_text,
                            "opened_after_single_click": opened_after_single_click,
                            "unavailable_item_selected": bool(unavailable_item),
                            "open_result": open_result,
                            "open_details": open_details,
                            "invalid_result": invalid_result,
                            "opened_after_invalid": opened_after_invalid,
                            "removed_result": removed_result,
                            "removed_absent": "arquivo-removido.pdf" not in removed_names,
                            "removed_status": removed_status,
                            "preview_active": preview_active,
                            "slow_open_result": slow_open_result,
                            "opened_while_loading": opened_while_loading,
                            "generation_preserved": (
                                generation_before_open == generation_after_open
                            ),
                            "preview_ready": preview_ready,
                            "favorite_labels": [first_label, second_label],
                            "manual_choice": manual_choice,
                            "favorite_unavailable": favorite_unavailable,
                            "folder_unavailable": folder_unavailable,
                            "private_details_hidden": all(
                                str(base) not in message
                                and "detalhe técnico" not in message
                                for message in public_messages
                            ),
                            "errors": errors,
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
            result["initial"]["status"], "Escolha uma pasta para ver seus arquivos."
        )
        self.assertEqual(result["initial"]["details"], "Nenhum arquivo selecionado")
        self.assertEqual(result["initial"]["favorites"], 10)
        self.assertEqual(
            result["empty_status"],
            "Nenhum arquivo compatível nesta pasta. Escolha outra pasta.",
        )
        self.assertEqual(result["no_selection"], "Nenhum arquivo selecionado")
        self.assertEqual(
            result["search_status"],
            "Nenhum arquivo corresponde à busca. Tente outro termo.",
        )
        self.assertEqual(
            result["filter_status"],
            "Nenhum arquivo neste filtro. Escolha outro filtro.",
        )
        self.assertTrue(result["preview_unavailable"])
        self.assertEqual(
            result["preview_unavailable_text"],
            "Não foi possível mostrar a prévia. Tente abrir o arquivo.",
        )
        self.assertEqual(result["opened_after_single_click"], [])
        self.assertTrue(result["unavailable_item_selected"])
        self.assertEqual(result["open_result"], "break")
        self.assertEqual(result["open_details"], "abrir.pdf")
        self.assertEqual(result["invalid_result"], "break")
        self.assertEqual(result["opened_after_invalid"], ["abrir.pdf"])
        self.assertEqual(result["removed_result"], "break")
        self.assertTrue(result["removed_absent"])
        self.assertIn("não está mais disponível", result["removed_status"])
        self.assertTrue(result["preview_active"])
        self.assertEqual(result["slow_open_result"], "break")
        self.assertTrue(result["opened_while_loading"])
        self.assertTrue(result["generation_preserved"])
        self.assertTrue(result["preview_ready"])
        self.assertNotEqual(*result["favorite_labels"])
        self.assertTrue(
            all(label.startswith("Material — ") for label in result["favorite_labels"])
        )
        self.assertEqual(result["manual_choice"], "Pastas favoritas")
        self.assertEqual(
            result["favorite_unavailable"]["status"],
            "Esta pasta favorita não está disponível.",
        )
        self.assertTrue(result["favorite_unavailable"]["directory_preserved"])
        self.assertIn("não está disponível", result["folder_unavailable"]["status"])
        self.assertTrue(result["folder_unavailable"]["directory_cleared"])
        self.assertEqual(
            result["folder_unavailable"]["favorite_choice"], "Pastas favoritas"
        )
        self.assertTrue(result["private_details_hidden"])
        self.assertGreaterEqual(len(result["errors"]), 3)

    def test_async_preview_states_debounce_stale_lifecycle_and_layout(self) -> None:
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

                    from file_preview import (
                        FilePreviewResult,
                        PreviewKind,
                        PreviewStatus,
                    )
                    from local_files import LocalFileCategory, LocalFileEntry
                    from ui_pages import FilesPage, FilesPageActions

                    main_thread = threading.get_ident()
                    preview_threads = []
                    preview_worker_names = []
                    tk_image_threads = []
                    calls = []
                    routed = []
                    opened = []
                    revealed = []
                    responsive = []
                    slow_a_started = threading.Event()
                    slow_a_release = threading.Event()
                    slow_z_started = threading.Event()
                    slow_z_release = threading.Event()
                    folder_started = threading.Event()
                    folder_release = threading.Event()
                    refresh_started = threading.Event()
                    refresh_release = threading.Event()
                    close_started = threading.Event()
                    close_release = threading.Event()

                    def success(color, kind=PreviewKind.IMAGE, size=(4, 2)):
                        return FilePreviewResult(
                            PreviewStatus.SUCCESS,
                            kind=kind,
                            width=size[0],
                            height=size[1],
                            rgba=bytes(color) * (size[0] * size[1]),
                        )

                    class PreviewService:
                        def create_preview(self, entry, directory):
                            preview_threads.append(threading.get_ident())
                            calls.append((entry.name, Path(directory).name))
                            if entry.name == "slow-a.png":
                                slow_a_started.set()
                                slow_a_release.wait(3)
                                return success((220, 10, 10, 255))
                            if entry.name == "slow-z.png":
                                slow_z_started.set()
                                slow_z_release.wait(3)
                                return success((10, 20, 230, 255))
                            if entry.name == "folder-slow.png":
                                folder_started.set()
                                folder_release.wait(3)
                                return success((230, 20, 20, 255))
                            if entry.name == "refresh-slow.png":
                                refresh_started.set()
                                refresh_release.wait(3)
                                return success((230, 20, 20, 255))
                            if entry.name == "close-slow.png":
                                close_started.set()
                                close_release.wait(3)
                                return success((230, 20, 20, 255))
                            if entry.name == "indisponivel.png":
                                return FilePreviewResult(PreviewStatus.UNAVAILABLE)
                            if entry.name == "grande.png":
                                return FilePreviewResult(PreviewStatus.TOO_LARGE)
                            if entry.name == "erro.png":
                                return FilePreviewResult(PreviewStatus.ERROR)
                            if entry.category is LocalFileCategory.PDF:
                                return success(
                                    (240, 240, 240, 255),
                                    kind=PreviewKind.PDF_PAGE,
                                    size=(2, 4),
                                )
                            return success((20, 180, 40, 255))

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    def preview_thread_factory(**kwargs):
                        preview_worker_names.append(kwargs["name"])
                        return threading.Thread(**kwargs)

                    def entry(directory, name, category):
                        return LocalFileEntry(
                            directory / name,
                            category,
                            1024,
                            1_700_000_000.0,
                        )

                    ctk.set_appearance_mode("Light")
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        base = Path(temporary_dir)
                        first = base / "Pasta A"
                        favorite = base / "Favorita João 你好"
                        first.mkdir()
                        favorite.mkdir()
                        first_entries = (
                            entry(first, "foto.png", LocalFileCategory.IMAGE),
                            entry(first, "documento.pdf", LocalFileCategory.PDF),
                            entry(first, "audio.mp3", LocalFileCategory.AUDIO),
                            entry(first, "indisponivel.png", LocalFileCategory.IMAGE),
                            entry(first, "grande.png", LocalFileCategory.IMAGE),
                            entry(first, "erro.png", LocalFileCategory.IMAGE),
                            entry(first, "slow-a.png", LocalFileCategory.IMAGE),
                            entry(first, "slow-z.png", LocalFileCategory.IMAGE),
                            *(entry(first, f"rapido-{index}.png", LocalFileCategory.IMAGE)
                              for index in range(20)),
                            *(entry(first, f"zz-carga-{index:04d}.png", LocalFileCategory.IMAGE)
                              for index in range(1_200)),
                        )
                        favorite_entries = (
                            entry(favorite, "favorita.png", LocalFileCategory.IMAGE),
                            entry(
                                favorite,
                                "material escolar com nome muito longo para o painel de detalhes.png",
                                LocalFileCategory.IMAGE,
                            ),
                            entry(favorite, "folder-slow.png", LocalFileCategory.IMAGE),
                            entry(favorite, "refresh-slow.png", LocalFileCategory.IMAGE),
                            entry(favorite, "close-slow.png", LocalFileCategory.IMAGE),
                        )
                        entries_by_directory = {
                            first: first_entries,
                            favorite: favorite_entries,
                        }

                        def list_files(directory):
                            return entries_by_directory[Path(directory)]

                        def route(path):
                            routed.append(Path(path).name)
                            return True

                        page = FilesPage(
                            root,
                            actions=FilesPageActions(
                                show_warning=lambda _message: None,
                                show_error=lambda _message: None,
                                extract_pages=route,
                                pdf_to_images=route,
                                image_to_pdf=route,
                                video_to_mp3=route,
                            ),
                            thread_factory=ImmediateThread,
                            list_files=list_files,
                            open_file=lambda selected, _directory: (
                                opened.append(selected.name) or selected.path
                            ),
                            reveal_file=lambda selected, _directory: (
                                revealed.append(selected.name) or selected.path
                            ),
                            revalidate_file=lambda selected, _directory: selected,
                            preview_service=PreviewService(),
                            preview_thread_factory=preview_thread_factory,
                        )
                        page.pack(fill="both", expand=True)

                        real_ctk_image = ctk.CTkImage

                        def tracked_ctk_image(*args, **kwargs):
                            tk_image_threads.append(threading.get_ident())
                            return real_ctk_image(*args, **kwargs)

                        def spin_until(predicate, timeout=3):
                            deadline = time.monotonic() + timeout
                            while time.monotonic() < deadline:
                                root.update_idletasks()
                                root.update()
                                if predicate():
                                    return True
                                time.sleep(0.005)
                            return False

                        def select(name):
                            item = next(
                                item
                                for item in page.file_tree.get_children()
                                if page._entry_by_item[item].name == name
                            )
                            page.file_tree.selection_set(item)
                            page._on_tree_selection()

                        def load(directory, replace=True):
                            page._start_scan(directory, replace_directory=replace)
                            page._poll_scan()
                            root.update_idletasks()

                        with patch("ui_pages.ctk.CTkImage", side_effect=tracked_ctk_image):
                            root.geometry("860x600")
                            root.deiconify()
                            load(first)
                            empty = {
                                "state": page._preview_state.value,
                                "text": page._preview_text.get(),
                            }

                            select("foto.png")
                            loading = {
                                "state": page._preview_state.value,
                                "text": page._preview_text.get(),
                                "open": page.open_button.cget("state"),
                                "handoff": page.image_pdf_button.cget("state"),
                            }
                            image_ready = spin_until(
                                lambda: page._preview_state.value == "available"
                            )
                            image_pixel = page._preview_pil_image.getpixel((0, 0))
                            old_image = page._preview_pil_image

                            select("documento.pdf")
                            pdf_ready = spin_until(
                                lambda: page._preview_state.value == "available"
                            )
                            pdf_size = page._preview_pil_image.size
                            try:
                                old_image.getbbox()
                                old_image_closed = False
                            except ValueError:
                                old_image_closed = True

                            calls_before_unsupported = len(calls)
                            select("audio.mp3")
                            unsupported = {
                                "state": page._preview_state.value,
                                "text": page._preview_text.get(),
                                "service_not_called": len(calls) == calls_before_unsupported,
                            }

                            status_states = {}
                            for name in ("indisponivel.png", "grande.png", "erro.png"):
                                select(name)
                                spin_until(lambda: page._preview_state.value != "loading")
                                status_states[name] = {
                                    "state": page._preview_state.value,
                                    "text": page._preview_text.get(),
                                    "path_hidden": str(base) not in page._preview_text.get(),
                                }

                            calls_before_debounce = len(calls)
                            for index in range(20):
                                select(f"rapido-{index}.png")
                            debounce_ready = spin_until(
                                lambda: page._preview_state.value == "available"
                            )
                            debounce_calls = calls[calls_before_debounce:]

                            page._show_more()
                            expanded_render_ready = spin_until(
                                lambda: len(page.file_tree.get_children()) == 1_000
                            )
                            calls_before_stress = len(calls)
                            select("slow-a.png")
                            slow_a_active = spin_until(slow_a_started.is_set)
                            root.after(1, lambda: responsive.append("tick"))
                            ui_responsive = spin_until(lambda: bool(responsive), timeout=1)
                            page._sort_name.set("Mais recentes")
                            page._on_sort_change("Mais recentes")
                            page.filter_control.set("Imagens")
                            page._on_filter_change("Imagens")
                            page._query.set("slow")
                            page._apply_search_now()
                            combined_render_ready = spin_until(
                                lambda: len(page.file_tree.get_children()) == 2
                            )
                            select("slow-z.png")
                            queued_latest_only = spin_until(
                                lambda: page._preview_requests.qsize() == 1
                            )
                            max_request_queue = page._preview_requests.qsize()
                            slow_a_release.set()
                            slow_z_active = spin_until(slow_z_started.is_set)
                            stale_not_applied = (
                                page._preview_state.value == "loading"
                                and page._preview_pil_image is None
                            )
                            slow_z_release.set()
                            latest_ready = spin_until(
                                lambda: page._preview_state.value == "available"
                            )
                            latest_pixel = page._preview_pil_image.getpixel((0, 0))
                            stress_calls = calls[calls_before_stress:]

                            page._query.set("")
                            page.filter_control.set("Todos")
                            page._on_filter_change("Todos")
                            page._sort_name.set("Nome")
                            page._on_sort_change("Nome")
                            spin_until(
                                lambda: len(page.file_tree.get_children()) == 500
                            )

                            page._favorite_path_by_label = {
                                "Favorita": str(favorite)
                            }
                            page._favorite_choice.set("Favorita")
                            select("slow-a.png")
                            spin_until(slow_a_started.is_set)
                            page._select_favorite("Favorita")
                            page._poll_scan()
                            favorite_rendered = spin_until(
                                lambda: any(
                                    page.file_tree.item(item, "values")[0]
                                    == "favorita.png"
                                    for item in page.file_tree.get_children()
                                )
                            )
                            favorite_switch = {
                                "directory": page.directory.name,
                                "state": page._preview_state.value,
                                "selected": page._detail_name.get(),
                            }
                            select("favorita.png")
                            favorite_ready = spin_until(
                                lambda: page._preview_state.value == "available"
                            )

                            select("folder-slow.png")
                            folder_active = spin_until(folder_started.is_set)
                            page._refresh_directory()
                            page._poll_scan()
                            refresh_preserved = (
                                page._preview_state.value == "loading"
                                and page._selected_entry is not None
                                and page._selected_entry.name == "folder-slow.png"
                            )
                            folder_release.set()
                            spin_until(lambda: page._preview_results.empty())

                            select("refresh-slow.png")
                            refresh_active = spin_until(refresh_started.is_set)
                            page.filter_control.set("PDF")
                            page._on_filter_change("PDF")
                            filter_cleared = (
                                page._preview_state.value == "empty"
                                and page._selected_entry is None
                            )
                            refresh_release.set()
                            spin_until(lambda: page._preview_results.empty())

                            page.filter_control.set("Todos")
                            page._on_filter_change("Todos")
                            select("favorita.png")
                            page._open_selected()
                            page._reveal_selected()
                            page.image_pdf_button.invoke()

                            select(
                                "material escolar com nome muito longo para o painel de detalhes.png"
                            )
                            spin_until(
                                lambda: page._preview_state.value == "available"
                            )
                            page.apply_theme("Escuro")
                            dark_state = page._preview_state.value
                            page.apply_theme("Claro")
                            light_state = page._preview_state.value
                            root.update_idletasks()
                            layout = {
                                "page_height": page.winfo_height(),
                                "page_width": page.winfo_width(),
                                "tree_height": page.file_tree.winfo_height(),
                                "context_right": (
                                    page.context_frame.winfo_x()
                                    + page.context_frame.winfo_width()
                                ),
                                "context_bottom": (
                                    page.context_frame.winfo_y()
                                    + page.context_frame.winfo_height()
                                ),
                                "status_y": page.status_frame.winfo_y(),
                                "status_bottom": (
                                    page.status_frame.winfo_y()
                                    + page.status_frame.winfo_height()
                                ),
                                "preview_width": page.preview_frame.winfo_width(),
                                "preview_height": page.preview_frame.winfo_height(),
                                "horizontal_scrollbar": any(
                                    child.winfo_class() == "TScrollbar"
                                    and str(child.cget("orient")) == "horizontal"
                                    for child in page.file_list_frame.winfo_children()
                                ),
                            }

                            select("close-slow.png")
                            close_active = spin_until(close_started.is_set)
                            page.close()
                            close_state = {
                                "closed": page._closed,
                                "debounce_cancelled": page._preview_after_id is None,
                                "poll_cancelled": page._preview_poll_after_id is None,
                                "worker_released": page._preview_worker is None,
                                "image_released": page._preview_pil_image is None,
                            }
                            close_release.set()
                            time.sleep(0.05)
                            root.update_idletasks()

                        result = {
                            "empty": empty,
                            "loading": loading,
                            "image_ready": image_ready,
                            "image_pixel": image_pixel,
                            "pdf_ready": pdf_ready,
                            "pdf_size": pdf_size,
                            "old_image_closed": old_image_closed,
                            "unsupported": unsupported,
                            "status_states": status_states,
                            "debounce_ready": debounce_ready,
                            "debounce_calls": debounce_calls,
                            "expanded_render_ready": expanded_render_ready,
                            "slow_a_active": slow_a_active,
                            "ui_responsive": ui_responsive,
                            "combined_render_ready": combined_render_ready,
                            "queued_latest_only": queued_latest_only,
                            "max_request_queue": max_request_queue,
                            "slow_z_active": slow_z_active,
                            "stale_not_applied": stale_not_applied,
                            "latest_ready": latest_ready,
                            "latest_pixel": latest_pixel,
                            "stress_calls": stress_calls,
                            "favorite_rendered": favorite_rendered,
                            "favorite_switch": favorite_switch,
                            "favorite_ready": favorite_ready,
                            "folder_active": folder_active,
                            "refresh_preserved": refresh_preserved,
                            "refresh_active": refresh_active,
                            "filter_cleared": filter_cleared,
                            "opened": opened,
                            "revealed": revealed,
                            "routed": routed,
                            "preview_threads": preview_threads,
                            "preview_worker_names": preview_worker_names,
                            "tk_image_threads": tk_image_threads,
                            "result_queue_bounded": page._preview_results.qsize() <= 1,
                            "dark_state": dark_state,
                            "light_state": light_state,
                            "layout": layout,
                            "close_active": close_active,
                            "close_state": close_state,
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

        self.assertEqual(result["empty"]["state"], "empty")
        self.assertIn("Selecione", result["empty"]["text"])
        self.assertEqual(result["loading"]["state"], "loading")
        self.assertEqual(result["loading"]["text"], "Carregando prévia...")
        self.assertEqual(result["loading"]["open"], "normal")
        self.assertEqual(result["loading"]["handoff"], "normal")
        self.assertTrue(result["image_ready"])
        self.assertEqual(result["image_pixel"], [20, 180, 40, 255])
        self.assertTrue(result["pdf_ready"])
        self.assertEqual(result["pdf_size"], [2, 4])
        self.assertTrue(result["old_image_closed"])
        self.assertEqual(result["unsupported"]["state"], "unsupported")
        self.assertIn("não disponível", result["unsupported"]["text"])
        self.assertTrue(result["unsupported"]["service_not_called"])
        self.assertEqual(
            result["status_states"]["indisponivel.png"]["text"],
            "Não foi possível mostrar a prévia. Tente abrir o arquivo.",
        )
        self.assertEqual(
            result["status_states"]["grande.png"]["text"],
            "Arquivo grande demais para gerar a prévia.",
        )
        self.assertEqual(result["status_states"]["erro.png"]["state"], "error")
        self.assertTrue(
            all(state["path_hidden"] for state in result["status_states"].values())
        )
        self.assertTrue(result["debounce_ready"])
        self.assertEqual(
            [call[0] for call in result["debounce_calls"]], ["rapido-19.png"]
        )
        self.assertTrue(result["expanded_render_ready"])
        self.assertTrue(result["slow_a_active"])
        self.assertTrue(result["ui_responsive"])
        self.assertTrue(result["combined_render_ready"])
        self.assertTrue(result["queued_latest_only"])
        self.assertLessEqual(result["max_request_queue"], 1)
        self.assertTrue(result["slow_z_active"])
        self.assertTrue(result["stale_not_applied"])
        self.assertTrue(result["latest_ready"])
        self.assertEqual(result["latest_pixel"], [10, 20, 230, 255])
        self.assertEqual(
            [call[0] for call in result["stress_calls"]],
            ["slow-a.png", "slow-z.png"],
        )
        self.assertTrue(result["favorite_rendered"])
        self.assertEqual(result["favorite_switch"]["directory"], "Favorita João 你好")
        self.assertEqual(result["favorite_switch"]["state"], "empty")
        self.assertEqual(result["favorite_switch"]["selected"], "—")
        self.assertTrue(result["favorite_ready"])
        self.assertTrue(result["folder_active"])
        self.assertTrue(result["refresh_preserved"])
        self.assertTrue(result["refresh_active"])
        self.assertTrue(result["filter_cleared"])
        self.assertEqual(result["opened"], ["favorita.png"])
        self.assertEqual(result["revealed"], ["favorita.png"])
        self.assertEqual(result["routed"], ["favorita.png"])
        self.assertEqual(len(result["preview_worker_names"]), 1)
        self.assertEqual(
            result["preview_worker_names"], ["edudownloader-file-preview-worker"]
        )
        self.assertTrue(result["preview_threads"])
        self.assertTrue(
            all(
                thread != result["tk_image_threads"][0]
                for thread in result["preview_threads"]
            )
        )
        self.assertTrue(
            all(
                thread == result["tk_image_threads"][0]
                for thread in result["tk_image_threads"]
            )
        )
        self.assertTrue(result["result_queue_bounded"])
        self.assertEqual(result["dark_state"], "available")
        self.assertEqual(result["light_state"], "available")
        self.assertGreaterEqual(result["layout"]["tree_height"], 110)
        self.assertGreaterEqual(result["layout"]["preview_width"], 248)
        self.assertGreaterEqual(result["layout"]["preview_height"], 208)
        self.assertLessEqual(
            result["layout"]["context_right"], result["layout"]["page_width"]
        )
        self.assertLessEqual(
            result["layout"]["context_bottom"], result["layout"]["status_y"]
        )
        self.assertLessEqual(
            result["layout"]["status_bottom"], result["layout"]["page_height"]
        )
        self.assertFalse(result["layout"]["horizontal_scrollbar"])
        self.assertTrue(result["close_active"])
        self.assertTrue(all(result["close_state"].values()))


if __name__ == "__main__":
    unittest.main()
