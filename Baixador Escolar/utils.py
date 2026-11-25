"""Funções pequenas e independentes usadas pela interface."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit


_INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_NUMERIC_HOST_LABEL = re.compile(r"(?:[0-9]+|0x[0-9a-f]+)", re.ASCII)


def is_empty(value: str | None) -> bool:
    """Informa se um texto está ausente, vazio ou contém apenas espaços."""
    return value is None or not value.strip()


def is_valid_url(value: str | None) -> bool:
    """Validação estrutural sem I/O, adequada ao campo de entrada."""
    try:
        split_media_url(value)
    except ValueError:
        return False
    return True


def split_media_url(value: str | None):
    """Extrai uma URL de mídia inequívoca, sem interpretar credenciais."""
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= 16_384
        or any(
            character.isspace()
            or character == "\\"
            or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in value
        )
    ):
        raise ValueError("URL inválida")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("URL inválida") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or any(character in parsed.netloc for character in "@%")
        or parsed.netloc.endswith(":")
        or port == 0
    ):
        raise ValueError("URL inválida")
    if parsed.netloc.startswith("["):
        closing = parsed.netloc.index("]")
        if parsed.netloc[closing + 1 :] not in {"", f":{port}"}:
            raise ValueError("Autoridade IPv6 inválida")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        if (address.version == 6) != parsed.netloc.startswith("["):
            raise ValueError("Endereço inválido")
        return parsed
    try:
        ascii_host = hostname.encode("idna").decode("ascii").lower().removesuffix(".")
    except UnicodeError:
        raise ValueError("Host inválido") from None
    labels = ascii_host.split(".")
    if (
        len(ascii_host) > 253
        or not all(_DNS_LABEL.fullmatch(label) for label in labels)
        or _NUMERIC_HOST_LABEL.fullmatch(labels[-1])
        or parsed.netloc.startswith("[")
    ):
        raise ValueError("Host inválido")
    return parsed


def format_size(size_bytes: int | float) -> str:
    """Converte uma quantidade de bytes para uma forma legível."""
    if size_bytes < 0:
        raise ValueError("O tamanho não pode ser negativo.")

    size = float(size_bytes)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("Unidade de tamanho não encontrada.")


def format_duration(total_seconds: int | float) -> str:
    """Formata segundos como MM:SS ou HH:MM:SS."""
    if total_seconds < 0:
        raise ValueError("O tempo não pode ser negativo.")

    seconds = int(total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def sanitize_filename(filename: str, max_length: int = 180) -> str:
    """Remove caracteres proibidos e nomes reservados pelo Windows."""
    if max_length < 1:
        raise ValueError("O limite do nome deve ser maior que zero.")

    sanitized = _INVALID_WINDOWS_FILENAME.sub("_", filename)
    sanitized = re.sub(r"_+", "_", sanitized).strip().rstrip(". ")
    if not sanitized:
        sanitized = "conteudo"

    first_part = sanitized.split(".", maxsplit=1)[0].upper()
    if first_part in _RESERVED_WINDOWS_NAMES:
        sanitized = f"_{sanitized}"

    sanitized = sanitized[:max_length].rstrip(". ")
    return sanitized or "conteudo"
