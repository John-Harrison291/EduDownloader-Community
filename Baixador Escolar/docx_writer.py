"""Small generated-only OOXML subset for editable local PDF conversions.

No templates, macros, fields, external relationships or third-party XML writer.
Atomic publication belongs to the conversion service, after validation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import struct
import zlib
import tempfile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
CORE = {
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/_rels/document.xml.rels",
}
MAX_BYTES = 256 * 1024 * 1024
MAX_PAGES = 500
MAX_IMAGES = 2000
MAX_IMAGE_PIXELS = 25_000_000


def q(name):
    prefix, local = name.split(":", 1)
    return "{" + NS[prefix] + "}" + local


def node(parent, tag, **attrs):
    return ET.SubElement(
        parent,
        q(tag),
        {
            q(k) if ":" in k and not k.startswith("{") else k: str(v)
            for k, v in attrs.items()
        },
    )


def safe_text(value):
    # PDF text may contain characters forbidden by XML 1.0; preserve whitespace.
    return "".join(
        c
        for c in value
        if c in "\t\n\r"
        or 32 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD
        or 0x10000 <= ord(c) <= 0x10FFFF
    )


@dataclass(frozen=True)
class Run:
    text: str
    size: float = 12
    bold: bool = False
    italic: bool = False
    font: str = "Arial"
    color: str = "000000"
    underline: bool = False


@dataclass(frozen=True)
class PngAsset:
    """Own temporary PNG, streamed into the package instead of retained in RAM."""

    path: Path
    size: int
    digest: bytes


class ImageStore:
    def __init__(self):
        self._directory = None
        self._count = self._bytes = 0

    def add(self, data):
        validate_png(data)
        if self._count >= MAX_IMAGES or self._bytes + len(data) > MAX_BYTES:
            raise ValueError("image store limit")
        if self._directory is None:
            self._directory = tempfile.TemporaryDirectory(
                prefix="edudownloader-word-media-"
            )
        self._count += 1
        path = Path(self._directory.name) / f"image-{self._count:04}.png"
        with path.open("xb") as stream:
            stream.write(data)
        self._bytes += len(data)
        return PngAsset(path, len(data), hashlib.sha256(data).digest())

    def close(self):
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None


@dataclass(frozen=True)
class Picture:
    png: bytes | PngAsset
    width: float
    height: float
    left: float = 0
    before: float = 0
    position: tuple[float, float] | None = None


@dataclass(frozen=True)
class Paragraph:
    runs: tuple[Run, ...]
    alignment: str = "left"
    before: float = 0
    after: float = 6
    line: float = 0
    left: float = 0
    first_line: float = 0
    right: float = 0
    heading: int | None = None


@dataclass(frozen=True)
class Cell:
    column: int
    blocks: tuple
    colspan: int = 1
    rowspan: int = 1
    continuation: bool = False
    vertical: str = "top"


@dataclass(frozen=True)
class Table:
    widths: tuple[float, ...]
    rows: tuple[tuple[Cell, ...], ...]
    before: float = 0
    left: float = 0
    border: bool = True
    heights: tuple[float, ...] = ()


@dataclass(frozen=True)
class Columns:
    columns: tuple[tuple, ...]
    gap: float = 24
    before: float = 0


@dataclass(frozen=True)
class Page:
    width: float
    height: float
    blocks: tuple[Paragraph | Picture | Table | Columns, ...]
    margins: tuple[float, float, float, float] = (36, 36, 36, 36)
    header: tuple[Paragraph, ...] = ()
    footer: tuple[Paragraph, ...] = ()
    header_distance: float = 18
    footer_distance: float = 18


def section(parent, page, *, columns=1, gap=24, continuous=False, references=()):
    sect = node(parent, "w:sectPr")
    for kind, identity in references:
        node(sect, "w:" + kind + "Reference", **{"w:type": "default", "r:id": identity})
    node(sect, "w:type", **{"w:val": "continuous" if continuous else "nextPage"})
    node(
        sect,
        "w:pgSz",
        **{
            "w:w": round(page.width * 20),
            "w:h": round(page.height * 20),
            "w:orient": "landscape" if page.width > page.height else "portrait",
        },
    )
    node(
        sect,
        "w:pgMar",
        **{
            **{
                f"w:{key}": round(value * 20)
                for key, value in zip(("top", "right", "bottom", "left"), page.margins)
            },
            "w:header": round(page.header_distance * 20) if page.header else 0,
            "w:footer": round(page.footer_distance * 20) if page.footer else 0,
            "w:gutter": 0,
        },
    )
    if columns > 1:
        node(sect, "w:cols", **{"w:num": columns, "w:space": round(gap * 20)})


def text_run(paragraph, item):
    run = node(paragraph, "w:r")
    props = node(run, "w:rPr")
    if item.font not in {
        "Arial",
        "Times New Roman",
        "Courier New",
        "Calibri",
        "Cambria",
        "Verdana",
        "Tahoma",
        "Segoe UI",
        "Symbol",
    }:
        raise ValueError("unsupported font")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", item.color):
        raise ValueError("font color")
    node(props, "w:rFonts", **{"w:ascii": item.font, "w:hAnsi": item.font})
    if item.color != "000000":
        node(props, "w:color", **{"w:val": item.color.upper()})
    if item.underline:
        node(props, "w:u", **{"w:val": "single"})
    if item.bold:
        node(props, "w:b")
    if item.italic:
        node(props, "w:i")
    if not math.isfinite(item.size) or not 6 <= item.size <= 96:
        raise ValueError("font size")
    node(props, "w:sz", **{"w:val": round(item.size * 2)})
    for part in re.split(
        r"([\t\n])", safe_text(item.text).replace("\r\n", "\n").replace("\r", "\n")
    ):
        if part in ("\t", "\n"):
            node(run, "w:tab" if part == "\t" else "w:br")
        elif part:
            node(run, "w:t", **{XML_SPACE: "preserve"}).text = part


def picture_run(paragraph, picture, number, page, relationship=None):
    if isinstance(picture.png, PngAsset):
        with picture.png.path.open("rb") as stream:
            header = stream.read(8)
    else:
        header = picture.png[:8]
    if header != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG required")
    if not all(math.isfinite(x) and x > 0 for x in (picture.width, picture.height)):
        raise ValueError("image size")
    scale = (
        1
        if picture.position is not None
        else min(
            1, (page.width - 72) / picture.width, (page.height - 96) / picture.height
        )
    )
    cx, cy = round(picture.width * scale * 12700), round(picture.height * scale * 12700)
    inline = node(
        node(node(paragraph, "w:r"), "w:drawing"),
        "wp:anchor" if picture.position is not None else "wp:inline",
        distT=0,
        distB=0,
        distL=0,
        distR=0,
    )
    if picture.position is not None:
        x, y = picture.position
        if (
            not all(math.isfinite(v) and v >= 0 for v in (x, y))
            or x + picture.width > page.width + 1
            or y + picture.height > page.height + 1
        ):
            raise ValueError("anchored image position")
        inline.attrib.update(
            simplePos="0",
            relativeHeight="0",
            behindDoc="1",
            locked="0",
            layoutInCell="1",
            allowOverlap="1",
        )
        node(inline, "wp:simplePos", x=0, y=0)
        for tag, offset in (("wp:positionH", x), ("wp:positionV", y)):
            node(node(inline, tag, relativeFrom="page"), "wp:posOffset").text = str(
                round(offset * 12700)
            )
    node(inline, "wp:extent", cx=cx, cy=cy)
    if picture.position is not None:
        node(inline, "wp:wrapNone")
    node(
        inline,
        "wp:docPr",
        id=number,
        name=f"Image {number}",
        descr="Image extracted from PDF",
    )
    node(node(inline, "wp:cNvGraphicFramePr"), "a:graphicFrameLocks", noChangeAspect=1)
    graphic = node(node(inline, "a:graphic"), "a:graphicData", uri=NS["pic"])
    pic = node(graphic, "pic:pic")
    nonvisual = node(pic, "pic:nvPicPr")
    node(nonvisual, "pic:cNvPr", id=number, name=f"image{number}.png")
    node(nonvisual, "pic:cNvPicPr")
    fill = node(pic, "pic:blipFill")
    node(fill, "a:blip", **{"r:embed": relationship or f"rId{number}"})
    node(node(fill, "a:stretch"), "a:fillRect")
    props = node(pic, "pic:spPr")
    transform = node(props, "a:xfrm")
    node(transform, "a:off", x=0, y=0)
    node(transform, "a:ext", cx=cx, cy=cy)
    node(node(props, "a:prstGeom", prst="rect"), "a:avLst")


def package_parts(pages: list[Page], check_cancel=lambda: None):
    if not pages or len(pages) > MAX_PAGES:
        raise ValueError("page limit")
    document = ET.Element(q("w:document"))
    body = node(document, "w:body")
    rels = ET.Element(q("pr:Relationships"))
    media, expected = {}, []
    story_roots, story_text = {}, {}
    image_ids = {}
    drawing_count = 0
    story_kinds = [
        kind
        for kind in ("header", "footer")
        if any(getattr(page, kind) for page in pages)
    ]

    def paragraph(parent, block):
        p = node(parent, "w:p")
        props = node(p, "w:pPr")
        for value in (
            block.before,
            block.after,
            block.line,
            block.left,
            block.right,
            block.first_line,
        ):
            if not math.isfinite(value) or abs(value) > 1440:
                raise ValueError("paragraph geometry")
        spacing = {
            "w:before": round(max(0, block.before) * 20),
            "w:after": round(max(0, block.after) * 20),
        }
        spacing.update(
            {"w:line": round(block.line * 20), "w:lineRule": "atLeast"}
            if block.line
            else {"w:line": 240, "w:lineRule": "auto"}
        )
        node(props, "w:spacing", **spacing)
        if block.left or block.right or block.first_line:
            indentation = {
                "w:left": round(max(0, block.left) * 20),
                "w:right": round(max(0, block.right) * 20),
            }
            indentation["w:firstLine" if block.first_line >= 0 else "w:hanging"] = (
                round(abs(block.first_line) * 20)
            )
            node(props, "w:ind", **indentation)
        if block.heading is not None:
            if not 0 <= block.heading <= 8:
                raise ValueError("heading level")
            node(props, "w:outlineLvl", **{"w:val": block.heading})
            node(props, "w:keepNext")
        if block.alignment not in {"left", "center", "right", "both"}:
            raise ValueError("alignment")
        node(props, "w:jc", **{"w:val": block.alignment})
        mark = node(props, "w:rPr")
        node(
            mark,
            "w:rFonts",
            **{
                "w:ascii": block.runs[0].font if block.runs else "Arial",
                "w:hAnsi": block.runs[0].font if block.runs else "Arial",
            },
        )
        node(
            mark,
            "w:sz",
            **{"w:val": round(block.runs[0].size * 2) if block.runs else 2},
        )
        for item in block.runs:
            text_run(p, item)
            expected.append(
                safe_text(item.text).replace("\r\n", "\n").replace("\r", "\n")
            )
        return props

    def emit(parent, block, page):
        nonlocal section_continuous, drawing_count
        check_cancel()
        if isinstance(block, Table):
            if not 2 <= len(block.widths) <= 64 or not 1 <= len(block.rows) <= 2000:
                raise ValueError("table bounds")
            if not all(math.isfinite(x) and x > 0 for x in block.widths):
                raise ValueError("table widths")
            if block.before:
                paragraph(parent, Paragraph((), before=block.before, after=0, line=1))
            table = node(parent, "w:tbl")
            props = node(table, "w:tblPr")
            node(
                props,
                "w:tblW",
                **{"w:w": round(sum(block.widths) * 20), "w:type": "dxa"},
            )
            node(
                props,
                "w:tblInd",
                **{"w:w": round(max(0, block.left) * 20), "w:type": "dxa"},
            )
            node(props, "w:tblLayout", **{"w:type": "fixed"})
            borders = node(props, "w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                node(
                    borders,
                    "w:" + side,
                    **{
                        "w:val": "single" if block.border else "nil",
                        "w:sz": 4,
                        "w:color": "444444",
                    },
                )
            margins = node(props, "w:tblCellMar")
            for side in ("top", "bottom", "left", "right"):
                node(margins, "w:" + side, **{"w:w": 60, "w:type": "dxa"})
            grid = node(table, "w:tblGrid")
            for width in block.widths:
                node(grid, "w:gridCol", **{"w:w": round(width * 20)})
            for number, cells in enumerate(block.rows):
                check_cancel()
                row = node(table, "w:tr")
                rowprops = node(row, "w:trPr")
                node(rowprops, "w:cantSplit")
                if block.heights:
                    height = block.heights[number]
                    if not math.isfinite(height) or not 0 < height <= 1440:
                        raise ValueError("row height")
                    node(
                        rowprops,
                        "w:trHeight",
                        # Word adds the top/bottom cell margins to this minimum.
                        **{
                            "w:val": round(max(1, height - 6) * 20),
                            "w:hRule": "atLeast",
                        },
                    )
                column = 0
                for cell in cells:
                    if (
                        cell.column != column
                        or cell.colspan < 1
                        or column + cell.colspan > len(block.widths)
                        or not 1 <= cell.rowspan <= len(block.rows) - number
                    ):
                        raise ValueError("cell span")
                    target = node(row, "w:tc")
                    cellprops = node(target, "w:tcPr")
                    node(
                        cellprops,
                        "w:tcW",
                        **{
                            "w:w": round(
                                sum(block.widths[column : column + cell.colspan]) * 20
                            ),
                            "w:type": "dxa",
                        },
                    )
                    if cell.colspan > 1:
                        node(cellprops, "w:gridSpan", **{"w:val": cell.colspan})
                    if cell.vertical not in {"top", "center", "bottom"}:
                        raise ValueError("cell alignment")
                    node(cellprops, "w:vAlign", **{"w:val": cell.vertical})
                    if cell.rowspan > 1 or cell.continuation:
                        node(
                            cellprops,
                            "w:vMerge",
                            **{"w:val": "continue" if cell.continuation else "restart"},
                        )
                    for item in cell.blocks or (Paragraph((), after=0),):
                        if not isinstance(item, (Paragraph, Picture)):
                            raise ValueError("nested structure")
                        emit(target, item, page)
                    if target[-1].tag != q("w:p"):
                        paragraph(target, Paragraph((), after=0, line=1))
                    column += cell.colspan
                if column != len(block.widths):
                    raise ValueError("incomplete row")
            return paragraph(parent, Paragraph((), after=0, line=1))
        if isinstance(block, Columns):
            if not 2 <= len(block.columns) <= 3 or not 0 <= block.gap <= 144:
                raise ValueError("columns")
            if block.before:
                # Word discards spacing/height on a continuous section-break
                # paragraph. Keep source whitespace in its own flow paragraph.
                paragraph(parent, Paragraph((), after=0, line=block.before))
            props = paragraph(parent, Paragraph((), after=0, line=1))
            section(
                props,
                page,
                continuous=section_continuous,
                references=current_references,
            )
            for number, items in enumerate(block.columns):
                for item in items:
                    if isinstance(item, Columns):
                        raise ValueError("nested columns")
                    props = emit(parent, item, page)
                if number < len(block.columns) - 1:
                    paragraph(parent, Paragraph((), after=0, line=1))
                    p = parent[-1]
                    node(node(p, "w:r"), "w:br", **{"w:type": "column"})
                    expected.append("\n")
            props = paragraph(parent, Paragraph((), after=0, line=1))
            section(
                props,
                page,
                columns=len(block.columns),
                gap=block.gap,
                continuous=True,
                references=current_references,
            )
            section_continuous = True
            return props
        if isinstance(block, Picture):
            props = paragraph(
                parent,
                Paragraph(
                    (),
                    before=block.before,
                    after=0,
                    line=1 if block.position is not None else 0,
                    left=block.left,
                ),
            )
            p = parent[-1]
            drawing_count += 1
            if drawing_count > MAX_IMAGES:
                raise ValueError("image count")
            digest = (
                block.png.digest
                if isinstance(block.png, PngAsset)
                else hashlib.sha256(block.png).digest()
            )
            if digest not in image_ids:
                number = len(media) + 1
                name = f"media/image{number}.png"
                media["word/" + name] = block.png
                image_ids[digest] = f"rId{number}"
                node(
                    rels,
                    "pr:Relationship",
                    Id=image_ids[digest],
                    Type=NS["r"] + "/image",
                    Target=name,
                )
            picture_run(p, block, drawing_count, page, image_ids[digest])
            return props
        if not isinstance(block, Paragraph):
            raise ValueError("block type")
        return paragraph(parent, block)

    for index, page in enumerate(pages):
        check_cancel()
        section_continuous = False
        current_references = []
        if not all(
            math.isfinite(x) and 144 <= x <= 1440 for x in (page.width, page.height)
        ):
            raise ValueError("page dimensions")
        if len(page.margins) != 4 or not all(
            math.isfinite(x) and 0 <= x <= 144 for x in page.margins
        ):
            raise ValueError("margins")
        for kind in story_kinds:
            identity = f"rId{kind[0].upper()}{index + 1}"
            name = f"word/{kind}{index + 1}.xml"
            root = ET.Element(q("w:hdr" if kind == "header" else "w:ftr"))
            start = len(expected)
            for block in getattr(page, kind) or (Paragraph((), after=0, line=1),):
                if not isinstance(block, Paragraph):
                    raise ValueError("unsupported header/footer")
                paragraph(root, block)
            story_roots[name] = root
            story_text[name] = "".join(expected[start:])
            del expected[start:]
            current_references.append((kind, identity))
            node(
                rels,
                "pr:Relationship",
                Id=identity,
                Type=NS["r"] + "/" + kind,
                Target=name.removeprefix("word/"),
            )
        for block in page.blocks or (Paragraph(()),):
            props = emit(body, block, page)
        # Section properties on the last paragraph describe the section ending
        # here; final body sectPr describes the last section. No extra blank page.
        section(
            props if index < len(pages) - 1 else body,
            page,
            continuous=section_continuous,
            references=current_references,
        )
    types = ET.Element(q("ct:Types"))
    node(types, "ct:Default", Extension="rels", ContentType=RELS_TYPE)
    node(types, "ct:Default", Extension="xml", ContentType="application/xml")
    if media:
        node(types, "ct:Default", Extension="png", ContentType="image/png")
    node(types, "ct:Override", PartName="/word/document.xml", ContentType=DOCUMENT_TYPE)
    for name in sorted(story_roots):
        kind = "header" if "/header" in name else "footer"
        node(
            types,
            "ct:Override",
            PartName="/" + name,
            ContentType=f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml",
        )
    root_rels = ET.Element(q("pr:Relationships"))
    node(
        root_rels,
        "pr:Relationship",
        Id="rId1",
        Type=NS["r"] + "/officeDocument",
        Target="word/document.xml",
    )
    roots = {
        "[Content_Types].xml": types,
        "_rels/.rels": root_rels,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": rels,
        **story_roots,
    }
    parts = {}
    for name, root in roots.items():
        if name in {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/_rels/document.xml.rels",
        }:
            # Writer 26.2's package discovery rejects prefixed OPC containers.
            # Use the conventional default namespace, without templates or
            # process-global namespace mutation during serialization.
            namespace = root.tag[1:].split("}")[0]
            for element in root.iter():
                element.tag = element.tag.split("}", 1)[1]
            root.set("xmlns", namespace)
        parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parts.update(media)
    if (
        sum(
            data.size if isinstance(data, PngAsset) else len(data)
            for data in parts.values()
        )
        > MAX_BYTES
    ):
        raise ValueError("output budget")
    return parts, "".join(expected) + "".join(
        story_text[name] for name in sorted(story_text)
    )


def validate(path, expected_text=None, check_cancel=lambda: None):
    """Check our output subset, not arbitrary imported DOCX or full ISO schema."""
    if not 0 < Path(path).stat().st_size <= MAX_BYTES:
        raise ValueError("output size")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = set(archive.namelist())
        if (
            len(entries) != len(names)
            or len(entries) > MAX_IMAGES + 4 + MAX_PAGES * 2
            or not CORE <= names
        ):
            raise ValueError("package structure")
        if sum(x.file_size for x in entries) > MAX_BYTES:
            raise ValueError("ZIP integrity")
        stories = {
            n
            for n in names
            if re.fullmatch(r"word/(?:header|footer)[1-9][0-9]*\.xml", n)
        }
        if len(stories) > MAX_PAGES * 2 or any(
            n not in CORE | stories
            and not re.fullmatch(r"word/media/image[1-9][0-9]*\.png", n)
            for n in names
        ):
            raise ValueError("unexpected part or unsafe path")
        for entry in entries:
            check_cancel()
            if entry.flag_bits & 1:
                raise ValueError("encrypted ZIP member")
            with archive.open(entry) as stream:
                while stream.read(1024 * 1024):
                    check_cancel()  # ZipExtFile checks CRC at EOF.
        trees = {}
        for name in CORE | stories:
            data = archive.read(name)
            if b"<!" in data or not data.startswith(b"<?xml"):
                raise ValueError("DTD/entities/declarations not supported")
            trees[name] = ET.fromstring(data)
        for filename, tag in (
            ("[Content_Types].xml", "ct:Types"),
            ("_rels/.rels", "pr:Relationships"),
            ("word/_rels/document.xml.rels", "pr:Relationships"),
        ):
            if trees[filename].tag != q(tag) or trees[filename].attrib:
                raise ValueError("package root")
        root_rel = list(trees["_rels/.rels"])
        if (
            len(root_rel) != 1
            or root_rel[0].tag != q("pr:Relationship")
            or root_rel[0].attrib
            != {
                "Id": "rId1",
                "Type": NS["r"] + "/officeDocument",
                "Target": "word/document.xml",
            }
        ):
            raise ValueError("root relationship")
        ids = {}
        story_ids = {}
        for rel in trees["word/_rels/document.xml.rels"]:
            rid, target = rel.get("Id"), rel.get("Target", "")
            kind = "header" if target.startswith("header") else "footer"
            if "word/" + target in stories:
                if (
                    rel.tag != q("pr:Relationship")
                    or set(rel.attrib) != {"Id", "Type", "Target"}
                    or not re.fullmatch(r"rId[HF][1-9][0-9]*", rid or "")
                    or rid in story_ids
                    or rel.get("Type") != NS["r"] + "/" + kind
                ):
                    raise ValueError("header/footer relationship")
                story_ids[rid] = (kind, "word/" + target)
                continue
            if (
                rel.tag != q("pr:Relationship")
                or set(rel.attrib) != {"Id", "Type", "Target"}
                or rid in ids
                or not re.fullmatch(r"rId[1-9][0-9]*", rid or "")
                or not re.fullmatch(r"media/image[1-9][0-9]*\.png", target)
                or "word/" + target not in names
                or rel.get("Type") != NS["r"] + "/image"
            ):
                raise ValueError("image relationship")
            ids[rid] = target
        root = trees["word/document.xml"]
        allowed = {
            q(x)
            for x in "w:document w:body w:p w:pPr w:jc w:spacing w:r w:rPr w:rFonts w:b w:i w:sz w:t w:tab w:br w:sectPr w:type w:pgSz w:pgMar w:drawing wp:inline wp:extent wp:docPr wp:cNvGraphicFramePr a:graphicFrameLocks a:graphic a:graphicData pic:pic pic:nvPicPr pic:cNvPr pic:cNvPicPr pic:blipFill a:blip a:stretch a:fillRect pic:spPr a:xfrm a:off a:ext a:prstGeom a:avLst".split()
        }
        allowed.update(
            q(x)
            for x in "w:color w:u w:ind w:outlineLvl w:keepNext w:cols w:tbl w:tblPr w:tblW w:tblInd w:tblLayout w:tblBorders w:top w:left w:bottom w:right w:insideH w:insideV w:tblCellMar w:tblGrid w:gridCol w:tr w:trPr w:cantSplit w:trHeight w:tc w:tcPr w:tcW w:gridSpan w:vMerge w:vAlign".split()
        )
        allowed.update(
            q(x)
            for x in "wp:anchor wp:simplePos wp:positionH wp:positionV wp:posOffset wp:wrapNone".split()
        )
        allowed.update(
            q(tag)
            for tag in ("w:hdr", "w:ftr", "w:headerReference", "w:footerReference")
        )
        if root.tag != q("w:document") or any(
            element.tag not in allowed for element in root.iter()
        ):
            raise ValueError("unsupported document content")
        _validate_attributes(root)
        for anchor in root.iter(q("wp:anchor")):
            required = [
                "wp:simplePos",
                "wp:positionH",
                "wp:positionV",
                "wp:extent",
                "wp:wrapNone",
                "wp:docPr",
                "wp:cNvGraphicFramePr",
                "a:graphic",
            ]
            if [child.tag for child in anchor] != [
                q(tag) for tag in required
            ] or anchor.get("behindDoc") != "1":
                raise ValueError("anchor structure")
            for tag in ("wp:positionH", "wp:positionV"):
                position = anchor.find(tag, NS)
                if (
                    position.get("relativeFrom") != "page"
                    or len(position) != 1
                    or position[0].tag != q("wp:posOffset")
                    or not re.fullmatch(r"[0-9]{1,9}", position[0].text or "")
                ):
                    raise ValueError("anchor position")
        for name in stories:
            story = trees[name]
            if (
                story.tag != q("w:hdr" if "/header" in name else "w:ftr")
                or story.attrib
                or any(el.tag not in allowed for el in story.iter())
            ):
                raise ValueError("header/footer content")
            _validate_attributes(story)
            if any(el.tag in {q("w:drawing"), q("w:sectPr")} for el in story.iter()):
                raise ValueError("unsupported header/footer structure")
        references = [
            (
                "header" if el.tag == q("w:headerReference") else "footer",
                el.get(q("r:id")),
            )
            for el in root.iter()
            if el.tag in {q("w:headerReference"), q("w:footerReference")}
        ]
        if (
            any(
                rid not in story_ids or story_ids[rid][0] != kind
                for kind, rid in references
            )
            or {rid for _, rid in references} != set(story_ids)
            or {name for _, name in story_ids.values()} != stories
        ):
            raise ValueError("unresolved header/footer")
        if (
            len(root) != 1
            or root[0].tag != q("w:body")
            or not len(root[0])
            or root[0][-1].tag != q("w:sectPr")
        ):
            raise ValueError("document body/section")
        refs = [element.get(q("r:embed")) for element in root.iter(q("a:blip"))]
        if (
            len(refs) > MAX_IMAGES
            or set(refs) != set(ids)
            or names - CORE - stories != {"word/" + t for t in ids.values()}
        ):
            raise ValueError("unresolved or unused image")
        types = trees["[Content_Types].xml"]
        expected_types = [
            (q("ct:Default"), {"Extension": "rels", "ContentType": RELS_TYPE}),
            (q("ct:Default"), {"Extension": "xml", "ContentType": "application/xml"}),
        ]
        if ids:
            expected_types.append(
                (q("ct:Default"), {"Extension": "png", "ContentType": "image/png"})
            )
        expected_types.append(
            (
                q("ct:Override"),
                {"PartName": "/word/document.xml", "ContentType": DOCUMENT_TYPE},
            )
        )
        for name in sorted(stories):
            kind = "header" if "/header" in name else "footer"
            expected_types.append(
                (
                    q("ct:Override"),
                    {
                        "PartName": "/" + name,
                        "ContentType": f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml",
                    },
                )
            )
        if [(el.tag, el.attrib) for el in types] != expected_types:
            raise ValueError("content types")
        for target in ids.values():
            check_cancel()
            validate_png(archive.read("word/" + target))
        text = "".join(
            (el.text or "")
            if el.tag == q("w:t")
            else "\t"
            if el.tag == q("w:tab")
            else "\n"
            if el.tag == q("w:br")
            else ""
            for tree in [root] + [trees[name] for name in sorted(stories)]
            for el in tree.iter()
        )
        if not text.strip() or (expected_text is not None and text != expected_text):
            raise ValueError("text missing or changed")
        return {
            "text": text,
            "paragraphs": len(list(root.iter(q("w:p")))),
            "images": len(refs),
            "unique_images": len(ids),
            "sections": len(list(root.iter(q("w:sectPr")))),
        }


def save_parts(parts, stream, check_cancel=lambda: None):
    """Write generated parts only; the caller owns the adjacent temporary file."""
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            check_cancel()
            if isinstance(data, PngAsset):
                if (
                    data.path.is_symlink()
                    or data.path.is_junction()
                    or data.path.stat().st_size != data.size
                ):
                    raise OSError("temporary image changed")
                digest = hashlib.sha256()
                copied = 0
                with data.path.open("rb") as source, archive.open(name, "w") as target:
                    while chunk := source.read(1024 * 1024):
                        check_cancel()
                        copied += len(chunk)
                        if copied > data.size:
                            raise OSError("temporary image changed")
                        digest.update(chunk)
                        target.write(chunk)
                if copied != data.size or digest.digest() != data.digest:
                    raise OSError("temporary image changed")
            else:
                archive.writestr(name, data)


def validate_png(data):
    """Bounded PNG chunk/CRC check; never accept executable or trailing payload."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG signature")
    cursor, count, has_data = 8, 0, False
    while cursor + 12 <= len(data):
        length = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4 : cursor + 8]
        end = cursor + 12 + length
        if end > len(data):
            raise ValueError("PNG chunk length")
        content = data[cursor + 8 : end - 4]
        if zlib.crc32(kind + content) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("PNG CRC")
        if count == 0:
            if kind != b"IHDR" or length != 13:
                raise ValueError("PNG header")
            width, height = struct.unpack_from(">II", content)
            if not 0 < width * height <= MAX_IMAGE_PIXELS:
                raise ValueError("PNG dimensions")
        elif kind == b"IHDR":
            raise ValueError("duplicate PNG header")
        if kind == b"IDAT":
            has_data = True
        if kind == b"IEND":
            if length or end != len(data) or not has_data:
                raise ValueError("PNG end")
            return
        cursor, count = end, count + 1
    raise ValueError("incomplete PNG")


def _validate_attributes(root):
    attributes = {
        "w:spacing": "w:before w:after w:line w:lineRule",
        "w:rFonts": "w:ascii w:hAnsi",
        "w:sz": "w:val",
        "w:color": "w:val",
        "w:u": "w:val",
        "w:ind": "w:left w:right w:firstLine w:hanging",
        "w:outlineLvl": "w:val",
        "w:cols": "w:num w:space",
        "w:br": "w:type",
        "w:tblW": "w:w w:type",
        "w:tblInd": "w:w w:type",
        "w:tblLayout": "w:type",
        "w:gridCol": "w:w",
        "w:trHeight": "w:val w:hRule",
        "w:tcW": "w:w w:type",
        "w:gridSpan": "w:val",
        "w:vMerge": "w:val",
        "w:vAlign": "w:val",
        "w:headerReference": "w:type r:id",
        "w:footerReference": "w:type r:id",
        **{
            f"w:{side}": "w:w w:type w:val w:sz w:color"
            for side in ("top", "left", "bottom", "right", "insideH", "insideV")
        },
        "w:jc": "w:val",
        "w:type": "w:val",
        "w:pgSz": "w:w w:h w:orient",
        "w:pgMar": "w:top w:right w:bottom w:left w:header w:footer w:gutter",
        "wp:inline": "distT distB distL distR",
        "wp:anchor": "distT distB distL distR simplePos relativeHeight behindDoc locked layoutInCell allowOverlap",
        "wp:simplePos": "x y",
        "wp:positionH": "relativeFrom",
        "wp:positionV": "relativeFrom",
        "wp:extent": "cx cy",
        "wp:docPr": "id name descr",
        "a:graphicFrameLocks": "noChangeAspect",
        "a:graphicData": "uri",
        "pic:cNvPr": "id name",
        "a:blip": "r:embed",
        "a:off": "x y",
        "a:ext": "cx cy",
        "a:prstGeom": "prst",
    }
    permitted = {
        q(tag): {q(a) if ":" in a else a for a in names.split()}
        for tag, names in attributes.items()
    }
    permitted[q("w:t")] = {XML_SPACE}
    for element in root.iter():
        if set(element.attrib) - permitted.get(element.tag, set()):
            raise ValueError("unsupported attribute")
        if element.tag == q("a:blip") and set(element.attrib) != {q("r:embed")}:
            raise ValueError("external or missing image embed")
        if element.tag == q("a:graphicData") and element.get("uri") != NS["pic"]:
            raise ValueError("unsupported graphic")
