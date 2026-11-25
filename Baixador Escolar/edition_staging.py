"""Lista dos arquivos usados para congelar a Community com PyInstaller."""

from __future__ import annotations

from pathlib import Path
import shutil

from edition_profiles import EditionBuildProfile
from libreoffice_image import IMAGE_FILES
from windows_metadata import version_resource


SHARED_SOURCES = (
    "app",
    "app_factory",
    "component_manager",
    "component_release_policy",
    "component_runtime",
    "component_transactions",
    "constants",
    "documents_component",
    "documents_tools",
    "docx_writer",
    "downloader",
    "download_network",
    "download_queue",
    "file_preview",
    "file_publication",
    "image_drag",
    "image_preparation",
    "libreoffice_managed",
    "libreoffice_image",
    "local_files",
    "media_tools",
    "media_time",
    "mp3_quality",
    "paths",
    "pdfium_access",
    "pdf_ocr_runtime",
    "pdf_ocr_vision",
    "pdf_ocr_windows",
    "pdf_preview_ui",
    "pdf_previews",
    "pdf_results",
    "pdf_tools",
    "pdf_to_docx",
    "pdf_word_layout",
    "pdf_word_ocr",
    "poster_tools",
    "print_layout",
    "settings",
    "ui_design",
    "ui_events",
    "ui_feedback",
    "ui_files_layout",
    "ui_lifecycle",
    "ui_motion",
    "ui_notifications",
    "ui_resize_cover",
    "ui_transitions",
    "ui_scroll",
    "ui_settings_layout",
    "ui_pages",
    "ui_start",
    "utils",
    "video_preview",
    "word_preview",
    "yt_dlp_update",
    "pyi_rth_edudownloader_tk",
)
COMPONENT_SOURCES = (
    "installed_maintenance",
    "windows_attachment",
    "component_catalog",
    "component_smoke",
    "component_updates",
)
COMMUNITY_DATA = {
    **{f"installer/{name}": f"installer/{name}" for name in IMAGE_FILES},
    "installer/community-components-v1.json": "installer/community-components-v1.json",
    "installer/component-assets/DENO-2.9.8-DEPENDENCIAS.txt": "installer/component-assets/DENO-2.9.8-DEPENDENCIAS.txt",
    "installer/component-assets/DENO-BASELINE-LICENSES.txt": "docs/compliance/deno/DENO_THIRD_PARTY_NOTICES.txt",
    "installer/component-assets/FFMPEG_BTBN_LICENSE.txt": "Licencas/FFMPEG_BTBN_LICENSE.txt",
    "installer/component-assets/FFMPEG_BTBN_NOTICE.txt": "Licencas/FFMPEG_BTBN_NOTICE.txt",
}
EXCLUDED_MODULES = (
    "tests",
    "bootstrap",
    "docx",
    "lxml",
    "pytesseract",
    "sqlite3",
    "_sqlite3",
)


def stage_sources(root: Path, target: Path, profile: EditionBuildProfile) -> None:
    """Fresh staging only. Never copy a working tree recursively or private tooling."""
    windows_version = tuple(int(part) for part in profile.app_version.split(".")) + (0,)
    if len(windows_version) != 4 or any(
        part < 0 or part > 65535 for part in windows_version
    ):
        raise ValueError("Invalid Windows product version")
    target.mkdir(parents=True, exist_ok=False)
    sources = [f"{name}.py" for name in SHARED_SOURCES] + [profile.entrypoint]
    sources.extend(f"{name}.py" for name in COMPONENT_SOURCES)
    sources.extend(
        (
            "branding/edudownloader-logo-original.png",
            "branding/edudownloader-symbol.ico",
        )
    )
    for relative in sources:
        source = root / relative
        if source.is_symlink() or source.is_junction() or not source.is_file():
            raise ValueError(f"Missing/unsafe build source: {relative}")
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    for destination, relative in COMMUNITY_DATA.items():
        source = root / relative
        if source.is_symlink() or source.is_junction() or not source.is_file():
            raise ValueError(f"Missing/unsafe Community data: {relative}")
        output = target / destination
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
    spec = root / "EduDownloader.spec"
    if spec.is_symlink() or spec.is_junction() or not spec.is_file():
        raise ValueError("Missing/unsafe PyInstaller specification")
    shutil.copyfile(spec, target / spec.name)
    # Build metadata only; no edition switch or sidecar is distributed to clients.
    (target / "version_info.txt").write_text(
        str(version_resource(edition=profile.edition)) + "\n",
        encoding="utf-8",
    )
