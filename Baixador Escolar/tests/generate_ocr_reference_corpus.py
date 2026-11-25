"""Own known-transcription OCR corpus; optional isolated QA dependencies only.

Requires Pillow, pypdfium2 and ReportLab in an isolated QA environment. Never
writes into the application or overwrites an existing corpus directory.
"""

import argparse


def main(output):
    import os
    from pathlib import Path
    from contextlib import closing
    import json
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    import pypdfium2 as pdfium
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader

    OUT = Path(output).resolve()
    if OUT.is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit("Use a new QA directory outside the repository")
    OUT.mkdir(parents=True, exist_ok=False)
    for name, file in [
        ("Arial", "arial.ttf"),
        ("ArialBold", "arialbd.ttf"),
        ("Times", "times.ttf"),
        ("Decorative", "comicbd.ttf"),
    ]:
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / file
        pdfmetrics.registerFont(
            TTFont(
                name, str(path if path.exists() else Path("C:/Windows/Fonts/arial.ttf"))
            )
        )
    TRANSCRIPTION = [
        "A escola reúne pessoas para aprender.",
        "Leia com atenção, observe as figuras e responda.",
        "A água, o coração e a ciência fazem parte da atividade.",
        "Questão 1. Quanto é 12 + 8 = 20?",
        "Questão 2. Calcule 35 - 7 = 28 e 6 × 4 = 24.",
        "Escreva uma explicação completa com suas palavras.",
    ]

    def digital(path, kind="plain", size=12):
        c = canvas.Canvas(str(path), pagesize=(595, 842))
        c.setTitle("Fixture sintética própria do Goal 5.5")
        if kind == "color":
            c.setFillColorRGB(0.92, 0.96, 0.78)
            c.rect(0, 0, 595, 842, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Decorative" if kind == "decorative" else "ArialBold", 20)
        c.drawString(48, 785, "Atividade escolar em português")
        c.setFont("Times" if kind == "decorative" else "Arial", size)
        expected = ["Atividade escolar em português"]
        for i, text in enumerate(TRANSCRIPTION):
            c.drawString(48, 735 - i * 32, text)
            expected.append(text)
        c.setFillColorRGB(0.2, 0.55, 0.75)
        c.circle(115, 385, 40, fill=1, stroke=0)
        c.setFillColorRGB(0.9, 0.65, 0.25)
        c.rect(205, 345, 80, 80, fill=1, stroke=0)
        if kind == "columns":
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Arial", 11)
            for x, label in ((48, "Esquerda"), (325, "Direita")):
                for i in range(5):
                    text = f"{label} {i + 1}: observe e registre."
                    c.drawString(x, 270 - i * 25, text)
                    expected.append(text)
        if kind == "table":
            c.setStrokeColorRGB(0, 0, 0)
            c.setFillColorRGB(0, 0, 0)
            xs = (48, 190, 340, 530)
            ys = (280, 245, 210, 175)
            for x in xs:
                c.line(x, ys[-1], x, ys[0])
            for y in ys:
                c.line(xs[0], y, xs[-1], y)
            c.setFont("Arial", 11)
            for r in range(3):
                for col in range(3):
                    text = f"Linha {r + 1} valor {col + 1}"
                    c.drawString(xs[col] + 6, ys[r] - 23, text)
                    expected.append(text)
        c.showPage()
        c.save()
        return expected

    def raster(path, dpi=220):
        with (
            pdfium.PdfDocument(path) as pdf,
            closing(pdf[0]) as page,
            closing(page.render(scale=dpi / 72)) as bitmap,
        ):
            return bitmap.to_pil().convert("RGB")

    def scan(path, image, size=(595, 842), pages=1):
        c = canvas.Canvas(str(path), pagesize=size)
        c.setTitle("Imagem sintética própria para OCR")
        for _ in range(pages):
            c.drawImage(ImageReader(image), 0, 0, *size)
            c.showPage()
        c.save()

    manifest = []
    for ident, kind, size in [
        ("digital", "plain", 12),
        ("color", "color", 12),
        ("decorative", "decorative", 12),
        ("small", "plain", 7),
        ("table", "table", 12),
        ("columns", "columns", 12),
    ]:
        source = OUT / (ident + "-source.pdf")
        expected = digital(source, kind, size)
        if ident == "digital":
            manifest.append(dict(id=ident, expected=expected, kind="digital"))
            continue
        with raster(source, 240 if ident != "small" else 200) as image:
            scan(OUT / (ident + ".pdf"), image)
        manifest.append(dict(id=ident, expected=expected, kind="scan"))
    with raster(OUT / "digital-source.pdf", 220) as original:
        for ident, angle, blur, contrast in [
            ("scanned", 0, 0, 1),
            ("skewed", 3, 0, 1),
            ("rotated90", 90, 0, 1),
            ("rotated180", 180, 0, 1),
            ("rotated270", 270, 0, 1),
            ("blurred", 0, 2.1, 0.7),
            ("photo", -2, 0.45, 0.82),
        ]:
            image = (
                original.rotate(
                    angle,
                    resample=Image.Resampling.BICUBIC,
                    expand=True,
                    fillcolor="white",
                )
                if angle
                else original.copy()
            )
            if blur:
                old = image
                image = image.filter(ImageFilter.GaussianBlur(blur))
                old.close()
            if contrast != 1:
                old = image
                image = ImageEnhance.Contrast(image).enhance(contrast)
                old.close()
            if ident == "photo":
                # Known synthetic perspective; no user photograph is altered.
                old = image
                image = image.transform(
                    image.size,
                    Image.Transform.QUAD,
                    (
                        20,
                        10,
                        0,
                        image.height - 10,
                        image.width - 5,
                        image.height,
                        image.width - 15,
                        0,
                    ),
                    resample=Image.Resampling.BICUBIC,
                    fillcolor="white",
                )
                old.close()
            scan(
                OUT / (ident + ".pdf"),
                image,
                (842, 595) if angle in (90, 270) else (595, 842),
            )
            image.close()
            manifest.append(
                dict(
                    id=ident,
                    expected=["Atividade escolar em português", *TRANSCRIPTION],
                    kind="scan",
                )
            )
        c = canvas.Canvas(str(OUT / "existing_layer.pdf"), pagesize=(595, 842))
        c.drawImage(ImageReader(original), 0, 0, 595, 842)
        text = c.beginText()
        text.setTextRenderMode(3)
        text.setFont("ArialBold", 20)
        text.setTextOrigin(48, 785)
        text.textOut("Atividade escolar em português")
        c.drawText(text)
        for i, line in enumerate(TRANSCRIPTION):
            text = c.beginText()
            text.setTextRenderMode(3)
            text.setFont("Arial", 12)
            text.setTextOrigin(48, 735 - i * 32)
            text.textOut(line)
            c.drawText(text)
        c.showPage()
        c.save()
        manifest.append(
            dict(
                id="existing_layer",
                expected=["Atividade escolar em português", *TRANSCRIPTION],
                kind="existing_layer",
            )
        )
        # Text image without a whole-page scan, alongside genuine digital text.
        crop = original.crop(
            (
                round(40 * 220 / 72),
                round((842 - 750) * 220 / 72),
                round(550 * 220 / 72),
                round((842 - 540) * 220 / 72),
            )
        )
        for ident in ("mixed", "mixed_regions"):
            c = canvas.Canvas(str(OUT / (ident + ".pdf")), pagesize=(595, 842))
            c.setFont("ArialBold", 18)
            c.drawString(48, 790, "Cabeçalho digital preservado")
            c.drawImage(ImageReader(crop), 48, 450, 510, 210)
            if ident == "mixed_regions":
                c.setFillColorRGB(0.3, 0.5, 0.8)
                c.circle(150, 300, 60, fill=1, stroke=0)
            c.showPage()
            c.save()
            manifest.append(
                dict(
                    id=ident,
                    expected=["Cabeçalho digital preservado", *TRANSCRIPTION],
                    kind="mixed",
                )
            )
        crop.close()
        scan(OUT / "large.pdf", original, pages=40)
        manifest.append(
            dict(
                id="large",
                expected=["Atividade escolar em português", *TRANSCRIPTION],
                kind="large",
                pages=40,
            )
        )
    figure = Image.new("RGB", (1400, 1800), "white")
    d = ImageDraw.Draw(figure)
    d.ellipse((100, 200, 600, 700), fill="#2277aa")
    d.polygon([(800, 300), (1200, 700), (800, 700)], fill="#e8ad32")
    d.rectangle((150, 1000, 1100, 1200), outline="black", width=5)
    scan(OUT / "illustration.pdf", figure)
    figure.close()
    manifest.append(dict(id="illustration", expected=[], kind="graphic"))
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Created {len(manifest)} controlled cases with known transcriptions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    main(parser.parse_args().output)
