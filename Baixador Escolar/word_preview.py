"""Leitura limitada de DOCX e ODT e verificação para a prévia local."""

from pathlib import PurePosixPath
from posixpath import normpath
import re
import stat
import zipfile
from xml.etree import ElementTree as ET
from urllib.parse import unquote, urlsplit

from file_preview import (
    FilePreviewResult,
    PreviewKind,
    PreviewStatus,
    PreviewCancelled,
    preview_checkpoint,
)

MAX_DOCX_BYTES = 16 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_MEMBERS = 512
MAX_ELEMENTS = 20_000
MAX_TEXT = 20_000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_ODT_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODT_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_EXTERNAL_FIELDS = re.compile(
    r"\b(?:DDE(?:AUTO)?|INCLUDE(?:TEXT|PICTURE)|LINK|DATABASE|HYPERLINK|RD|IMPORT)\b",
    re.IGNORECASE,
)


def require_offline_document(path, cancel):
    """Rejeita pacotes com vínculos externos ou conteúdo ativo antes do LibreOffice."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = {info.filename for info in entries}
        if (
            len(entries) > MAX_MEMBERS
            or len(names) != len(entries)
            or sum(info.file_size for info in entries) > 64 * 1024 * 1024
        ):
            raise WordLimit
        xml_bytes = 0
        for info in entries:
            name = info.filename.casefold()
            if (
                name.startswith("/")
                or "\\" in name
                or ":" in name
                or ".." in name.split("/")
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError("Entrada do documento inválida")
            if any(
                part in {"activex", "embeddings", "basic", "scripts", "externallinks"}
                for part in name.split("/")
            ) or name.endswith("vbaproject.bin"):
                raise ValueError("Documento com conteúdo ativo")
            if not name.endswith((".xml", ".rels")):
                continue
            xml_bytes += info.file_size
            if xml_bytes > 2 * MAX_XML_BYTES:
                raise WordLimit
            parts = _xml(archive, info.filename, cancel)
            instructions = []
            for element in parts.iter():
                tag = element.tag.rsplit("}", 1)[-1].casefold()
                if tag in {
                    "oleobject",
                    "object",
                    "object-ole",
                    "plugin",
                    "script",
                    "event-listener",
                    "include",
                }:
                    raise ValueError("Documento com conteúdo ativo")
                if tag == "instrtext":
                    instructions.append(element.text or "")
                for attribute, value in element.attrib.items():
                    local = attribute.rsplit("}", 1)[-1].casefold()
                    if local == "targetmode" and value.casefold() != "internal":
                        raise ValueError("Documento com vínculo externo")
                    if local == "base":
                        raise ValueError("Base de endereços externa")
                    if local == "instr":
                        instructions.append(value)
                    if local not in {"href", "target"}:
                        continue
                    _require_package_target(info.filename, value, names)
            if _EXTERNAL_FIELDS.search("".join(instructions)) or any(
                _EXTERNAL_FIELDS.search(instruction) for instruction in instructions
            ):
                raise ValueError("Documento com campo externo")


def _require_package_target(part, value, names):
    target = unquote(value)
    if re.search(r"[\x00-\x1f\x7f\\%]", target) or target != target.strip():
        raise ValueError("Documento com vínculo inválido")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or target.startswith("//"):
        raise ValueError("Documento com vínculo externo")
    if not parsed.path and target.startswith("#"):
        return
    owner = PurePosixPath(part).parent
    relationship = part.casefold().endswith(".rels") and owner.name == "_rels"
    if relationship:
        owner = owner.parent
    relative = parsed.path
    if not relative or (relative.startswith("/") and not relationship):
        raise ValueError("Documento com vínculo externo")
    member = (
        normpath(relative.lstrip("/"))
        if relative.startswith("/")
        else normpath((owner / relative).as_posix())
    )
    if member not in names and member + "/" not in names:
        raise ValueError("Vínculo fora do pacote do documento")


def preview_odt(path, cancel=None):
    try:
        with zipfile.ZipFile(path) as archive:
            mime = b"application/vnd.oasis.opendocument.text"
            if archive.getinfo("mimetype").file_size != len(mime) or archive.read(
                "mimetype"
            ) != (mime):
                raise ValueError("Formato ODT inválido")
            root = _xml(archive, "content.xml", cancel)
            body = root.find(f"{_ODT_OFFICE}body/{_ODT_OFFICE}text")
            if body is None:
                raise ValueError("ODT sem corpo")
            lines = []
            length = 0
            for item in body.iter():
                if item.tag not in {_ODT_TEXT + "p", _ODT_TEXT + "h"}:
                    continue
                line = "".join(item.itertext())
                remaining = max(0, MAX_TEXT - length)
                lines.append(line[:remaining])
                length += len(line) + 1
                if length > MAX_TEXT:
                    break
            text = "\n".join(lines).strip()
            return FilePreviewResult(
                PreviewStatus.SUCCESS,
                kind=PreviewKind.WORD_TEXT,
                text=text,
                truncated=length > MAX_TEXT,
                message="Documento sem texto extraível." if not text else None,
            )
    except PreviewCancelled:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        ET.ParseError,
        zipfile.BadZipFile,
        RuntimeError,
    ):
        return FilePreviewResult(
            PreviewStatus.INVALID,
            message="Documento ODT inválido ou incompatível. Use Abrir.",
        )


class WordLimit(ValueError):
    pass


def _xml(archive, name, cancel, limit=MAX_XML_BYTES):
    preview_checkpoint(cancel)
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise WordLimit
    with archive.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise WordLimit
    declarations = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("DTD/entities are not supported")
    parser = ET.XMLPullParser(events=("start", "end"))
    root, count, depth = None, 0, 0
    for offset in range(0, len(data), 4096):
        preview_checkpoint(cancel)
        parser.feed(data[offset : offset + 4096])
        for event, element in parser.read_events():
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                count += 1
                if depth > 64 or count > MAX_ELEMENTS:
                    raise WordLimit
            else:
                depth -= 1
    parser.close()
    if root is None:
        raise ValueError("Empty XML")
    return root


def _paragraph(element):
    pieces = []
    for item in element.iter():
        if item.tag == W + "t":
            pieces.append(item.text or "")
        elif item.tag == W + "tab":
            pieces.append("\t")
        elif item.tag in (W + "br", W + "cr"):
            pieces.append("\n")
    return "".join(pieces)


def _lines(parent, cancel):
    for element in parent:
        preview_checkpoint(cancel)
        if element.tag == W + "p":
            yield _paragraph(element)
        elif element.tag == W + "tbl":
            for row in element.findall(W + "tr"):
                yield "\t".join(
                    "\n".join(_lines(cell, cancel)) for cell in row.findall(W + "tc")
                )
        elif element.tag not in (W + "sectPr", W + "pPr"):
            yield from _lines(element, cancel)


def preview_word(path, cancel=None):
    try:
        if path.stat().st_size > MAX_DOCX_BYTES:
            raise WordLimit
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if (
                len(infos) > MAX_MEMBERS
                or sum(i.file_size for i in infos) > 32 * 1024 * 1024
            ):
                raise WordLimit
            names = set()
            for info in infos:
                preview_checkpoint(cancel)
                name = PurePosixPath(info.filename)
                if (
                    info.filename in names
                    or name.is_absolute()
                    or ".." in name.parts
                    or "\\" in info.filename
                    or ":" in info.filename
                ):
                    raise ValueError("Unsafe package names")
                names.add(info.filename)
                if (
                    info.flag_bits & 1
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or info.compress_type
                    not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                ):
                    raise ValueError("Unsupported package entry")
                if info.file_size > max(1, info.compress_size) * 200:
                    raise WordLimit
            types = _xml(archive, "[Content_Types].xml", cancel, 64 * 1024)
            if not any(
                e.get("PartName") == "/word/document.xml"
                and e.get("ContentType") == MAIN_TYPE
                for e in types
            ):
                raise ValueError("Not a standard DOCX")
            document = _xml(archive, "word/document.xml", cancel, MAX_XML_BYTES)
            if document.tag != W + "document" or document.find(W + "body") is None:
                raise ValueError("No Word document body")
            text, truncated = "", False
            for line in _lines(document.find(W + "body"), cancel):
                addition = ("\n" if text else "") + line
                remaining = MAX_TEXT - len(text)
                text += addition[:remaining]
                if len(addition) > remaining:
                    truncated = True
                    break
            title = ""
            if "docProps/core.xml" in names:
                try:
                    props = _xml(archive, "docProps/core.xml", cancel, 64 * 1024)
                    title = (
                        props.findtext("{http://purl.org/dc/elements/1.1/}title") or ""
                    )[:256]
                except (ValueError, KeyError, ET.ParseError):
                    pass
            return FilePreviewResult(
                PreviewStatus.SUCCESS,
                kind=PreviewKind.WORD_TEXT,
                text=text if text.strip() else "",
                title=title,
                truncated=truncated,
                message="Documento sem texto extraível." if not text.strip() else None,
            )
    except PreviewCancelled:
        raise
    except WordLimit:
        return FilePreviewResult(
            PreviewStatus.TOO_LARGE,
            message="O documento excede os limites seguros da prévia textual. Use Abrir.",
        )
    except (
        OSError,
        ValueError,
        KeyError,
        ET.ParseError,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
    ):
        return FilePreviewResult(
            PreviewStatus.INVALID,
            message="Documento Word inválido, protegido ou incompatível. Use Abrir.",
        )
