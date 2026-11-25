"""Consulta de versões públicas e aprovação local de perfis de componentes."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass


_HTTPS = "https://"
_GITHUB = _HTTPS + "api.github.com/repos/"
_RELEASES = {
    "deno": _GITHUB + "denoland/deno/releases/latest",
    "ocr": _GITHUB + "tesseract-ocr/tesseract/releases/latest",
    "ffmpeg-ffprobe": _HTTPS + "ffmpeg.org/download.html",
    "libreoffice": _HTTPS + "download.documentfoundation.org/libreoffice/stable/",
}
_HOSTS = frozenset(
    {
        "api.github.com",
        "ffmpeg.org",
        "www.ffmpeg.org",
        "download.documentfoundation.org",
    }
)
_VERSIONS = re.compile(r"(?:v|n)?([0-9]+(?:\.[0-9]+){1,3})")
_CACHE_SECONDS = 15 * 60

# A release estável abaixo foi conferida com o ativo oficial, hashes, fonte,
# Windows x64, execução e integração com o downloader da Community 2.5.0.
_APPROVED_YTDLP = {
    "2026.11.23": (
        23_627_865,
        "622ed48023cac1daa52a3bf3a6ac38f03514de214b5f0fa069389fd0f6d17e5c",
        "40cbeef6bd7c0377479fe87e41add10488a511a1001519b7d4ba2ff67fba618c",
    ),
}
YTDLP_NOTICE_NAMES = ("LICENSE", "THIRD_PARTY_LICENSES.txt")
_YTDLP_2026_11_23_NOTICES = (
    ("LICENSE", "7e12e5df4bae12cb21581ba157ced20e1986a0508dd10d0e8a4ab9a4cf94e85c"),
    (
        "THIRD_PARTY_LICENSES.txt",
        "510233b06ab5222b087d3384ac82ee3f369fde9991fb71e08175d88b72383584",
    ),
)


def approved_yt_dlp_notices(release) -> tuple[tuple[str, str, str], ...]:
    if not approve_yt_dlp(release):
        raise ValueError("Licenças ausentes para a versão solicitada")
    authority = _HTTPS + "raw.githubusercontent.com/yt-dlp/yt-dlp/"
    return tuple(
        (name, authority + release.version + "/" + name, digest)
        for name, digest in _YTDLP_2026_11_23_NOTICES
    )


def approve_yt_dlp(release) -> bool:
    return _APPROVED_YTDLP.get(release.version) == (
        release.binary_size,
        release.binary_digest,
        release.sums_digest,
    )


def parse_version(version: str) -> tuple[int, ...]:
    if not isinstance(version, str) or (match := _VERSIONS.fullmatch(version)) is None:
        raise ValueError("Versão não estável")
    return tuple(map(int, match[1].split(".")))


def reported_version(component: str, raw: bytes) -> str:
    page = raw.decode("utf-8")
    if component in ("deno", "ocr"):
        release = json.loads(page)
        if release.get("draft") is not False or release.get("prerelease") is not False:
            raise ValueError("Publicação não estável")
        versions = [release.get("tag_name")]
    elif component == "ffmpeg-ffprobe":
        versions = re.findall(
            r'href="[^"]*\bffmpeg-([0-9]+(?:\.[0-9]+){1,3})\.tar\.xz"', page
        )
    elif component == "libreoffice":
        versions = re.findall(r'href="([0-9]+(?:\.[0-9]+){1,3})/"', page)
    else:
        raise ValueError("Componente sem autoridade")
    if not versions:
        raise ValueError("Resposta sem versão estável reconhecível")
    return max(versions, key=parse_version).lstrip("vn")


@dataclass(frozen=True, slots=True)
class ReleaseObservation:
    available_version: str | None
    status: str


class ComponentReleaseObserver:
    """A versão anunciada informa o diagnóstico, sem autorizar o download."""

    def __init__(self, transport=None):
        if transport is None:
            from yt_dlp_update import OfficialTransport

            transport = OfficialTransport()
        self._transport = transport
        self._cache: dict[str, tuple[float, str]] = {}

    def check(self, component: str, current_version: str | None) -> ReleaseObservation:
        from yt_dlp_update import UpdateError

        if component not in _RELEASES:
            return ReleaseObservation(None, "unsupported")
        try:
            instant = time.monotonic()
            cached = self._cache.get(component)
            if cached is not None and instant - cached[0] < _CACHE_SECONDS:
                version = cached[1]
            else:
                raw = self._transport.read_bytes(
                    _RELEASES[component], limit=1024 * 1024, allowed_hosts=_HOSTS
                )
                version = reported_version(component, raw)
                self._cache[component] = (instant, version)
            if current_version is not None and parse_version(version) <= parse_version(
                current_version
            ):
                return ReleaseObservation(version, "current")
            return ReleaseObservation(version, "not-approved")
        except UpdateError as error:
            return ReleaseObservation(
                None,
                "offline" if error.code == "connection_unavailable" else "failed",
            )
        except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
            return ReleaseObservation(None, "failed")
