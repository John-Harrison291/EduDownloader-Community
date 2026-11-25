"""Generated-only OOXML security and no-abandoned-stack regressions."""

import ast
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image

import docx_writer as w
import validate_distribution as distribution
from edition_profiles import select_build_profile
from validate_edition_distribution import module_issues


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ação 你好.docx"
        buffer = BytesIO()
        Image.new("RGBA", (40, 20), (0, 80, 200, 100)).save(buffer, format="PNG")
        self.picture = w.Picture(buffer.getvalue(), 120, 60)
        self.parts, self.text = w.package_parts(
            [
                w.Page(
                    595,
                    842,
                    (
                        w.Paragraph(
                            (
                                w.Run(
                                    "Olá <&> 你好\ttexto\nlinha", bold=True, italic=True
                                ),
                            ),
                            "center",
                        ),
                        self.picture,
                    ),
                ),
            ]
        )

    def save(self, parts=None):
        with self.path.open("wb") as stream:
            w.save_parts(self.parts if parts is None else parts, stream)

    def mutate_xml(self, name, change):
        root = ET.fromstring(self.parts[name])
        change(root)
        self.parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def reject(self):
        self.save()
        with self.assertRaises(ValueError):
            w.validate(self.path)

    def test_text_unicode_styles_alignment_and_rgba(self):
        self.save()
        report = w.validate(self.path, self.text)
        self.assertEqual(report["text"], "Olá <&> 你好\ttexto\nlinha")
        self.assertEqual(report["images"], 1)
        root = ET.fromstring(self.parts["word/document.xml"])
        self.assertIsNotNone(root.find(".//w:i", w.NS))
        self.assertEqual(root.find(".//w:jc", w.NS).get(w.q("w:val")), "center")
        with Image.open(BytesIO(self.picture.png)) as image:
            image.verify()

    def test_traversal_and_unexpected_parts(self):
        for name in (
            "../evil",
            "/absolute",
            "word/../../evil",
            "word/vbaProject.bin",
            "word/embeddings/object.exe",
            "word/settings.xml",
        ):
            with self.subTest(name=name):
                self.save({**self.parts, name: b"unexpected"})
                with self.assertRaises(ValueError):
                    w.validate(self.path)

    def test_external_relationships(self):
        self.mutate_xml(
            "word/_rels/document.xml.rels",
            lambda root: root[0].set("TargetMode", "External"),
        )
        self.reject()

    def test_missing_media_and_bad_content_type(self):
        media = self.parts.pop("word/media/image1.png")
        self.reject()
        self.parts["word/media/image1.png"] = media
        self.mutate_xml(
            "[Content_Types].xml",
            lambda root: root[-1].set(
                "ContentType", "application/vnd.ms-word.document.macroEnabled.main+xml"
            ),
        )
        self.reject()

    def test_duplicate_and_invalid_relationship_ids(self):
        self.mutate_xml(
            "word/_rels/document.xml.rels", lambda root: root[0].set("Id", "")
        )
        self.reject()

    def test_active_fields_and_attributes(self):
        original = self.parts["word/document.xml"]
        for tag in ("w:fldSimple", "w:object", "w:altChunk", "w:hyperlink"):
            self.parts["word/document.xml"] = original
            self.mutate_xml(
                "word/document.xml", lambda root: ET.SubElement(root[0], w.q(tag))
            )
            self.reject()
        self.parts["word/document.xml"] = original
        self.mutate_xml(
            "word/document.xml", lambda root: root.set("unexpected", "value")
        )
        self.reject()

    def test_dtd_and_malformed_xml(self):
        self.parts["word/document.xml"] = b'<?xml version="1.0"?><!DOCTYPE x><x/>'
        self.reject()
        self.parts["word/document.xml"] = b'<?xml version="1.0"?><broken'
        self.save()
        with self.assertRaises(ET.ParseError):
            w.validate(self.path)

    def test_duplicate_zip_entries_rejected(self):
        self.save()
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "a") as archive:
                archive.writestr("word/document.xml", self.parts["word/document.xml"])
        with self.assertRaises(ValueError):
            w.validate(self.path)

    def test_png_crc_and_trailing_payload(self):
        for data in (self.picture.png + b"payload", self.picture.png[:-4] + b"xxxx"):
            with self.assertRaises(ValueError):
                w.validate_png(data)

    def test_dimensions_and_output_limits(self):
        for size in (float("nan"), float("inf"), 0, 1500):
            with self.assertRaises(ValueError):
                w.package_parts([w.Page(size, 842, ())])
        self.save()
        with patch.object(w, "MAX_BYTES", 10), self.assertRaises(ValueError):
            w.validate(self.path)

    def test_cancellation_during_package_write_and_validation(self):
        def cancel():
            raise InterruptedError("cancel")

        with self.assertRaises(InterruptedError):
            w.package_parts([w.Page(595, 842, ())], cancel)
        with self.assertRaises(InterruptedError):
            w.save_parts(self.parts, BytesIO(), cancel)
        self.save()
        with self.assertRaises(InterruptedError):
            w.validate(self.path, self.text, cancel)


class AbandonedDependencyTests(unittest.TestCase):
    def test_exact_xml_namespaces(self):
        self.assertEqual(
            w.NS["w"], "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        )
        self.assertEqual(
            w.NS["r"],
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        )

    def test_feature_imports_and_requirements_do_not_use_abandoned_stack(self):
        project = Path(__file__).resolve().parents[1]
        for name in ("docx_writer.py", "pdf_to_docx.py", "pdfium_access.py"):
            tree = ast.parse((project / name).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module or "")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("__import__", "exec", "eval"))
            self.assertFalse({x.split(".")[0] for x in imports} & {"docx", "lxml"})
        for name in (
            "requirements.txt",
            "requirements-build.lock",
            "requirements-build-hashes.lock",
        ):
            text = (project / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("python-docx", text)
            self.assertNotIn("lxml", text)
            self.assertNotIn("typing_extensions", text)
        self.assertFalse((project / "hooks/hook-lxml.py").exists())

    def test_pyz_guard_rejects_both_packages_not_custom_writer(self):
        profile = select_build_profile("community")
        findings = module_issues(
            {"lxml.etree", "docx.document", "docx_writer"}, profile
        )
        self.assertIn("forbidden-module:lxml.etree", findings)
        self.assertIn("forbidden-module:docx.document", findings)
        self.assertNotIn("forbidden-module:docx_writer", findings)

    def test_distribution_directory_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "_internal/lxml").mkdir(parents=True)
            issues = distribution.find_distribution_issues(root)
            self.assertTrue(
                any("Stack PDF/Word abandonada" in issue for issue in issues)
            )


if __name__ == "__main__":
    unittest.main()
