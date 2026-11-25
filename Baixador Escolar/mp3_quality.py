"""Perfis fechados de qualidade MP3 compartilháveis pelas ferramentas."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Mp3Quality(StrEnum):
    """Identidade estável, nome público e bitrate dos três perfis permitidos."""

    ECONOMY = ("economy", "Econômica", 128)
    STANDARD = ("standard", "Padrão", 192)
    HIGH = ("high", "Alta", 320)

    def __new__(cls, key: str, label: str, kbps: int) -> Mp3Quality:
        member = str.__new__(cls, key)
        member._value_ = key
        member.label = label
        member.kbps = kbps
        return member

    @property
    def display_label(self) -> str:
        """Texto simples para um futuro seletor, sem opções técnicas extras."""

        return f"{self.label} — {self.kbps} kbps"

    @property
    def bitrate_argument(self) -> str:
        """Bitrate textual neutro, aceito pelos futuros adaptadores de comando."""

        return f"{self.kbps}k"


MP3_QUALITY_OPTIONS: Final = tuple(Mp3Quality)
DEFAULT_MP3_QUALITY: Final = Mp3Quality.STANDARD
DEFAULT_MP3_BITRATE_KBPS: Final = DEFAULT_MP3_QUALITY.kbps
