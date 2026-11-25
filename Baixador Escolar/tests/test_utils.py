"""Testes das funções auxiliares."""

import unittest

from utils import (
    format_duration,
    format_size,
    is_empty,
    is_valid_url,
    sanitize_filename,
)


class UtilsTests(unittest.TestCase):
    def test_is_empty_accepts_none_spaces_and_empty_text(self) -> None:
        self.assertTrue(is_empty(None))
        self.assertTrue(is_empty(""))
        self.assertTrue(is_empty("   "))
        self.assertFalse(is_empty("conteúdo"))

    def test_url_requires_http_or_https_and_host(self) -> None:
        self.assertTrue(is_valid_url("https://example.com/aula"))
        self.assertTrue(is_valid_url("http://example.com"))
        self.assertFalse(is_valid_url("example.com/aula"))
        self.assertFalse(is_valid_url("ftp://example.com/aula"))
        self.assertFalse(is_valid_url("https://exa mple.com"))
        self.assertFalse(is_valid_url("https://[endereco-incompleto"))
        self.assertFalse(is_valid_url("https://usuario@:80"))
        self.assertFalse(is_valid_url(None))

    def test_format_size(self) -> None:
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1_572_864), "1.5 MB")
        with self.assertRaises(ValueError):
            format_size(-1)

    def test_format_duration(self) -> None:
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "01:01:01")
        with self.assertRaises(ValueError):
            format_duration(-1)

    def test_sanitize_filename_for_windows(self) -> None:
        self.assertEqual(
            sanitize_filename("Aula: matemática? <parte 1>."),
            "Aula_ matemática_ _parte 1_",
        )
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("..."), "conteudo")
        self.assertEqual(sanitize_filename("a" * 200), "a" * 180)
        with self.assertRaises(ValueError):
            sanitize_filename("aula", max_length=0)


if __name__ == "__main__":
    unittest.main()
