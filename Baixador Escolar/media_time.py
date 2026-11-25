"""Validação dos horários digitados; duração real pertence ao serviço/FFprobe."""

import re


def parse_media_time(value: str) -> int:
    """Converte MM:SS ou HH:MM:SS em segundos não negativos."""
    value = value.strip()
    if not re.fullmatch(r"[0-9]{2,6}:(?:[0-5][0-9]:)?[0-5][0-9]", value):
        raise ValueError("Informe início e fim no formato MM:SS ou HH:MM:SS.")
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    minutes, seconds = parts
    return minutes * 60 + seconds


def parse_media_segment(start: str, end: str) -> tuple[int, int]:
    start_seconds, end_seconds = parse_media_time(start), parse_media_time(end)
    if end_seconds <= start_seconds:
        raise ValueError("O fim do trecho deve ser maior que o início.")
    return start_seconds, end_seconds
