"""Conversões documentais locais com validação e publicação segura."""

from __future__ import annotations

import ctypes
import math
import msvcrt
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
from io import BytesIO
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final
from urllib.parse import urlunsplit

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from documents_component import (
    DocumentsComponent,
    DocumentsComponentService,
    DocumentsComponentStatus,
)
from local_files import (
    LocalFilesError,
    validate_local_output_path,
    validate_local_regular_file,
)
from paths import (
    InvalidLocalDataPath,
    LocalDataPathUnavailable,
    documents_conversion_temp_parent,
)


DOCX_MAX_FILE_BYTES: Final = 100 * 1024 * 1024
DOCX_MAX_ENTRY_BYTES: Final = 100 * 1024 * 1024
DOCX_MAX_ENTRIES: Final = 10_000
DOCX_MAX_EXPANDED_BYTES: Final = 500 * 1024 * 1024
DOCX_MAX_COMPRESSION_RATIO: Final = 100.0
ODT_MAX_FILE_BYTES: Final = DOCX_MAX_FILE_BYTES
ODT_MAX_ENTRY_BYTES: Final = DOCX_MAX_ENTRY_BYTES
ODT_MAX_ENTRIES: Final = DOCX_MAX_ENTRIES
ODT_MAX_EXPANDED_BYTES: Final = DOCX_MAX_EXPANDED_BYTES
ODT_MAX_COMPRESSION_RATIO: Final = DOCX_MAX_COMPRESSION_RATIO
TXT_MAX_FILE_BYTES: Final = 8 * 1024 * 1024
TXT_MAX_LINE_CHARACTERS: Final = 100_000
TXT_MAX_PAGES: Final = 1_000
TXT_PAGE_WIDTH: Final = 1_240
TXT_PAGE_HEIGHT: Final = 1_754
TXT_PAGE_MARGIN: Final = 100
TXT_FONT_SIZE: Final = 24
TXT_LINE_SPACING: Final = 10
DOCUMENT_CONVERSION_TIMEOUT_SECONDS: Final = 10 * 60.0
PROCESS_POLL_INTERVAL_SECONDS: Final = 0.05
PROCESS_TREE_SHUTDOWN_SECONDS: Final = 5.0
PROCESS_OUTPUT_CAPTURE_BYTES: Final = 64 * 1024
MINIMUM_PDF_BYTES: Final = 64
_DOCX_REQUIRED_ENTRIES: Final = frozenset({"[Content_Types].xml", "word/document.xml"})
_ODT_REQUIRED_ENTRIES: Final = frozenset({"mimetype", "content.xml"})
_ODT_MIMETYPE: Final = b"application/vnd.oasis.opendocument.text"
_PROFILE_NAMESPACE: Final = "http" + "://openoffice.org/2001/registry"
_PROFILE_CONFIGURATION: Final = f"""<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="{_PROFILE_NAMESPACE}">
  <item oor:path="/org.openoffice.Office.Security/Scripting">
    <prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
    <prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
  </item>
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
    <prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
  </item>
  <item oor:path="/org.openoffice.Office.Common/Security">
    <prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
  </item>
</oor:items>
"""


class DocumentConversionStatus(str, Enum):
    """Estados terminais públicos de uma operação documental."""

    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    COMPONENT_UNAVAILABLE = "COMPONENT_UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    ERROR = "ERROR"


class DocumentInputFormat(str, Enum):
    """Formatos aceitos pelo contrato documental público."""

    DOCX = "DOCX"
    TXT = "TXT"
    ODT = "ODT"


@dataclass(frozen=True, slots=True)
class DocumentConversionRequest:
    """Pedido imutável de conversão documental para PDF."""

    input_path: Path
    output_path: Path
    component_root: Path | None = None
    overwrite: bool = False
    cancel_event: threading.Event | None = None
    input_format: DocumentInputFormat = DocumentInputFormat.DOCX
    preview: bool = False


@dataclass(frozen=True, slots=True)
class DocumentConversionResult:
    """Resultado seguro, sem stderr ou paths temporários."""

    status: DocumentConversionStatus
    output_path: Path | None
    engine_version: str | None
    public_message: str
    diagnostic_code: str


@dataclass(frozen=True, slots=True)
class _ProcessOutcome:
    returncode: int | None
    cancelled: bool = False
    timed_out: bool = False
    tree_stopped: bool = True
    stdout: str = ""
    stderr: str = ""


class _InvalidDocument(ValueError):
    pass


class _OutputExists(ValueError):
    pass


class _ConversionCancelled(RuntimeError):
    pass


class _ConversionFailure(RuntimeError):
    def __init__(self, diagnostic_code: str) -> None:
        super().__init__(diagnostic_code)
        self.diagnostic_code = diagnostic_code


_ProcessRunner = Callable[
    [
        Sequence[str],
        Mapping[str, str],
        Path,
        Path,
        Path,
        threading.Event,
        float,
    ],
    _ProcessOutcome,
]


class DocumentsConversionService:
    """Serviço sem UI para uma conversão isolada por chamada."""

    def __init__(
        self,
        *,
        component_service: DocumentsComponentService | None = None,
        timeout_seconds: float = DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
        temporary_parent: Path | None = None,
        process_runner: _ProcessRunner | None = None,
        memory_limit: int | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds deve ser positivo e finito")
        self._component_service = component_service or DocumentsComponentService()
        self._timeout_seconds = timeout_seconds
        self._temporary_parent = temporary_parent
        self._process_runner = process_runner or partial(
            _run_windows_job_process, memory_limit=memory_limit
        )

    def convert(self, request: DocumentConversionRequest) -> DocumentConversionResult:
        """Converte uma entrada validada sem expor detalhes internos ao chamador."""

        cancel_event = request.cancel_event or threading.Event()
        if cancel_event.is_set():
            return _cancelled_result(None)
        if not isinstance(request.input_format, DocumentInputFormat):
            return DocumentConversionResult(
                DocumentConversionStatus.INVALID_INPUT,
                None,
                None,
                "Selecione um documento local e válido.",
                "documents_invalid_input_format",
            )

        if request.input_format is DocumentInputFormat.TXT:
            return self._convert_text(request, cancel_event)

        validator = {
            DocumentInputFormat.DOCX: validate_docx_input,
            DocumentInputFormat.ODT: validate_odt_input,
        }.get(request.input_format)
        if validator is None:
            return _invalid_input_result(None, request.input_format)

        component_check = self._component_service.fast_check(request.component_root)
        if component_check.status is not DocumentsComponentStatus.AVAILABLE:
            return DocumentConversionResult(
                DocumentConversionStatus.COMPONENT_UNAVAILABLE,
                None,
                None,
                "Configure uma instalação local do LibreOffice para esta conversão.",
                component_check.diagnostic_code,
            )
        component = component_check.component
        assert component is not None

        try:
            source = validator(request.input_path)
            output = _validate_pdf_output(
                request.output_path, source, overwrite=request.overwrite
            )
        except _OutputExists:
            return DocumentConversionResult(
                DocumentConversionStatus.OUTPUT_EXISTS,
                None,
                component.engine_version,
                "O arquivo PDF de destino já existe.",
                "documents_output_exists",
            )
        except (_InvalidDocument, LocalFilesError, OSError, ValueError):
            return _invalid_input_result(component.engine_version, request.input_format)

        if cancel_event.is_set():
            return _cancelled_result(component.engine_version)

        operation_root: Path | None = None
        pending_output: Path | None = None
        terminal: DocumentConversionResult | None = None
        try:
            try:
                temporary_parent = (
                    self._temporary_parent
                    if self._temporary_parent is not None
                    else documents_conversion_temp_parent()
                )
            except (
                OSError,
                InvalidLocalDataPath,
                LocalDataPathUnavailable,
            ):
                raise _ConversionFailure("documents_temp_parent_unavailable") from None
            operation_root = Path(
                tempfile.mkdtemp(
                    prefix="EduDownloader-documents-",
                    dir=temporary_parent,
                )
            )
            profile = operation_root / "profile"
            controlled_input = operation_root / "input"
            engine_output = operation_root / "engine-output"
            temporary = operation_root / "temp"
            for directory in (profile, controlled_input, engine_output, temporary):
                directory.mkdir()
            copied_input = controlled_input / f"document{source.suffix.casefold()}"
            _copy_validated_input(source, copied_input)
            if request.preview and not cancel_event.is_set():
                from word_preview import require_offline_document, PreviewCancelled
                from xml.etree.ElementTree import ParseError

                try:
                    require_offline_document(copied_input, cancel_event)
                except PreviewCancelled:
                    raise _ConversionCancelled from None
                except (ValueError, KeyError, ParseError, zipfile.BadZipFile):
                    raise _ConversionFailure(
                        "documents_preview_requires_local_content"
                    ) from None
            if cancel_event.is_set():
                terminal = _cancelled_result(component.engine_version)
            else:
                with socket.socket() if request.preview else nullcontext() as proxy:
                    proxy_port = None
                    environment = build_libreoffice_environment(component, temporary)
                    if proxy is not None:
                        # Porta reservada até o fim da prévia, sem aceitar conexões.
                        proxy.setsockopt(
                            socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                        )
                        proxy.bind(("127.0.0.1", 0))
                        proxy_port = proxy.getsockname()[1]
                        proxy_url = urlunsplit(
                            ("http", f"127.0.0.1:{proxy_port}", "", "", "")
                        )
                        environment = {
                            key: value
                            for key, value in environment.items()
                            if not key.lower().endswith("_proxy")
                            and key.upper() != "SC_FORCE_CALCULATION"
                        }
                        environment.update(
                            HTTP_PROXY=proxy_url,
                            HTTPS_PROXY=proxy_url,
                            SAL_DISABLE_OPENCL="1",
                        )
                    _write_hardened_profile(profile, proxy_port=proxy_port)
                    command = build_libreoffice_command(
                        component,
                        copied_input,
                        engine_output,
                        profile,
                        first_page=request.preview,
                    )
                    outcome = self._process_runner(
                        command,
                        environment,
                        component.soffice_entrypoint.parent,
                        temporary / "stdout.txt",
                        temporary / "stderr.txt",
                        cancel_event,
                        self._timeout_seconds,
                    )
                terminal = _classify_process_outcome(
                    outcome, component.engine_version, cancel_event
                )
                if terminal is None:
                    generated = _validate_staging_output(engine_output)
                    pending_output = _prepare_output_candidate(generated, output)
        except _ConversionCancelled:
            terminal = _cancelled_result(component.engine_version)
        except _ConversionFailure as error:
            terminal = _error_result(component.engine_version, error.diagnostic_code)
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
            terminal = _error_result(
                component.engine_version, "documents_conversion_internal_error"
            )

        cleanup_ok = True
        if operation_root is not None:
            cleanup_ok = _remove_operation_root(operation_root)
        if not cleanup_ok:
            _remove_file(pending_output)
            return _error_result(
                component.engine_version, "documents_temporary_cleanup_failed"
            )
        if terminal is not None:
            if not _remove_file(pending_output):
                return _error_result(
                    component.engine_version, "documents_output_cleanup_failed"
                )
            return terminal
        if pending_output is None:
            return _error_result(
                component.engine_version, "documents_output_candidate_missing"
            )

        publication_result: DocumentConversionResult | None = None
        try:
            _publish_atomically(
                pending_output,
                output,
                overwrite=request.overwrite,
                cancel_event=cancel_event,
            )
        except _ConversionCancelled:
            publication_result = _cancelled_result(component.engine_version)
        except _OutputExists:
            publication_result = DocumentConversionResult(
                DocumentConversionStatus.OUTPUT_EXISTS,
                None,
                component.engine_version,
                "O arquivo PDF de destino já existe.",
                "documents_output_exists_race",
            )
        except (OSError, RuntimeError, ValueError):
            if not request.overwrite and output.exists():
                publication_result = DocumentConversionResult(
                    DocumentConversionStatus.OUTPUT_EXISTS,
                    None,
                    component.engine_version,
                    "O arquivo PDF de destino já existe.",
                    "documents_output_exists_race",
                )
            else:
                publication_result = _error_result(
                    component.engine_version, "documents_atomic_publish_failed"
                )
        if not _remove_file(pending_output):
            return _error_result(
                component.engine_version, "documents_output_cleanup_failed"
            )
        if publication_result is not None:
            return publication_result

        return DocumentConversionResult(
            DocumentConversionStatus.COMPLETED,
            output,
            component.engine_version,
            "PDF criado com sucesso.",
            "documents_conversion_completed",
        )

    def _convert_text(
        self,
        request: DocumentConversionRequest,
        cancel_event: threading.Event,
    ) -> DocumentConversionResult:
        """Converte TXT internamente, sem consultar ou iniciar LibreOffice."""

        try:
            source = validate_txt_input(request.input_path)
            output = _validate_pdf_output(
                request.output_path, source, overwrite=request.overwrite
            )
        except _OutputExists:
            return DocumentConversionResult(
                DocumentConversionStatus.OUTPUT_EXISTS,
                None,
                None,
                "O arquivo PDF de destino já existe.",
                "documents_output_exists",
            )
        except (_InvalidDocument, LocalFilesError, OSError, ValueError):
            return _invalid_input_result(None, DocumentInputFormat.TXT)

        operation_root: Path | None = None
        pending_output: Path | None = None
        terminal: DocumentConversionResult | None = None
        try:
            operation_root = Path(
                tempfile.mkdtemp(
                    prefix="EduDownloader-text-",
                    dir=self._temporary_parent,
                )
            )
            controlled_input = operation_root / "document.txt"
            _copy_validated_input(source, controlled_input)
            generated = operation_root / "document.pdf"
            _render_text_pdf(controlled_input, generated, cancel_event)
            if cancel_event.is_set():
                terminal = _cancelled_result(None)
            else:
                _validate_generated_pdf(generated)
                pending_output = _prepare_output_candidate(generated, output)
        except _ConversionCancelled:
            terminal = _cancelled_result(None)
        except UnicodeError:
            terminal = _invalid_input_result(None, DocumentInputFormat.TXT)
        except _InvalidDocument:
            terminal = _invalid_input_result(None, DocumentInputFormat.TXT)
        except (OSError, RuntimeError, ValueError):
            terminal = _error_result(None, "documents_text_conversion_failed")

        cleanup_ok = True
        if operation_root is not None:
            cleanup_ok = _remove_operation_root(operation_root)
        if not cleanup_ok:
            _remove_file(pending_output)
            return _error_result(None, "documents_temporary_cleanup_failed")
        if terminal is not None:
            if not _remove_file(pending_output):
                return _error_result(None, "documents_output_cleanup_failed")
            return terminal
        if pending_output is None:
            return _error_result(None, "documents_output_candidate_missing")

        publication_result: DocumentConversionResult | None = None
        try:
            _publish_atomically(
                pending_output,
                output,
                overwrite=request.overwrite,
                cancel_event=cancel_event,
            )
        except _ConversionCancelled:
            publication_result = _cancelled_result(None)
        except _OutputExists:
            publication_result = DocumentConversionResult(
                DocumentConversionStatus.OUTPUT_EXISTS,
                None,
                None,
                "O arquivo PDF de destino já existe.",
                "documents_output_exists_race",
            )
        except (OSError, RuntimeError, ValueError):
            if not request.overwrite and output.exists():
                publication_result = DocumentConversionResult(
                    DocumentConversionStatus.OUTPUT_EXISTS,
                    None,
                    None,
                    "O arquivo PDF de destino já existe.",
                    "documents_output_exists_race",
                )
            else:
                publication_result = _error_result(
                    None, "documents_atomic_publish_failed"
                )
        if not _remove_file(pending_output):
            return _error_result(None, "documents_output_cleanup_failed")
        if publication_result is not None:
            return publication_result
        return DocumentConversionResult(
            DocumentConversionStatus.COMPLETED,
            output,
            None,
            "PDF criado com sucesso.",
            "documents_conversion_completed",
        )


def validate_docx_input(value: Path | str) -> Path:
    """Valida estrutura e limites defensivos sem extrair o archive inteiro."""

    try:
        source = validate_local_regular_file(value)
    except LocalFilesError as error:
        raise _InvalidDocument from error
    if source.suffix.casefold() != ".docx":
        raise _InvalidDocument
    _validate_zip_document(
        source,
        required_entries=_DOCX_REQUIRED_ENTRIES,
        max_file_bytes=DOCX_MAX_FILE_BYTES,
        max_entry_bytes=DOCX_MAX_ENTRY_BYTES,
        max_entries=DOCX_MAX_ENTRIES,
        max_expanded_bytes=DOCX_MAX_EXPANDED_BYTES,
        max_compression_ratio=DOCX_MAX_COMPRESSION_RATIO,
    )
    return source


def validate_odt_input(value: Path | str) -> Path:
    """Valida um pacote ODT local antes de qualquer chamada ao motor externo."""

    try:
        source = validate_local_regular_file(value)
    except LocalFilesError as error:
        raise _InvalidDocument from error
    if source.suffix.casefold() != ".odt":
        raise _InvalidDocument
    _validate_zip_document(
        source,
        required_entries=_ODT_REQUIRED_ENTRIES,
        max_file_bytes=ODT_MAX_FILE_BYTES,
        max_entry_bytes=ODT_MAX_ENTRY_BYTES,
        max_entries=ODT_MAX_ENTRIES,
        max_expanded_bytes=ODT_MAX_EXPANDED_BYTES,
        max_compression_ratio=ODT_MAX_COMPRESSION_RATIO,
        odt_mimetype=True,
    )
    return source


def validate_txt_input(value: Path | str) -> Path:
    """Valida somente o envelope local do TXT; o UTF-8 é validado no streaming."""

    try:
        source = validate_local_regular_file(value)
    except LocalFilesError as error:
        raise _InvalidDocument from error
    if source.suffix.casefold() != ".txt":
        raise _InvalidDocument
    metadata = os.stat(source, follow_symlinks=False)
    if metadata.st_size < 0 or metadata.st_size > TXT_MAX_FILE_BYTES:
        raise _InvalidDocument
    return source


def _validate_zip_document(
    source: Path,
    *,
    required_entries: frozenset[str],
    max_file_bytes: int,
    max_entry_bytes: int,
    max_entries: int,
    max_expanded_bytes: int,
    max_compression_ratio: float,
    odt_mimetype: bool = False,
) -> None:
    metadata = os.stat(source, follow_symlinks=False)
    if metadata.st_size <= 0 or metadata.st_size > max_file_bytes:
        raise _InvalidDocument
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise _InvalidDocument
            names: set[str] = set()
            expanded = 0
            for entry in entries:
                if not _safe_zip_entry(entry.filename) or entry.flag_bits & 0x1:
                    raise _InvalidDocument
                unix_type = (entry.external_attr >> 16) & 0o170000
                if unix_type == stat.S_IFLNK:
                    raise _InvalidDocument
                if entry.file_size < 0 or entry.file_size > max_entry_bytes:
                    raise _InvalidDocument
                expanded += entry.file_size
                if expanded > max_expanded_bytes:
                    raise _InvalidDocument
                if entry.file_size:
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    if ratio > max_compression_ratio:
                        raise _InvalidDocument
                normalized = entry.filename.rstrip("/")
                if normalized:
                    key = normalized.casefold()
                    if key in names:
                        raise _InvalidDocument
                    names.add(key)
            if not {name.casefold() for name in required_entries}.issubset(names):
                raise _InvalidDocument
            for required in required_entries:
                info = archive.getinfo(required)
                with archive.open(info) as handle:
                    content = handle.read(info.file_size + 1)
                    if len(content) != info.file_size:
                        raise _InvalidDocument
                    if required in {"content.xml", "word/document.xml"} and not content:
                        raise _InvalidDocument
            if odt_mimetype:
                mimetype = archive.getinfo("mimetype")
                if (
                    mimetype.compress_type != zipfile.ZIP_STORED
                    or archive.read(mimetype) != _ODT_MIMETYPE
                ):
                    raise _InvalidDocument
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise _InvalidDocument from None


def _render_text_pdf(
    source: Path,
    destination: Path,
    cancel_event: threading.Event,
) -> None:
    """Renderiza TXT UTF-8 em A4 retrato por streaming e com memória limitada."""

    writer = PdfWriter()
    font = _load_text_font()
    line_height = _text_line_height(font)
    usable_width = TXT_PAGE_WIDTH - (2 * TXT_PAGE_MARGIN)
    usable_height = TXT_PAGE_HEIGHT - (2 * TXT_PAGE_MARGIN)
    lines_per_page = max(1, usable_height // line_height)
    page: Image.Image | None = None
    draw: ImageDraw.ImageDraw | None = None
    line_index = 0
    page_count = 0

    def ensure_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        nonlocal page, draw, page_count
        if page is None or draw is None:
            if page_count >= TXT_MAX_PAGES:
                raise _InvalidDocument
            page = Image.new("RGB", (TXT_PAGE_WIDTH, TXT_PAGE_HEIGHT), "white")
            draw = ImageDraw.Draw(page)
            page_count += 1
        return page, draw

    def flush_page() -> None:
        nonlocal page, draw, line_index
        if page is None:
            return
        if cancel_event.is_set():
            raise _ConversionCancelled
        buffer = BytesIO()
        try:
            page.save(buffer, format="PDF", resolution=150.0)
            buffer.seek(0)
            rendered = PdfReader(buffer, strict=True)
            if len(rendered.pages) != 1:
                raise _ConversionFailure("documents_text_page_invalid")
            writer.add_page(rendered.pages[0])
        finally:
            buffer.close()
            page.close()
        page = None
        draw = None
        line_index = 0

    try:
        with source.open(
            "r", encoding="utf-8-sig", errors="strict", newline=None
        ) as handle:
            found_line = False
            for raw_line in handle:
                found_line = True
                if cancel_event.is_set():
                    raise _ConversionCancelled
                logical = raw_line.rstrip("\r\n")
                if len(logical) > TXT_MAX_LINE_CHARACTERS:
                    raise _InvalidDocument
                current_page, current_draw = ensure_page()
                wrapped = _wrap_text_line(current_draw, logical, font, usable_width)
                for visual_line in wrapped:
                    if line_index >= lines_per_page:
                        flush_page()
                        current_page, current_draw = ensure_page()
                    current_draw.text(
                        (TXT_PAGE_MARGIN, TXT_PAGE_MARGIN + (line_index * line_height)),
                        visual_line,
                        fill="black",
                        font=font,
                    )
                    line_index += 1
            if not found_line:
                ensure_page()
        flush_page()
        if cancel_event.is_set():
            raise _ConversionCancelled
        with destination.open("wb") as output:
            writer.write(output)
    finally:
        if page is not None:
            page.close()


def _load_text_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Usa fonte Unicode do Windows quando disponível, com Roboto já distribuída."""

    candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts/msyh.ttc",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts/segoeui.ttf",
    ]
    try:
        customtkinter = __import__("customtkinter")
        candidates.append(
            Path(customtkinter.__file__).parent
            / "assets/fonts/Roboto/Roboto-Regular.ttf"
        )
    except (AttributeError, ImportError, TypeError):
        pass
    for candidate in candidates:
        try:
            if candidate.is_file():
                return ImageFont.truetype(candidate, TXT_FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default(size=TXT_FONT_SIZE)


def _text_line_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    top, bottom = font.getbbox("Ag")[1], font.getbbox("Ag")[3]
    return max(1, bottom - top + TXT_LINE_SPACING)


def _wrap_text_line(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> tuple[str, ...]:
    expanded = value.expandtabs(4)
    if not expanded:
        return ("",)
    lines: list[str] = []
    remaining = expanded
    while remaining:
        if draw.textlength(remaining, font=font) <= max_width:
            lines.append(remaining)
            break
        low, high = 1, len(remaining)
        while low < high:
            middle = (low + high + 1) // 2
            if draw.textlength(remaining[:middle], font=font) <= max_width:
                low = middle
            else:
                high = middle - 1
        cut = max(1, low)
        whitespace = max(
            remaining.rfind(" ", 0, cut + 1), remaining.rfind("\t", 0, cut + 1)
        )
        if whitespace > 0:
            cut = whitespace
        lines.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip(" \t")
    return tuple(lines)


def build_libreoffice_command(
    component: DocumentsComponent,
    input_path: Path,
    staging_directory: Path,
    profile_directory: Path,
    *,
    first_page: bool = False,
) -> list[str]:
    """Monta argv explícito; não usa PATH, shell, registro ou cwd implícito."""

    conversion = "pdf:writer_pdf_Export"
    if first_page:
        conversion += ':{"PageRange":{"type":"string","value":"1"}}'
    return [
        str(component.soffice_entrypoint),
        f"-env:UserInstallation={profile_directory.as_uri()}",
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nofirststartwizard",
        "--convert-to",
        conversion,
        "--outdir",
        str(staging_directory),
        str(input_path),
    ]


def build_libreoffice_environment(
    component: DocumentsComponent, temporary_directory: Path
) -> dict[str, str]:
    """Cria ambiente por processo sem alterar PATH nem o ambiente global."""

    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONHOME": str(component.python_home),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(temporary_directory),
            "TMP": str(temporary_directory),
        }
    )
    return environment


def _validate_pdf_output(value: Path | str, source: Path, *, overwrite: bool) -> Path:
    output = validate_local_output_path(value, inputs=(source,))
    if output.suffix.casefold() != ".pdf":
        raise _InvalidDocument
    if output.exists() and not overwrite:
        raise _OutputExists
    return output


def _safe_zip_entry(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value or value.startswith("/"):
        return False
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    return not (
        windows.is_absolute()
        or bool(windows.drive)
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
    )


def _write_hardened_profile(profile: Path, *, proxy_port: int | None = None) -> None:
    user = profile / "user"
    user.mkdir(parents=True)
    configuration = user / "registrymodifications.xcu"
    policy = _PROFILE_CONFIGURATION
    if proxy_port is not None:
        network_settings = {
            "ooInetProxyType": 2,
            "ooInetNoProxy": "",
            "ooInetHTTPProxyName": "127.0.0.1",
            "ooInetHTTPProxyPort": proxy_port,
            "ooInetHTTPSProxyName": "127.0.0.1",
            "ooInetHTTPSProxyPort": proxy_port,
        }
        properties = "\n".join(
            f'    <prop oor:name="{name}" oor:op="fuse"><value>{value}</value></prop>'
            for name, value in network_settings.items()
        )
        policy = policy.replace(
            "</oor:items>",
            f"""  <item oor:path="/org.openoffice.Office.Writer/Content/Update">
    <prop oor:name="Link" oor:op="fuse"><value>0</value></prop>
  </item>
  <item oor:path="/org.openoffice.Inet/Settings">
{properties}
  </item>
  <item oor:path="/org.openoffice.Office.Common/Misc">
    <prop oor:name="CrashReport" oor:op="fuse"><value>false</value></prop>
    <prop oor:name="UseOpenCL" oor:op="fuse"><value>false</value></prop>
  </item>
</oor:items>""",
        )
    configuration.write_text(policy, encoding="utf-8", newline="\n")
    if configuration.read_text(encoding="utf-8") != policy:
        raise _ConversionFailure("documents_profile_policy_not_applied")


def _copy_validated_input(source: Path, destination: Path) -> None:
    before = os.stat(source, follow_symlinks=False)
    shutil.copyfile(source, destination)
    after = os.stat(source, follow_symlinks=False)
    copied = os.stat(destination, follow_symlinks=False)
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or copied.st_size != before.st_size
    ):
        raise _ConversionFailure("documents_input_changed_during_copy")


def _classify_process_outcome(
    outcome: _ProcessOutcome,
    engine_version: str,
    cancel_event: threading.Event,
) -> DocumentConversionResult | None:
    if cancel_event.is_set() or outcome.cancelled:
        return _cancelled_result(engine_version)
    if outcome.timed_out:
        return _error_result(engine_version, "documents_conversion_timeout")
    if not outcome.tree_stopped:
        return _error_result(engine_version, "documents_process_tree_not_stopped")
    if outcome.returncode != 0:
        return _error_result(engine_version, "documents_engine_failed")
    if "Could not find platform independent libraries <prefix>" in outcome.stderr:
        return _error_result(engine_version, "documents_pythonhome_warning")
    return None


def _validate_staging_output(staging: Path) -> Path:
    with os.scandir(staging) as directory:
        entries = [entry for entry in directory if not _is_office_output_lock(entry)]
    if len(entries) != 1 or entries[0].name != "document.pdf":
        raise _ConversionFailure("documents_unexpected_engine_output")
    metadata = entries[0].stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise _ConversionFailure("documents_invalid_engine_output")
    output = Path(entries[0].path)
    _validate_generated_pdf(output)
    return output


def _is_office_output_lock(entry: os.DirEntry) -> bool:
    if entry.name != ".~lock.document.pdf#":
        return False
    details = entry.stat(follow_symlinks=False)
    return stat.S_ISREG(details.st_mode) and not (
        getattr(details, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    )


def _validate_generated_pdf(path: Path) -> None:
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < MINIMUM_PDF_BYTES:
        raise _ConversionFailure("documents_invalid_pdf")
    try:
        with path.open("rb") as handle:
            reader = PdfReader(handle, strict=True)
            if reader.is_encrypted or len(reader.pages) < 1:
                raise _ConversionFailure("documents_invalid_pdf")
            for page in reader.pages:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                if (
                    not math.isfinite(width)
                    or not math.isfinite(height)
                    or width <= 0
                    or height <= 0
                ):
                    raise _ConversionFailure("documents_invalid_pdf")
    except _ConversionFailure:
        raise
    except Exception as error:
        raise _ConversionFailure("documents_invalid_pdf") from error


def _prepare_output_candidate(generated: Path, output: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{output.stem}-",
        suffix=".pending.pdf",
        dir=output.parent,
    )
    os.close(descriptor)
    candidate = Path(name)
    try:
        shutil.copyfile(generated, candidate)
        _validate_generated_pdf(candidate)
    except Exception:
        _unlink_quietly(candidate)
        raise
    return candidate


def _publish_atomically(
    candidate: Path,
    output: Path,
    *,
    overwrite: bool,
    cancel_event: threading.Event,
) -> None:
    if cancel_event.is_set():
        raise _ConversionCancelled
    if output.exists() and not overwrite:
        raise _OutputExists

    backup: Path | None = None
    previous_moved = False
    new_published = False
    try:
        if overwrite and output.exists():
            descriptor, backup_name = tempfile.mkstemp(
                prefix=f".{output.stem}-",
                suffix=".backup.pdf",
                dir=output.parent,
            )
            os.close(descriptor)
            backup = Path(backup_name)
            backup.unlink()
            os.replace(output, backup)
            previous_moved = True
        if cancel_event.is_set():
            raise _ConversionCancelled
        if overwrite:
            os.replace(candidate, output)
        else:
            os.rename(candidate, output)
        new_published = True
        _validate_generated_pdf(output)
        if cancel_event.is_set():
            raise _ConversionCancelled
    except Exception:
        if new_published:
            _unlink_quietly(output)
        if previous_moved and backup is not None and backup.exists():
            os.replace(backup, output)
        raise
    else:
        if backup is not None and backup.exists():
            try:
                backup.unlink()
            except OSError:
                _unlink_quietly(output)
                if backup.exists():
                    os.replace(backup, output)
                raise


def _remove_operation_root(root: Path) -> bool:
    def make_writable_and_retry(
        operation: Callable[[str], object], path: str, _error: BaseException
    ) -> None:
        candidate = Path(path)
        if (
            os.path.commonpath((root, candidate)) != os.path.abspath(root)
            or candidate.is_symlink()
            or candidate.is_junction()
            or candidate.resolve(strict=True) != candidate
        ):
            raise OSError("Refusing cleanup outside operation root")
        os.chmod(candidate, stat.S_IWRITE)
        operation(path)

    for attempt in range(4):
        try:
            if root.is_symlink() or root.is_junction() or root.resolve() != root:
                return False
            shutil.rmtree(root, onexc=make_writable_and_retry)
            return not root.exists()
        except FileNotFoundError:
            return not root.exists()
        except OSError as error:
            if attempt == 3 or getattr(error, "winerror", 0) not in (32, 33):
                return False
            time.sleep(0.04)
    return False


def _unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove_file(path: Path | None) -> bool:
    if path is None:
        return True
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return not path.exists()


def _cancelled_result(engine_version: str | None) -> DocumentConversionResult:
    return DocumentConversionResult(
        DocumentConversionStatus.CANCELLED,
        None,
        engine_version,
        "A conversão foi cancelada.",
        "documents_conversion_cancelled",
    )


def _invalid_input_result(
    engine_version: str | None,
    input_format: DocumentInputFormat,
) -> DocumentConversionResult:
    messages = {
        DocumentInputFormat.DOCX: "Selecione um documento DOCX local e válido.",
        DocumentInputFormat.ODT: "Selecione um documento ODT local e válido.",
        DocumentInputFormat.TXT: "Não foi possível ler este arquivo de texto.",
    }
    return DocumentConversionResult(
        DocumentConversionStatus.INVALID_INPUT,
        None,
        engine_version,
        messages[input_format],
        "documents_invalid_input",
    )


def _error_result(engine_version: str | None, code: str) -> DocumentConversionResult:
    return DocumentConversionResult(
        DocumentConversionStatus.ERROR,
        None,
        engine_version,
        "Não foi possível converter o documento.",
        code,
    )


CREATE_SUSPENDED: Final = 0x00000004
CREATE_NO_WINDOW: Final = 0x08000000
CREATE_UNICODE_ENVIRONMENT: Final = 0x00000400
STARTF_USESTDHANDLES: Final = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x00002000
JOB_OBJECT_LIMIT_JOB_MEMORY: Final = 0x00000200
JOBOBJECT_EXTENDED_LIMIT_INFORMATION: Final = 9
JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: Final = 1
WAIT_OBJECT_0: Final = 0x00000000
WAIT_TIMEOUT: Final = 0x00000102
INFINITE: Final = 0xFFFFFFFF


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _WindowsJobProcess:
    """Processo suspenso e árvore confinada a um Job Object exclusivo."""

    def __init__(self, process_handle: int, job_handle: int, process_id: int) -> None:
        self.process_handle = process_handle
        self.job_handle = job_handle
        self.process_id = process_id
        self._closed = False

    @classmethod
    def start(
        cls,
        command: Sequence[str],
        environment: Mapping[str, str],
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        *,
        memory_limit: int | None = None,
    ) -> _WindowsJobProcess:
        if os.name != "nt":
            raise OSError("Windows Job Objects estão disponíveis apenas no Windows.")
        if not command or not Path(command[0]).is_absolute():
            raise OSError("O executável deve possuir caminho absoluto.")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_kernel32(kernel32)
        startup = _STARTUPINFO()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = STARTF_USESTDHANDLES
        process_info = _PROCESS_INFORMATION()
        process_created = False
        assigned = False
        job_handle = 0
        with (
            open(os.devnull, "rb", buffering=0) as stdin_file,
            stdout_path.open("wb", buffering=0) as stdout_file,
            stderr_path.open("wb", buffering=0) as stderr_file,
        ):
            inherited = [stdin_file, stdout_file, stderr_file]
            for handle in inherited:
                os.set_handle_inheritable(msvcrt.get_osfhandle(handle.fileno()), True)
            startup.hStdInput = msvcrt.get_osfhandle(stdin_file.fileno())
            startup.hStdOutput = msvcrt.get_osfhandle(stdout_file.fileno())
            startup.hStdError = msvcrt.get_osfhandle(stderr_file.fileno())
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(command)
            )
            environment_block = _windows_environment_block(environment)
            try:
                if not kernel32.CreateProcessW(
                    str(command[0]),
                    command_line,
                    None,
                    None,
                    True,
                    CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                    ctypes.cast(environment_block, ctypes.c_void_p),
                    str(cwd),
                    ctypes.byref(startup),
                    ctypes.byref(process_info),
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                process_created = True
                job_handle = kernel32.CreateJobObjectW(None, None)
                if not job_handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                limits.BasicLimitInformation.LimitFlags = (
                    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                )
                if memory_limit is not None:
                    limits.BasicLimitInformation.LimitFlags |= (
                        JOB_OBJECT_LIMIT_JOB_MEMORY
                    )
                    limits.JobMemoryLimit = memory_limit
                if not kernel32.SetInformationJobObject(
                    job_handle,
                    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not kernel32.AssignProcessToJobObject(
                    job_handle, process_info.hProcess
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                assigned = True
                if kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
            except Exception:
                if assigned and job_handle:
                    kernel32.TerminateJobObject(job_handle, 1)
                elif process_created:
                    kernel32.TerminateProcess(process_info.hProcess, 1)
                if job_handle:
                    kernel32.CloseHandle(job_handle)
                if process_created:
                    kernel32.CloseHandle(process_info.hProcess)
                raise
            finally:
                for handle in inherited:
                    os.set_handle_inheritable(
                        msvcrt.get_osfhandle(handle.fileno()), False
                    )
                if process_created:
                    kernel32.CloseHandle(process_info.hThread)
        return cls(
            int(process_info.hProcess), int(job_handle), int(process_info.dwProcessId)
        )

    def wait(
        self, cancel_event: threading.Event, timeout_seconds: float
    ) -> _ProcessOutcome:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_kernel32(kernel32)
        deadline = time.monotonic() + timeout_seconds
        while True:
            if cancel_event.is_set():
                stopped = self.terminate()
                return _ProcessOutcome(None, cancelled=True, tree_stopped=stopped)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stopped = self.terminate()
                return _ProcessOutcome(None, timed_out=True, tree_stopped=stopped)
            wait_ms = max(
                1,
                min(int(PROCESS_POLL_INTERVAL_SECONDS * 1000), int(remaining * 1000)),
            )
            wait_result = kernel32.WaitForSingleObject(self.process_handle, wait_ms)
            if wait_result == WAIT_OBJECT_0:
                break
            if wait_result != WAIT_TIMEOUT:
                raise ctypes.WinError(ctypes.get_last_error())

        return_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(
            self.process_handle, ctypes.byref(return_code)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        while _job_active_processes(kernel32, self.job_handle):
            if cancel_event.is_set():
                stopped = self.terminate()
                return _ProcessOutcome(None, cancelled=True, tree_stopped=stopped)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stopped = self.terminate()
                return _ProcessOutcome(None, timed_out=True, tree_stopped=stopped)
            time.sleep(min(PROCESS_POLL_INTERVAL_SECONDS, remaining))
        return _ProcessOutcome(int(return_code.value), tree_stopped=True)

    def terminate(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_kernel32(kernel32)
        if not kernel32.TerminateJobObject(self.job_handle, 1):
            return False
        job_stopped = _wait_for_job_empty(
            kernel32, self.job_handle, PROCESS_TREE_SHUTDOWN_SECONDS
        )
        process_wait = kernel32.WaitForSingleObject(
            self.process_handle, int(PROCESS_TREE_SHUTDOWN_SECONDS * 1000)
        )
        return job_stopped and process_wait == WAIT_OBJECT_0

    def close(self) -> None:
        if self._closed:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_kernel32(kernel32)
        kernel32.CloseHandle(self.process_handle)
        kernel32.CloseHandle(self.job_handle)
        self._closed = True

    def __enter__(self) -> _WindowsJobProcess:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def _run_windows_job_process(
    command: Sequence[str],
    environment: Mapping[str, str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    cancel_event: threading.Event,
    timeout_seconds: float,
    *,
    memory_limit: int | None = None,
) -> _ProcessOutcome:
    if os.name != "nt":
        return _ProcessOutcome(None, tree_stopped=True)
    from contextlib import nullcontext
    from component_transactions import component_lock
    from constants import PRODUCT_EDITION, ProductEdition
    from libreoffice_managed import AcquisitionError, documents_data_root
    from paths import get_managed_components_dir

    lease = nullcontext()
    if PRODUCT_EDITION is ProductEdition.COMMUNITY:
        try:
            lease = component_lock(
                get_managed_components_dir(documents_data_root()),
                "libreoffice",
                shared=True,
            )
        except AcquisitionError:
            pass
    with lease:
        with _WindowsJobProcess.start(
            command,
            environment,
            cwd,
            stdout_path,
            stderr_path,
            memory_limit=memory_limit,
        ) as process:
            outcome = process.wait(cancel_event, timeout_seconds)
    return _ProcessOutcome(
        outcome.returncode,
        cancelled=outcome.cancelled,
        timed_out=outcome.timed_out,
        tree_stopped=outcome.tree_stopped,
        stdout=_read_limited_text(stdout_path),
        stderr=_read_limited_text(stderr_path),
    )


def _windows_environment_block(
    environment: Mapping[str, str],
) -> ctypes.Array[ctypes.c_wchar]:
    entries: list[str] = []
    for key, value in environment.items():
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ValueError("Ambiente Windows inválido.")
        entries.append(f"{key}={value}")
    entries.sort(key=str.casefold)
    return ctypes.create_unicode_buffer("\x00".join(entries) + "\x00\x00")


def _wait_for_job_empty(
    kernel32: ctypes.WinDLL, job_handle: int, timeout_seconds: float
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if _job_active_processes(kernel32, job_handle) == 0:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(PROCESS_POLL_INTERVAL_SECONDS, remaining))


def _job_active_processes(kernel32: ctypes.WinDLL, job_handle: int) -> int:
    accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    returned = wintypes.DWORD()
    if not kernel32.QueryInformationJobObject(
        job_handle,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        ctypes.byref(returned),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(accounting.ActiveProcesses)


def _read_limited_text(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(PROCESS_OUTPUT_CAPTURE_BYTES + 1)
    except OSError:
        return ""
    if len(raw) > PROCESS_OUTPUT_CAPTURE_BYTES:
        raw = raw[:PROCESS_OUTPUT_CAPTURE_BYTES]
    return raw.decode("utf-8", errors="replace")


def _configure_kernel32(kernel32: ctypes.WinDLL) -> None:
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFO),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
