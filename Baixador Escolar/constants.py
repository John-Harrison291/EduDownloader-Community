"""Constantes compartilhadas pelo EduDownloader."""

from enum import StrEnum
from typing import Final


class ProductEdition(StrEnum):
    """Identidade da Community usada pela interface e pelo build."""

    COMMUNITY = "community"


APP_NAME = "EduDownloader"
APP_SUBTITLE = "Baixador Escolar"
PRODUCT_EDITION: Final = ProductEdition.COMMUNITY
COMMUNITY_VERSION: Final = "3.0.0"


def edition_version(edition: ProductEdition) -> str:
    if edition is not ProductEdition.COMMUNITY:
        raise ValueError("Unsupported product identity")
    return COMMUNITY_VERSION


APP_VERSION = COMMUNITY_VERSION
APP_DESCRIPTION = "Prepare downloads de conteúdos educacionais de forma simples."
LEGAL_NOTICE = (
    "Utilize apenas para conteúdos próprios, autorizados ou disponibilizados "
    "legalmente para download."
)

CONTENT_TYPE_VIDEO = "Vídeo MP4"
CONTENT_TYPE_AUDIO = "Áudio MP3"
CONTENT_TYPES = (CONTENT_TYPE_VIDEO, CONTENT_TYPE_AUDIO)
VIDEO_QUALITIES = (
    "Melhor qualidade",
    "1080p",
    "720p",
    "480p",
    "360p",
)

THEME_LIGHT = "claro"
THEME_DARK = "escuro"
THEMES = (THEME_LIGHT, THEME_DARK)
DEFAULT_TEXT_SCALE = 100
TEXT_SCALE_LEVELS = (90, DEFAULT_TEXT_SCALE, 110, 120)
MOTION_BALANCED = "equilibrado"
MOTION_REDUCED = "reduzido"
MOTION_OFF = "desativado"

DEFAULT_SETTINGS = {
    "tema": THEME_LIGHT,
    "text_scale": DEFAULT_TEXT_SCALE,
    "ultimo_tipo": CONTENT_TYPES[0],
    "ultima_qualidade": VIDEO_QUALITIES[0],
    "favorite_folders": [],
    "documents_component_path": None,
}

YTDLP_FILENAME = "yt-dlp.exe"
FFMPEG_FILENAME = "ffmpeg.exe"
FFPROBE_FILENAME = "ffprobe.exe"
DENO_FILENAME = "deno.exe"
REQUIRED_EXECUTABLES = (
    YTDLP_FILENAME,
    FFMPEG_FILENAME,
    FFPROBE_FILENAME,
    DENO_FILENAME,
)
LOG_FILENAME = "edudownloader.log"
