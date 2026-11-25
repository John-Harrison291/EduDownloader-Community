import json
import tempfile
import unittest
from pathlib import Path

from installed_maintenance import cleanup_user_installation
from libreoffice_image import file_hash, record_office_ownership


class InstalledMaintenanceTests(unittest.TestCase):
    def test_authenticated_profile_pointer_is_removed_with_owned_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation = root / "App"
            documents = root / "Documents"
            image = documents / "Componentes/L-repair-112233aa"
            image.mkdir(parents=True)
            (image / "program.bin").write_bytes(b"gerenciado")
            record_office_ownership(image, installation)
            pointer = image.parent / "active.json"
            pointer.write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "identity": "1" * 24,
                        "version": "26.8.3.1",
                        "relative_path": image.name,
                    }
                ),
                encoding="utf-8",
            )
            cleanup_user_installation(
                installation, root / "Runtime", documents, remove_preferences=False
            )
            self.assertFalse(image.exists())
            self.assertFalse(pointer.exists())

    def test_only_owned_components_are_removed_and_preferences_are_optional(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install, runtime, documents = (
                root / "App",
                root / "Runtime",
                root / "Documents",
            )
            office = documents / "Componentes" / "L"
            office.mkdir(parents=True)
            engine = office / "soffice.com"
            engine.write_bytes(b"installed")
            record_office_ownership(office, install)
            personal = office / "arquivo.pdf"
            personal.write_bytes(b"personal")
            other = documents / "Componentes" / "L-repair-112233aa"
            other.mkdir()
            (other / "independente.exe").write_bytes(b"independent")
            record_office_ownership(other, root / "OtherApp")

            yt = runtime / "Componentes" / "yt-dlp" / "2026.11.23"
            yt.mkdir(parents=True)
            binary = yt / "yt-dlp.exe"
            binary.write_bytes(b"test")
            metadata = {
                "component": "yt-dlp",
                "version": yt.name,
                "relative_path": yt.name + "/yt-dlp.exe",
                "sha256": file_hash(binary),
            }
            (yt / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            pointer = yt.parent / "active.json"
            pointer.write_text(json.dumps(metadata), encoding="utf-8")
            prefs = runtime / "settings.json"
            prefs.write_bytes(b'{"tema":"dark"}')
            private_pdf = runtime / "Downloads" / "resultado.pdf"
            private_pdf.parent.mkdir()
            private_pdf.write_bytes(b"result")

            cleanup_user_installation(
                install, runtime, documents, remove_preferences=False
            )
            self.assertFalse(engine.exists())
            self.assertFalse(binary.exists())
            self.assertFalse(pointer.exists())
            self.assertTrue(prefs.is_file())
            self.assertEqual(personal.read_bytes(), b"personal")
            self.assertEqual((other / "independente.exe").read_bytes(), b"independent")
            cleanup_user_installation(
                install, runtime, documents, remove_preferences=True
            )
            self.assertFalse(prefs.exists())
            self.assertEqual(private_pdf.read_bytes(), b"result")
