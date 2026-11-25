"""Testes do arquivo JSON de configurações."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from constants import DEFAULT_SETTINGS
from settings import (
    MAX_FAVORITE_FOLDERS,
    FavoriteFolderResult,
    add_favorite_folder,
    default_settings,
    favorite_folder_comparison_key,
    get_favorite_folders,
    is_favorite_folder,
    load_settings,
    remove_favorite_folder,
    save_settings,
)


class SettingsTests(unittest.TestCase):
    def test_missing_file_is_created_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            loaded = load_settings(settings_path)
            self.assertEqual(loaded, DEFAULT_SETTINGS)
            self.assertTrue(settings_path.is_file())

    def test_valid_settings_are_saved_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            expected = {
                "tema": "escuro",
                "text_scale": 110,
                "ultimo_tipo": "Áudio MP3",
                "ultima_qualidade": "720p",
                "favorite_folders": [],
                "documents_component_path": None,
            }
            save_settings(expected, settings_path)
            self.assertEqual(load_settings(settings_path), expected)

    def test_text_scale_migrates_old_files_and_rejects_unsupported_values(self):
        from settings import normalize_settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            legacy = {"tema": "escuro", "ultima_qualidade": "720p"}
            path.write_text(json.dumps(legacy), encoding="utf-8")
            upgraded = load_settings(path)
            self.assertEqual(upgraded["text_scale"], DEFAULT_SETTINGS["text_scale"])
            for key, value in legacy.items():
                self.assertEqual(upgraded[key], value)
            for value in (True, None, 80, 130, -100, 105, "120", 120.0, [120]):
                with self.subTest(value=value):
                    self.assertEqual(
                        normalize_settings({"text_scale": value})["text_scale"], 100
                    )
            for value in (90, 100, 110, 120):
                with self.subTest(value=value):
                    save_settings({**upgraded, "text_scale": value}, path)
                    self.assertEqual(load_settings(path)["text_scale"], value)

    def test_legacy_motion_is_removed_during_normal_settings_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            old = {"tema": "escuro", "text_scale": 120}
            for mode in ("equilibrado", "reduzido", "desativado", ["inválido"]):
                with self.subTest(mode=mode):
                    path.write_text(
                        json.dumps({**old, "motion": mode}), encoding="utf-8"
                    )
                    loaded = load_settings(path)
                    self.assertNotIn("motion", loaded)
                    self.assertEqual({key: loaded[key] for key in old}, old)
                    self.assertEqual(
                        json.loads(path.read_text(encoding="utf-8")), loaded
                    )

    def test_save_does_not_overwrite_unknown_stale_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            stale_path = settings_path.with_suffix(".json.tmp")
            stale_path.write_text("outra operação", encoding="utf-8")

            save_settings(default_settings(), settings_path)

            self.assertEqual(stale_path.read_text(encoding="utf-8"), "outra operação")
            self.assertEqual(load_settings(settings_path), DEFAULT_SETTINGS)

    def test_failed_save_preserves_previous_settings_and_removes_owned_temp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            previous = default_settings()
            previous["tema"] = "escuro"
            save_settings(previous, settings_path)

            with patch.object(Path, "replace", side_effect=OSError("falha simulada")):
                with self.assertRaises(OSError):
                    save_settings(default_settings(), settings_path)

            self.assertEqual(load_settings(settings_path), previous)
            self.assertEqual(list(settings_path.parent.iterdir()), [settings_path])

    def test_fsync_failure_preserves_previous_component_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            previous = default_settings()
            previous["documents_component_path"] = r"C:\LibreOfficeAnterior"
            save_settings(previous, settings_path)
            changed = {**previous, "documents_component_origin": "MANAGED"}
            with patch("settings.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    save_settings(changed, settings_path)
            self.assertEqual(load_settings(settings_path), previous)
            self.assertEqual(list(settings_path.parent.iterdir()), [settings_path])

    def test_corrupted_file_uses_defaults_without_destroying_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            settings_path.write_text("{arquivo quebrado", encoding="utf-8")
            loaded = load_settings(settings_path)
            self.assertEqual(loaded, DEFAULT_SETTINGS)
            self.assertEqual(
                settings_path.read_text(encoding="utf-8"), "{arquivo quebrado"
            )
            with self.assertRaises(OSError):
                save_settings(loaded, settings_path)

    def test_invalid_utf8_file_uses_defaults_without_destroying_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            settings_path.write_bytes(b"\xff\xfe\x00")
            loaded = load_settings(settings_path)
            self.assertEqual(loaded, DEFAULT_SETTINGS)
            self.assertEqual(settings_path.read_bytes(), b"\xff\xfe\x00")
            with self.assertRaises(OSError):
                save_settings(loaded, settings_path)

    def test_unknown_or_invalid_values_are_not_kept(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            invalid = {
                "tema": "azul",
                "ultimo_tipo": "Documento",
                "ultima_qualidade": "8K",
                "senha": "não deve ser mantida",
            }
            settings_path.write_text(
                json.dumps(invalid, ensure_ascii=False), encoding="utf-8"
            )
            self.assertEqual(load_settings(settings_path), DEFAULT_SETTINGS)
            repaired = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertNotIn("senha", repaired)

    def test_default_favorites_are_empty_and_not_shared(self) -> None:
        first = default_settings()
        second = default_settings()
        first["favorite_folders"].append(r"C:\Material")

        self.assertEqual(second["favorite_folders"], [])
        self.assertEqual(DEFAULT_SETTINGS["favorite_folders"], [])

    def test_legacy_1_1_settings_migrate_to_empty_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            legacy = {
                "tema": "escuro",
                "ultimo_tipo": "Áudio MP3",
                "ultima_qualidade": "720p",
            }
            settings_path.write_text(json.dumps(legacy), encoding="utf-8")

            loaded = load_settings(settings_path)
            repaired = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["favorite_folders"], [])
        self.assertEqual(repaired["favorite_folders"], [])
        self.assertIsNone(repaired["documents_component_path"])
        self.assertEqual(
            {key: loaded[key] for key in legacy},
            legacy,
        )

    def test_comparison_key_is_pure_case_insensitive_and_unicode_aware(self) -> None:
        composed = r"C:\Professores\Material Ação"
        decomposed = "c:/professores/material Ac\u0327a\u0303o/"
        with (
            patch("pathlib.Path.resolve", side_effect=AssertionError),
            patch("os.stat", side_effect=AssertionError),
            patch("os.scandir", side_effect=AssertionError),
        ):
            first = favorite_folder_comparison_key(composed)
            second = favorite_folder_comparison_key(decomposed)

        self.assertEqual(first, second)
        self.assertIsNone(favorite_folder_comparison_key("pasta relativa"))
        self.assertIsNone(favorite_folder_comparison_key(r"\\servidor\material"))
        self.assertIsNone(favorite_folder_comparison_key("C:material"))
        self.assertIsNone(favorite_folder_comparison_key("  "))
        self.assertIsNone(favorite_folder_comparison_key("C:\\linha\nnova"))
        self.assertIsNone(favorite_folder_comparison_key("C:\\material?.pdf"))
        self.assertIsNone(favorite_folder_comparison_key("C:\\" + "a" * 32_768))
        self.assertIsNotNone(favorite_folder_comparison_key("D:\\"))

    def test_add_duplicate_query_remove_and_idempotence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            original = r"C:\Professores\Material com espaço Ação"
            equivalent = "c:/professores/material com espaço ac\u0327a\u0303o/"
            other = r"D:\Conteúdo temporariamente indisponível"

            self.assertIs(
                add_favorite_folder(original, settings_path),
                FavoriteFolderResult.ADDED,
            )
            self.assertIs(
                add_favorite_folder(equivalent, settings_path),
                FavoriteFolderResult.ALREADY_EXISTS,
            )
            self.assertIs(
                add_favorite_folder(other, settings_path),
                FavoriteFolderResult.ADDED,
            )
            self.assertEqual(get_favorite_folders(settings_path), (original, other))
            self.assertTrue(is_favorite_folder(equivalent, settings_path))
            self.assertIs(
                remove_favorite_folder(equivalent, settings_path),
                FavoriteFolderResult.REMOVED,
            )
            self.assertIs(
                remove_favorite_folder(equivalent, settings_path),
                FavoriteFolderResult.NOT_FOUND,
            )
            self.assertEqual(get_favorite_folders(settings_path), (other,))

    def test_invalid_add_and_remove_are_controlled_and_create_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            for candidate in (
                "",
                "   ",
                "relativa/material",
                r"\\servidor\material",
                "C:material",
            ):
                with self.subTest(candidate=candidate):
                    self.assertIs(
                        add_favorite_folder(candidate, settings_path),
                        FavoriteFolderResult.INVALID_PATH,
                    )
                    self.assertIs(
                        remove_favorite_folder(candidate, settings_path),
                        FavoriteFolderResult.INVALID_PATH,
                    )
                    self.assertFalse(is_favorite_folder(candidate, settings_path))
            self.assertFalse(settings_path.exists())

    def test_ten_favorites_are_allowed_and_eleventh_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            for index in range(MAX_FAVORITE_FOLDERS):
                self.assertIs(
                    add_favorite_folder(rf"C:\Material\Pasta {index}", settings_path),
                    FavoriteFolderResult.ADDED,
                )
            before = settings_path.read_bytes()
            result = add_favorite_folder(r"C:\Material\Pasta 11", settings_path)

            self.assertIs(result, FavoriteFolderResult.LIMIT_REACHED)
            self.assertEqual(len(get_favorite_folders(settings_path)), 10)
            self.assertEqual(settings_path.read_bytes(), before)

    def test_loader_salvages_first_ten_valid_unique_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            valid = [rf"C:\Material\Pasta {index}" for index in range(12)]
            raw = {
                "tema": "escuro",
                "ultimo_tipo": "Áudio MP3",
                "ultima_qualidade": "720p",
                "favorite_folders": [
                    None,
                    42,
                    "",
                    "   ",
                    "relativa",
                    r"\\servidor\material",
                    valid[0],
                    valid[0].lower().replace("\\", "/"),
                    *valid[1:],
                    "D:\\",
                ],
            }
            settings_path.write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8"
            )

            loaded = load_settings(settings_path)
            repaired = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["favorite_folders"], valid[:10])
        self.assertEqual(repaired, loaded)

    def test_non_list_favorites_fail_safe_without_affecting_other_settings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            for invalid in (None, 123, r"C:\Material", {"pasta": "C:\\"}):
                with self.subTest(invalid=invalid):
                    raw = {
                        "tema": "escuro",
                        "ultimo_tipo": "Áudio MP3",
                        "ultima_qualidade": "720p",
                        "favorite_folders": invalid,
                    }
                    settings_path.write_text(
                        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
                    )
                    loaded = load_settings(settings_path)
                    self.assertEqual(loaded["favorite_folders"], [])
                    self.assertEqual(loaded["tema"], "escuro")

    def test_unicode_round_trip_preserves_other_preferences_and_json_style(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            expected = {
                "tema": "escuro",
                "ultimo_tipo": "Áudio MP3",
                "ultima_qualidade": "1080p",
                "text_scale": 100,
                "favorite_folders": [
                    r"C:\João\Educação 你好",
                    "D:\\Mídia desconectada",
                ],
                "documents_component_path": r"C:\Componentes\Documentos Ação 你好",
            }

            saved = save_settings(expected, settings_path)
            serialized = settings_path.read_text(encoding="utf-8")
            loaded = load_settings(settings_path)

        self.assertEqual(saved, expected)
        self.assertEqual(loaded, expected)
        self.assertIn("João", serialized)
        self.assertIn("你好", serialized)
        self.assertTrue(serialized.endswith("\n"))

    def test_documents_component_path_migrates_round_trips_and_can_be_removed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            legacy = {
                "tema": "claro",
                "ultimo_tipo": "Vídeo MP4",
                "ultima_qualidade": "Melhor qualidade",
                "favorite_folders": [],
            }
            settings_path.write_text(json.dumps(legacy), encoding="utf-8")
            migrated = load_settings(settings_path)
            self.assertIsNone(migrated["documents_component_path"])

            expected_path = r"D:\Componente Documentos\Educação 你好"
            migrated["documents_component_path"] = expected_path
            saved = save_settings(migrated, settings_path)
            self.assertEqual(saved["documents_component_path"], expected_path)
            self.assertEqual(
                load_settings(settings_path)["documents_component_path"],
                expected_path,
            )

            saved["documents_component_path"] = None
            self.assertIsNone(
                save_settings(saved, settings_path)["documents_component_path"]
            )

    def test_documents_component_path_validation_is_structural_and_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            for invalid in (
                "",
                "pasta relativa",
                r"\\servidor\componente",
                "C:componente",
                "C:\\documentos?",
                42,
            ):
                with self.subTest(invalid=invalid):
                    with patch("os.stat", side_effect=AssertionError):
                        saved = save_settings(
                            {
                                **default_settings(),
                                "documents_component_path": invalid,
                            },
                            settings_path,
                        )
                    self.assertIsNone(saved["documents_component_path"])

    def test_loading_favorites_never_catalogs_opens_or_logs_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            favorite = r"Z:\Pasta ausente\Material pessoal"
            save_settings(
                {**default_settings(), "favorite_folders": [favorite]},
                settings_path,
            )

            with (
                patch("os.scandir", side_effect=AssertionError),
                patch("os.stat", side_effect=AssertionError),
                patch("os.startfile", side_effect=AssertionError),
                patch("subprocess.Popen", side_effect=AssertionError),
                patch("logging.Logger._log", side_effect=AssertionError),
            ):
                loaded = get_favorite_folders(settings_path)
                present = is_favorite_folder(favorite.lower(), settings_path)

        self.assertEqual(loaded, (favorite,))
        self.assertTrue(present)


if __name__ == "__main__":
    unittest.main()
