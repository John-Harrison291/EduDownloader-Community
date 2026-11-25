"""Contrato isolado dos perfis MP3, sem ferramentas externas ou interface."""

import unittest

from mp3_quality import (
    DEFAULT_MP3_BITRATE_KBPS,
    DEFAULT_MP3_QUALITY,
    MP3_QUALITY_OPTIONS,
    Mp3Quality,
)


class Mp3QualityTests(unittest.TestCase):
    def test_exactly_three_ordered_profiles_have_stable_ids_and_bitrates(self) -> None:
        self.assertEqual(
            MP3_QUALITY_OPTIONS,
            (Mp3Quality.ECONOMY, Mp3Quality.STANDARD, Mp3Quality.HIGH),
        )
        self.assertEqual(
            [(profile.value, profile.kbps) for profile in MP3_QUALITY_OPTIONS],
            [("economy", 128), ("standard", 192), ("high", 320)],
        )

    def test_labels_and_tool_neutral_bitrate_representation(self) -> None:
        self.assertEqual(
            [profile.label for profile in MP3_QUALITY_OPTIONS],
            ["Econômica", "Padrão", "Alta"],
        )
        self.assertEqual(
            [profile.display_label for profile in MP3_QUALITY_OPTIONS],
            ["Econômica — 128 kbps", "Padrão — 192 kbps", "Alta — 320 kbps"],
        )
        self.assertEqual(
            [profile.bitrate_argument for profile in MP3_QUALITY_OPTIONS],
            ["128k", "192k", "320k"],
        )

    def test_default_is_derived_from_standard(self) -> None:
        self.assertIs(DEFAULT_MP3_QUALITY, Mp3Quality.STANDARD)
        self.assertEqual(DEFAULT_MP3_BITRATE_KBPS, 192)
        self.assertEqual(DEFAULT_MP3_BITRATE_KBPS, DEFAULT_MP3_QUALITY.kbps)

    def test_unknown_or_custom_bitrate_is_rejected(self) -> None:
        for value in ("64", "96", "160", "256", "500", "192", "192k", "other"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Mp3Quality(value)

    def test_contract_does_not_import_ui_or_tool_adapters(self) -> None:
        import ast
        from pathlib import Path

        module = ast.parse(
            (Path(__file__).resolve().parents[1] / "mp3_quality.py").read_text(
                encoding="utf-8"
            )
        )
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(module)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertEqual(imports, {"__future__", "enum", "typing"})


if __name__ == "__main__":
    unittest.main()
