"""Synthetic school documents; no operator data or third-party source assets."""

from pypdf import PdfWriter
from pypdf.generic import (
    DictionaryObject,
    NameObject,
    NumberObject,
    DecodedStreamObject,
)
from PIL import Image, ImageDraw


def make_pdf(
    path,
    *,
    count=1,
    image=False,
    scanned=(),
    table=False,
    landscape=(),
    reverse=False,
    text_lines=None,
):
    writer = PdfWriter()
    expected = []
    for index in range(count):
        width, height = (842, 595) if index in landscape else (595, 842)
        page = writer.add_blank_page(width, height)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        lines = [
            (48, height - 60, 20, f"Ciências página {index + 1}"),
            (48, height - 95, 14, "Atividade sobre educação e água"),
            (48, height - 135, 12, "Primeiro parágrafo com atenção e acentuação."),
            (48, height - 151, 12, "Continuação da mesma ideia para a turma."),
            (48, height - 182, 12, "Segundo parágrafo com observações independentes."),
            (48, height - 214, 12, "Terceiro parágrafo para revisão dos alunos."),
        ]
        if table:
            lines = [
                (48 + c * 120, height - 100 - r * 30, 12, f"L{r + 1}C{c + 1}")
                for r in range(4)
                for c in range(3)
            ]
        if text_lines is not None:
            lines = text_lines
        if index in scanned:
            lines = []
        expected.extend(line[3] for line in lines)
        commands = [
            f"BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm <{text.encode('cp1252').hex()}> Tj ET"
            for x, y, size, text in (reversed(lines) if reverse else lines)
        ]
        if image or index in scanned:
            with Image.new("RGB", (240, 120), "white") as bitmap:
                draw = ImageDraw.Draw(bitmap)
                draw.rectangle((8, 8, 230, 110), outline="blue", width=3)
                draw.text(
                    (20, 45),
                    "SOMENTE IMAGEM" if index in scanned else "FIGURA",
                    fill="black",
                )
                stream = DecodedStreamObject()
                stream.set_data(bitmap.tobytes())
            stream.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(240),
                    NameObject("/Height"): NumberObject(120),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Im1"): writer._add_object(stream)}
            )
            commands.append(f"q 240 0 0 120 48 {height - 380} cm /Im1 Do Q")
        page[NameObject("/Resources")] = resources
        contents = DecodedStreamObject()
        contents.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(contents)
    writer.write(path)
    writer.close()
    return expected
