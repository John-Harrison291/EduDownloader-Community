"""Horários de trecho independentes da GUI e da disponibilidade de FFmpeg."""

import unittest
from media_time import parse_media_time, parse_media_segment


class MediaTimeTests(unittest.TestCase):
    def test_examples_and_long_minutes(self):
        self.assertEqual(parse_media_segment("02:30", "05:45"), (150, 345))
        self.assertEqual(parse_media_time("01:02:03"), 3723)
        self.assertEqual(parse_media_time("90:00"), 5400)
        self.assertEqual(parse_media_time(" 00:00 "), 0)

    def test_empty_negative_non_numeric_and_invalid_clock_fields(self):
        for value in (
            "",
            "-01:00",
            "01:-01",
            "01:60",
            "01:60:00",
            "00:00:60",
            "1:00",
            "00",
            "1.5",
            "00:01.5",
            "ab:cd",
            "00:00:00:00",
            "１２:３０",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_media_time(value)

    def test_order_and_mixed_formats(self):
        self.assertEqual(parse_media_segment("59:59", "01:00:00"), (3599, 3600))
        for start, end in (
            ("00:00", "00:00"),
            ("01:00", "00:59"),
            ("", "01:00"),
            ("00:00", ""),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                parse_media_segment(start, end)
