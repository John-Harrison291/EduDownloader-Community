"""Testes do catálogo local não visual e de suas fronteiras Windows."""

from __future__ import annotations

import os
import stat
import tempfile
import unicodedata
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import local_files
from local_files import (
    LocalFileCategory,
    LocalFileEntry,
    LocalFilesError,
    LocalFileSort,
    classify_local_file,
    filter_local_files,
    list_local_files,
    open_local_file,
    project_local_files,
    require_distinct_output_path,
    reveal_local_file,
    revalidate_local_file,
    validate_local_output_path,
    validate_local_regular_file,
    windows_paths_equivalent,
)


class LocalFileClassificationTests(unittest.TestCase):
    def test_recognized_suffixes_have_expected_categories(self) -> None:
        expected = {
            ".docx": LocalFileCategory.DOCUMENT,
            ".doc": LocalFileCategory.DOCUMENT,
            ".odt": LocalFileCategory.DOCUMENT,
            ".txt": LocalFileCategory.DOCUMENT,
            ".pdf": LocalFileCategory.PDF,
            ".jpg": LocalFileCategory.IMAGE,
            ".jpeg": LocalFileCategory.IMAGE,
            ".png": LocalFileCategory.IMAGE,
            ".mp4": LocalFileCategory.VIDEO,
            ".mkv": LocalFileCategory.VIDEO,
            ".webm": LocalFileCategory.VIDEO,
            ".avi": LocalFileCategory.VIDEO,
            ".mov": LocalFileCategory.VIDEO,
            ".m4v": LocalFileCategory.VIDEO,
            ".mp3": LocalFileCategory.AUDIO,
            ".wav": LocalFileCategory.AUDIO,
            ".m4a": LocalFileCategory.AUDIO,
            ".aac": LocalFileCategory.AUDIO,
            ".flac": LocalFileCategory.AUDIO,
            ".ogg": LocalFileCategory.AUDIO,
            ".wma": LocalFileCategory.AUDIO,
        }
        for suffix, category in expected.items():
            with self.subTest(suffix=suffix):
                self.assertIs(classify_local_file(f"atividade{suffix}"), category)

    def test_classification_is_case_insensitive_and_omits_unknown(self) -> None:
        self.assertIs(classify_local_file("ATIVIDADE.PDF"), LocalFileCategory.PDF)
        self.assertIs(classify_local_file("FOTO.JpEg"), LocalFileCategory.IMAGE)
        self.assertIs(
            classify_local_file("Plano de ação 你好.DoCx"),
            LocalFileCategory.DOCUMENT,
        )
        self.assertIs(classify_local_file("LEGADO.DOC"), LocalFileCategory.DOCUMENT)
        self.assertIs(classify_local_file("TEXTO.TxT"), LocalFileCategory.DOCUMENT)
        self.assertIsNone(classify_local_file("nao-suportado.rtf"))
        self.assertIsNone(classify_local_file("programa.exe"))
        self.assertIsNone(classify_local_file("sem-extensao"))


class LocalFileListingTests(unittest.TestCase):
    def test_lists_only_direct_recognized_files_with_metadata_and_natural_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            nested = directory / "subpasta"
            nested.mkdir()
            (nested / "interno.pdf").write_bytes(b"interno")
            (directory / "ignorado.exe").write_bytes(b"nao acessar")
            (directory / "arquivo10.pdf").write_bytes(b"dez")
            (directory / "arquivo2.PDF").write_bytes(b"dois")
            unicode_file = directory / "vídeo com espaço ção.MP4"
            unicode_file.write_bytes(b"video")
            document = directory / "Aula João 你好.DOCX"
            document.write_bytes(b"catalogar-sem-abrir")

            entries = list_local_files(directory)

        self.assertEqual(
            [entry.name for entry in entries],
            [
                "arquivo2.PDF",
                "arquivo10.pdf",
                "Aula João 你好.DOCX",
                "vídeo com espaço ção.MP4",
            ],
        )
        self.assertEqual(entries[0].size_bytes, 4)
        self.assertGreater(entries[0].modified_timestamp, 0)
        self.assertIs(entries[0].category, LocalFileCategory.PDF)
        self.assertIs(entries[2].category, LocalFileCategory.DOCUMENT)
        self.assertIs(entries[3].category, LocalFileCategory.VIDEO)
        self.assertNotIn("interno.pdf", [entry.name for entry in entries])
        self.assertNotIn("ignorado.exe", [entry.name for entry in entries])

    def test_empty_folder_returns_empty_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            self.assertEqual(list_local_files(temporary_dir), ())

    def test_snapshot_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "atividade.pdf"
            path.write_bytes(b"pdf")
            entries = list_local_files(temporary_dir)

        self.assertIsInstance(entries, tuple)
        with self.assertRaises(AttributeError):
            entries[0].size_bytes = 9  # type: ignore[misc]

    def test_symlink_is_ignored_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            source = directory / "origem.pdf"
            link = directory / "atalho.pdf"
            source.write_bytes(b"pdf")
            try:
                link.symlink_to(source)
            except OSError as error:
                self.skipTest(f"symlink indisponível: {type(error).__name__}")

            entries = list_local_files(directory)

        self.assertEqual([entry.name for entry in entries], ["origem.pdf"])

    def test_simulated_reparse_entry_is_ignored(self) -> None:
        metadata = SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_size=10,
            st_mtime=20.0,
            st_file_attributes=local_files._FILE_ATTRIBUTE_REPARSE_POINT,
        )
        candidate = Mock()
        candidate.name = "junction.pdf"
        candidate.is_file.return_value = True
        candidate.stat.return_value = metadata
        scanned = MagicMock()
        scanned.__enter__ = Mock(return_value=iter([candidate]))
        scanned.__exit__ = Mock(return_value=False)

        with (
            tempfile.TemporaryDirectory() as temporary_dir,
            patch("local_files.os.scandir", return_value=scanned),
        ):
            self.assertEqual(list_local_files(temporary_dir), ())
        candidate.is_file.assert_called_once_with(follow_symlinks=False)
        candidate.stat.assert_called_once_with(follow_symlinks=False)


class LocalFileFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = (
            LocalFileEntry(
                Path("Plano João 你好.DOCX"), LocalFileCategory.DOCUMENT, 5, 5.0
            ),
            LocalFileEntry(Path("Árvore2.PDF"), LocalFileCategory.PDF, 1, 1.0),
            LocalFileEntry(Path("foto ação.PNG"), LocalFileCategory.IMAGE, 2, 2.0),
            LocalFileEntry(Path("aula.mp4"), LocalFileCategory.VIDEO, 3, 3.0),
            LocalFileEntry(Path("trilha.mp3"), LocalFileCategory.AUDIO, 4, 4.0),
        )

    def test_empty_filter_means_all_and_preserves_order(self) -> None:
        self.assertEqual(filter_local_files(self.entries), self.entries)

    def test_every_category_filters_independently(self) -> None:
        for category, expected in (
            (LocalFileCategory.DOCUMENT, "Plano João 你好.DOCX"),
            (LocalFileCategory.PDF, "Árvore2.PDF"),
            (LocalFileCategory.IMAGE, "foto ação.PNG"),
            (LocalFileCategory.VIDEO, "aula.mp4"),
            (LocalFileCategory.AUDIO, "trilha.mp3"),
        ):
            with self.subTest(category=category):
                result = filter_local_files(self.entries, category)
                self.assertEqual([entry.name for entry in result], [expected])

    def test_query_is_case_insensitive_unicode_nfc_substring(self) -> None:
        decomposed = unicodedata.normalize("NFD", "AÇÃO")
        result = filter_local_files(self.entries, query=decomposed)
        self.assertEqual([entry.name for entry in result], ["foto ação.PNG"])

    def test_category_and_query_are_combined(self) -> None:
        result = filter_local_files(self.entries, LocalFileCategory.PDF, query="árVORE")
        self.assertEqual([entry.name for entry in result], ["Árvore2.PDF"])
        self.assertEqual(
            filter_local_files(self.entries, LocalFileCategory.IMAGE, query="árVORE"),
            (),
        )

    def test_filter_does_not_read_filesystem(self) -> None:
        with patch("local_files.os.scandir", side_effect=AssertionError):
            self.assertEqual(
                filter_local_files(self.entries, query="aula")[0].name, "aula.mp4"
            )


class LocalFileProjectionTests(unittest.TestCase):
    @staticmethod
    def _entries(count: int) -> tuple[LocalFileEntry, ...]:
        categories = tuple(LocalFileCategory)
        suffixes = {
            LocalFileCategory.DOCUMENT: "docx",
            LocalFileCategory.PDF: "pdf",
            LocalFileCategory.IMAGE: "png",
            LocalFileCategory.VIDEO: "mp4",
            LocalFileCategory.AUDIO: "mp3",
        }
        return tuple(
            LocalFileEntry(
                Path(f"arquivo{index}.{suffixes[categories[index % len(categories)]]}"),
                categories[index % len(categories)],
                index + 1,
                float(index // 2),
            )
            for index in range(count)
        )

    def test_name_order_preserves_natural_sort(self) -> None:
        entries = (
            LocalFileEntry(Path("aula10.pdf"), LocalFileCategory.PDF, 1, 3.0),
            LocalFileEntry(Path("aula2.pdf"), LocalFileCategory.PDF, 1, 2.0),
            LocalFileEntry(Path("aula1.pdf"), LocalFileCategory.PDF, 1, 1.0),
        )
        result = project_local_files(entries, sort=LocalFileSort.NAME)
        self.assertEqual(
            [entry.name for entry in result.entries],
            ["aula1.pdf", "aula2.pdf", "aula10.pdf"],
        )

    def test_recent_order_is_descending_with_natural_name_tie_break(self) -> None:
        entries = (
            LocalFileEntry(Path("aula10.pdf"), LocalFileCategory.PDF, 1, 8.0),
            LocalFileEntry(Path("antiga.pdf"), LocalFileCategory.PDF, 1, 1.0),
            LocalFileEntry(Path("aula2.pdf"), LocalFileCategory.PDF, 1, 8.0),
        )
        result = project_local_files(entries, sort=LocalFileSort.RECENT)
        self.assertEqual(
            [entry.name for entry in result.entries],
            ["aula2.pdf", "aula10.pdf", "antiga.pdf"],
        )

    def test_query_category_sort_and_limit_are_composed(self) -> None:
        entries = (
            LocalFileEntry(Path("ação10.pdf"), LocalFileCategory.PDF, 1, 4.0),
            LocalFileEntry(Path("ação2.pdf"), LocalFileCategory.PDF, 1, 5.0),
            LocalFileEntry(Path("ação.png"), LocalFileCategory.IMAGE, 1, 6.0),
            LocalFileEntry(Path("outra.pdf"), LocalFileCategory.PDF, 1, 7.0),
        )
        result = project_local_files(
            entries,
            category=LocalFileCategory.PDF,
            query=unicodedata.normalize("NFD", "AÇÃO"),
            sort=LocalFileSort.RECENT,
            limit=1,
        )
        self.assertEqual([entry.name for entry in result.entries], ["ação2.pdf"])
        self.assertEqual(result.total_count, 2)

    def test_synthetic_snapshots_keep_full_total_but_limit_projection(self) -> None:
        hundred = project_local_files(self._entries(100), limit=500)
        thousand = project_local_files(self._entries(1_000), limit=500)
        thousand_expanded = project_local_files(self._entries(1_000), limit=1_000)
        ten_thousand = project_local_files(self._entries(10_000), limit=500)

        self.assertEqual((len(hundred.entries), hundred.total_count), (100, 100))
        self.assertEqual(
            (len(thousand.entries), thousand.total_count),
            (500, 1_000),
        )
        self.assertEqual(
            (len(thousand_expanded.entries), thousand_expanded.total_count),
            (1_000, 1_000),
        )
        self.assertEqual(
            (len(ten_thousand.entries), ten_thousand.total_count),
            (500, 10_000),
        )

        searched = project_local_files(
            self._entries(10_000),
            query="arquivo9999",
            limit=500,
        )
        filtered = project_local_files(
            self._entries(10_000),
            category=LocalFileCategory.PDF,
            query="arquivo10",
            limit=500,
        )
        self.assertEqual(
            [entry.name for entry in searched.entries], ["arquivo9999.mp3"]
        )
        self.assertGreater(filtered.total_count, 0)
        self.assertTrue(
            all(entry.category is LocalFileCategory.PDF for entry in filtered.entries)
        )
        documents = project_local_files(
            self._entries(10_000),
            category=LocalFileCategory.DOCUMENT,
            limit=500,
        )
        self.assertEqual((len(documents.entries), documents.total_count), (500, 2_000))
        self.assertTrue(
            all(
                entry.category is LocalFileCategory.DOCUMENT
                for entry in documents.entries
            )
        )

    def test_invalid_sort_and_limit_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            project_local_files((), sort="name")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            project_local_files((), limit=True)
        with self.assertRaises(ValueError):
            project_local_files((), limit=0)


class LocalFileErrorTests(unittest.TestCase):
    def assert_safe_error(self, operation, forbidden_path: Path) -> str:
        with self.assertRaises(LocalFilesError) as context:
            operation()
        message = str(context.exception)
        self.assertNotIn(str(forbidden_path), message)
        return message

    def test_missing_and_non_directory_paths_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            missing = directory / "pessoal" / "ausente"
            self.assert_safe_error(lambda: list_local_files(missing), missing)
            file_path = directory / "arquivo.pdf"
            file_path.write_bytes(b"pdf")
            self.assert_safe_error(lambda: list_local_files(file_path), file_path)

    def test_relative_directory_is_rejected_before_filesystem_access(self) -> None:
        with patch("local_files.os.stat") as stat_call:
            with self.assertRaisesRegex(LocalFilesError, "caminho absoluto"):
                list_local_files(Path("pasta-relativa"))

        stat_call.assert_not_called()

    def test_permission_and_scandir_errors_are_translated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            with patch("local_files.os.scandir", side_effect=PermissionError):
                message = self.assert_safe_error(
                    lambda: list_local_files(directory), directory
                )
                self.assertIn("permissão", message.casefold())
            with patch("local_files.os.scandir", side_effect=OSError):
                message = self.assert_safe_error(
                    lambda: list_local_files(directory), directory
                )
                self.assertIn("ler", message.casefold())

    def test_unc_is_rejected_without_touching_network(self) -> None:
        unc = Path(r"\\servidor\pasta-pessoal")
        with (
            patch("local_files._windows_drive_type") as drive_type,
            patch("local_files.os.stat") as stat_call,
        ):
            message = self.assert_safe_error(lambda: list_local_files(unc), unc)
        self.assertIn("rede", message.casefold())
        drive_type.assert_not_called()
        stat_call.assert_not_called()

    def test_remote_drive_is_rejected_and_local_drive_types_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            with patch(
                "local_files._windows_drive_type",
                return_value=local_files._DRIVE_REMOTE,
            ):
                message = self.assert_safe_error(
                    lambda: list_local_files(directory), directory
                )
                self.assertIn("rede", message.casefold())
            for drive_type in (
                local_files._DRIVE_FIXED,
                local_files._DRIVE_REMOVABLE,
            ):
                with (
                    self.subTest(drive_type=drive_type),
                    patch("local_files._windows_drive_type", return_value=drive_type),
                ):
                    self.assertEqual(list_local_files(directory), ())


class FutureLocalPathPolicyTests(unittest.TestCase):
    def test_absolute_regular_file_with_spaces_and_unicode_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "Material João — aula 你好.pdf"
            path.write_bytes(b"pdf")
            self.assertEqual(validate_local_regular_file(path), path)

    def test_relative_and_unc_files_are_rejected_before_filesystem_access(self) -> None:
        with patch("local_files.os.stat") as stat_call:
            with self.assertRaises(LocalFilesError):
                validate_local_regular_file(Path("material.pdf"))
            with self.assertRaises(LocalFilesError):
                validate_local_regular_file(r"\\servidor\materiais\aula.pdf")
        stat_call.assert_not_called()

    def test_directory_and_simulated_reparse_file_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            with self.assertRaises(LocalFilesError):
                validate_local_regular_file(directory)

            path = directory / "aula.pdf"
            path.write_bytes(b"pdf")
            actual = path.stat()
            reparse = SimpleNamespace(
                st_mode=actual.st_mode,
                st_file_attributes=local_files._FILE_ATTRIBUTE_REPARSE_POINT,
            )
            with (
                patch("local_files.os.stat", return_value=reparse),
                self.assertRaises(LocalFilesError),
            ):
                validate_local_regular_file(path)

    def test_windows_equivalence_is_case_and_separator_insensitive(self) -> None:
        self.assertTrue(
            windows_paths_equivalent(
                r"C:\A\File.pdf",
                r"c:/a/file.pdf",
            )
        )
        self.assertFalse(
            windows_paths_equivalent(
                r"C:\A\File.pdf",
                r"C:\A\Outro.pdf",
            )
        )

    def test_output_must_be_distinct_from_every_input(self) -> None:
        with self.assertRaises(LocalFilesError):
            require_distinct_output_path(
                r"c:\a\file.pdf",
                (r"C:\A\File.pdf", r"C:\A\Outro.pdf"),
            )
        output = Path(r"C:\A\resultado.pdf")
        self.assertEqual(
            require_distinct_output_path(output, (r"C:\A\File.pdf",)),
            output,
        )

    def test_output_policy_requires_local_absolute_parent_and_distinct_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            source = directory / "Entrada João.pdf"
            source.write_bytes(b"pdf")
            output = directory / "Saída Educação 你好.pdf"
            self.assertEqual(
                validate_local_output_path(output, inputs=(source,)),
                output,
            )
            output.write_bytes(b"existing")
            self.assertEqual(
                validate_local_output_path(output, inputs=(source,)),
                output,
            )
            with self.assertRaises(LocalFilesError):
                validate_local_output_path(source, inputs=(source,))

        with self.assertRaises(LocalFilesError):
            validate_local_output_path(Path("resultado.pdf"))
        with self.assertRaises(LocalFilesError):
            validate_local_output_path(r"\\servidor\materiais\resultado.pdf")

    def test_output_policy_rejects_existing_reparse_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "resultado.pdf"
            output.write_bytes(b"pdf")
            actual_directory = output.parent.stat()
            actual_output = output.stat()
            directory_metadata = SimpleNamespace(
                st_mode=actual_directory.st_mode,
                st_file_attributes=0,
            )
            reparse_output = SimpleNamespace(
                st_mode=actual_output.st_mode,
                st_file_attributes=local_files._FILE_ATTRIBUTE_REPARSE_POINT,
            )
            with (
                patch(
                    "local_files.os.stat",
                    side_effect=(directory_metadata, reparse_output),
                ),
                self.assertRaises(LocalFilesError),
            ):
                validate_local_output_path(output)


class LocalFileRevalidationTests(unittest.TestCase):
    def test_revalidates_existing_file_and_refreshes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            file_path = directory / "atividade.pdf"
            file_path.write_bytes(b"conteudo")
            entry = list_local_files(directory)[0]
            file_path.write_bytes(b"conteudo atualizado")

            refreshed = revalidate_local_file(entry, directory)

        self.assertEqual(refreshed.size_bytes, len(b"conteudo atualizado"))
        self.assertEqual(refreshed.path, file_path)

    def test_removed_file_and_directory_replacement_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            file_path = directory / "atividade.pdf"
            file_path.write_bytes(b"pdf")
            entry = list_local_files(directory)[0]
            file_path.unlink()
            with self.assertRaises(LocalFilesError):
                revalidate_local_file(entry, directory)
            file_path.mkdir()
            with self.assertRaises(LocalFilesError):
                revalidate_local_file(entry, directory)

    def test_direct_parent_and_expected_category_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            other = directory / "outra"
            other.mkdir()
            outside = other / "atividade.pdf"
            outside.write_bytes(b"pdf")
            entry = LocalFileEntry(outside, LocalFileCategory.PDF, 3, 1.0)
            with self.assertRaises(LocalFilesError):
                revalidate_local_file(entry, directory)

            inside = directory / "foto.jpg"
            inside.write_bytes(b"jpg")
            incompatible = LocalFileEntry(inside, LocalFileCategory.PDF, 3, 1.0)
            with self.assertRaises(LocalFilesError):
                revalidate_local_file(incompatible, directory)

    def test_simulated_reparse_file_fails_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            file_path = directory / "atividade.pdf"
            file_path.write_bytes(b"pdf")
            entry = list_local_files(directory)[0]
            directory_stat = os.stat(directory, follow_symlinks=False)
            reparse_stat = SimpleNamespace(
                st_mode=stat.S_IFREG,
                st_size=3,
                st_mtime=1.0,
                st_file_attributes=local_files._FILE_ATTRIBUTE_REPARSE_POINT,
            )
            with patch(
                "local_files.os.stat", side_effect=(directory_stat, reparse_stat)
            ):
                with self.assertRaises(LocalFilesError):
                    revalidate_local_file(entry, directory)


@unittest.skipUnless(os.name == "nt", "Ações de arquivo são específicas do Windows")
class LocalFileWindowsActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "vídeo com espaço ção.mp4"
        self.path.write_bytes(b"video")
        self.entry = list_local_files(self.directory)[0]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_open_uses_startfile_with_exact_path(self) -> None:
        with patch.object(local_files.os, "startfile") as startfile:
            result = open_local_file(self.entry, self.directory)
        startfile.assert_called_once_with(str(self.path))
        self.assertEqual(result, self.path)

    def test_missing_file_is_not_opened(self) -> None:
        self.path.unlink()
        with patch.object(local_files.os, "startfile") as startfile:
            with self.assertRaises(LocalFilesError):
                open_local_file(self.entry, self.directory)
        startfile.assert_not_called()

    def test_reveal_uses_separate_argv_without_shell(self) -> None:
        with patch("local_files.subprocess.Popen") as popen:
            result = reveal_local_file(self.entry, self.directory)

        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["explorer.exe", "/select,", str(self.path)])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(args[0][2], str(self.path))
        self.assertEqual(result, self.path)

    def test_system_action_errors_are_translated_without_personal_path(self) -> None:
        with patch.object(local_files.os, "startfile", side_effect=OSError):
            with self.assertRaises(LocalFilesError) as open_context:
                open_local_file(self.entry, self.directory)
        with patch("local_files.subprocess.Popen", side_effect=OSError):
            with self.assertRaises(LocalFilesError) as reveal_context:
                reveal_local_file(self.entry, self.directory)
        self.assertNotIn(str(self.directory), str(open_context.exception))
        self.assertNotIn(str(self.directory), str(reveal_context.exception))


if __name__ == "__main__":
    unittest.main()
