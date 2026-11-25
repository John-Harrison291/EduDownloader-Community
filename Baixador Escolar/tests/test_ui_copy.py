"""Regressões puras da terminologia visível da interface."""

import unittest
from pathlib import Path

from ui_pages import (
    DocumentsUiState,
    MediaToolsPage,
    PdfToolsPage,
    _DOCUMENTS_STATE_TEXT,
    _format_count,
)


class UiCopyTests(unittest.TestCase):
    def test_short_counts_use_real_pt_br_pluralization(self) -> None:
        self.assertEqual(
            _format_count(0, "arquivo compatível", "arquivos compatíveis"),
            "0 arquivos compatíveis",
        )
        self.assertEqual(
            _format_count(1, "arquivo compatível", "arquivos compatíveis"),
            "1 arquivo compatível",
        )
        self.assertEqual(
            _format_count(16, "arquivo compatível", "arquivos compatíveis"),
            "16 arquivos compatíveis",
        )

    def test_tool_names_are_consistent_and_user_facing(self) -> None:
        self.assertEqual(
            PdfToolsPage.tool_names,
            (
                "Juntar PDFs",
                "Extrair páginas",
                "Imagens → PDF",
                "PDF → Imagens",
                "Pôster/Painel",
                "PDF para Word",
            ),
        )
        self.assertEqual(MediaToolsPage.tool_names, ("Extrair áudio do vídeo",))

    def test_visible_ui_source_has_no_artificial_plural_markers(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "ui_pages.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            "arquivo(s)",
            "compatível(is)",
            "PDF(s)",
            "imagem(ns)",
            "página(s)",
            "exportada(s)",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)

    def test_document_states_offer_plain_language_and_next_step(self) -> None:
        self.assertEqual(
            _DOCUMENTS_STATE_TEXT[DocumentsUiState.CANCELLING], "Cancelando..."
        )
        self.assertIn("tente novamente", _DOCUMENTS_STATE_TEXT[DocumentsUiState.ERROR])
        self.assertIn(
            "TXT para PDF funciona sem ele",
            _DOCUMENTS_STATE_TEXT[DocumentsUiState.COMPONENT_UNAVAILABLE],
        )


if __name__ == "__main__":
    unittest.main()
