"""Testes da estrutura portátil sem executar o PyInstaller."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import validate_distribution

from validate_distribution import (
    EMPTY_USER_DIRECTORIES,
    NOTICE_DELIVERY_SHA256,
    PILLOW_COMPLIANCE_SHA256,
    PINNED_LICENSE_SHA256,
    PORTABLE_DIR_NAME,
    PYPDFIUM2_LICENSE_SHA256,
    REQUIRED_DIRECTORIES,
    REQUIRED_INTERNAL_DIRECTORIES,
    REQUIRED_INTERNAL_FILES,
    REQUIRED_LICENSE_FILES,
    REQUIRED_ROOT_FILES,
    COMMUNITY_RELEASE_POLICY,
    COMMUNITY_CANDIDATE_METADATA,
    COMMUNITY_DISTRIBUTION_CLASSIFICATION,
    YTDLP_APPROVED_SHA256,
    YTDLP_APPROVED_SOURCE_COMMIT,
    YTDLP_APPROVED_VERSION,
    YTDLP_DERIVED_COMPLIANCE_FILES,
    YTDLP_DELIVERY_FILES,
    YTDLP_OFFICIAL_DOCUMENT_SHA256,
    YTDLP_PROVENANCE_EXPECTED,
    YTDLP_RUNTIME_NOTICE_REQUIRED_MARKERS,
    find_distribution_issues,
    find_unexpected_urls,
)


class DistributionValidationTests(unittest.TestCase):
    def test_local_candidate_is_not_authorized_for_publication(self):
        self.assertIs(COMMUNITY_RELEASE_POLICY["public_release_allowed"], False)

    def test_manifest_requires_community_identity_and_local_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "release-manifest.json"
            doc = {
                "release_policy": dict(COMMUNITY_RELEASE_POLICY),
                "product_candidate": dict(COMMUNITY_CANDIDATE_METADATA),
                "distribution": {
                    "classification": COMMUNITY_DISTRIBUTION_CLASSIFICATION
                },
            }
            with patch.object(
                validate_distribution, "find_inventory_issues", return_value=[]
            ):
                manifest.write_text(json.dumps(doc), encoding="utf-8")
                self.assertEqual(
                    validate_distribution._manifest_policy_issues(manifest), []
                )
                doc["release_policy"]["public_release_allowed"] = True
                manifest.write_text(json.dumps(doc), encoding="utf-8")
                self.assertTrue(validate_distribution._manifest_policy_issues(manifest))

    def test_stackoverflow_attribution_host_is_exactly_allowed(self) -> None:
        self.assertEqual(
            find_unexpected_urls(
                "https://stackoverflow.com/questions/11993290/truly-custom-font-in-tkinter/30631309"
            ),
            [],
        )
        self.assertTrue(find_unexpected_urls("https://evil.stackoverflow.com/answer"))

    def create_valid_distribution(self, root: Path) -> Path:
        """Cria a menor estrutura aceita pelo validador."""
        portable_dir = root / PORTABLE_DIR_NAME
        portable_dir.mkdir()
        for filename in REQUIRED_ROOT_FILES:
            target = portable_dir / filename
            if filename == "LICENSE":
                target.write_bytes(
                    (Path(__file__).resolve().parents[2] / "LICENSE").read_bytes()
                )
            else:
                target.touch()
        for dirname in REQUIRED_DIRECTORIES:
            (portable_dir / dirname).mkdir()
        for dirname in REQUIRED_INTERNAL_DIRECTORIES:
            (portable_dir / "_internal" / dirname).mkdir(parents=True)
        for filename in REQUIRED_INTERNAL_FILES:
            path = portable_dir / "_internal" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        for filename in REQUIRED_LICENSE_FILES:
            destination = portable_dir / "Licencas" / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (
                filename in PINNED_LICENSE_SHA256
                or filename in YTDLP_DERIVED_COMPLIANCE_FILES
            ):
                source = Path(__file__).resolve().parents[1] / "Licencas" / filename
                destination.write_bytes(source.read_bytes())
            else:
                destination.write_text("Avisos verificados", encoding="utf-8")
        return portable_dir

    def test_expected_portable_structure_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            self.assertEqual(find_distribution_issues(portable_dir), [])

    def test_missing_own_license_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "LICENSE").unlink()
            issues = find_distribution_issues(portable_dir)
            self.assertIn("Arquivo obrigatório ausente: LICENSE", issues)

    def test_modified_own_license_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "LICENSE").write_text("MIT", encoding="utf-8")
            issues = find_distribution_issues(portable_dir)
            self.assertIn("LICENSE próprio divergente do MIT aprovado", issues)

    def test_own_license_accepts_git_canonical_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            license_path = portable_dir / "LICENSE"
            license_path.write_bytes(license_path.read_bytes().replace(b"\r\n", b"\n"))
            self.assertEqual(find_distribution_issues(portable_dir), [])

    def test_d14a_notice_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            notice = portable_dir / "Licencas" / "MICROSOFT_RUNTIME_NOTICE.txt"
            notice.write_text("alterado", encoding="utf-8")

            issues = find_distribution_issues(portable_dir)

        self.assertIn(
            "Notice D14A divergente do inventário: MICROSOFT_RUNTIME_NOTICE.txt",
            issues,
        )

    def test_direct_vc_runtime_file_is_rejected_but_upstream_text_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable = self.create_valid_distribution(Path(temporary_dir))
            (portable / "yt-dlp.exe").write_bytes(b"VCRUNTIME140.dll")
            self.assertEqual(find_distribution_issues(portable), [])
            direct = portable / "_internal" / "vCrUnTiMe140.DLL"
            direct.write_bytes(b"fixture")
            issues = find_distribution_issues(portable)
            self.assertTrue(
                any(
                    "Microsoft VC runtime app-local proibido" in issue
                    for issue in issues
                )
            )

    def test_ds_store_is_rejected_at_any_depth_case_insensitively(self) -> None:
        for relative in (".DS_Store", "_internal/customtkinter/assets/.ds_store"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                portable = self.create_valid_distribution(Path(tmp))
                residue = portable / relative
                residue.parent.mkdir(parents=True, exist_ok=True)
                residue.write_bytes(b"synthetic metadata")
                self.assertTrue(
                    any(
                        relative in issue
                        for issue in find_distribution_issues(portable)
                    )
                )

    def test_structure_works_inside_path_with_spaces_and_accents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            accented_root = Path(temporary_dir) / "Distribuição com espaços e acentos"
            accented_root.mkdir()
            portable_dir = self.create_valid_distribution(accented_root)
            self.assertEqual(find_distribution_issues(portable_dir), [])

    def test_missing_external_tool_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "ffmpeg.exe").unlink()
            issues = find_distribution_issues(portable_dir)
            self.assertIn("Arquivo obrigatório ausente: ffmpeg.exe", issues)

    def test_missing_deno_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "deno.exe").unlink()

            issues = find_distribution_issues(portable_dir)

            self.assertIn("Arquivo obrigatório ausente: deno.exe", issues)

    def test_missing_tkinter_runtime_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "_internal" / "_tkinter.pyd").unlink()

            issues = find_distribution_issues(portable_dir)

            self.assertTrue(any("_tkinter.pyd" in issue for issue in issues))

    def test_pdfium_runtime_and_pinned_wheel_notices_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "_internal" / "pypdfium2_raw" / "pdfium.dll").unlink()
            notice = next(iter(PYPDFIUM2_LICENSE_SHA256))
            (portable_dir / "Licencas" / notice).unlink()

            issues = find_distribution_issues(portable_dir)

            self.assertTrue(
                any("pypdfium2_raw/pdfium.dll" in issue for issue in issues)
            )
            self.assertTrue(any(notice in issue for issue in issues))

    def test_modified_pypdfium_notice_is_not_trusted_or_url_exempted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            notice = next(iter(PYPDFIUM2_LICENSE_SHA256))
            notice_path = portable_dir / "Licencas" / notice
            notice_path.write_text(
                "texto alterado https://dominio-nao-autorizado.invalid/",
                encoding="utf-8",
            )

            issues = find_distribution_issues(portable_dir)

            self.assertTrue(
                any("divergente do wheel 5.12.1" in issue for issue in issues)
            )
            self.assertTrue(
                any("URL de domínio não aprovado" in issue for issue in issues)
            )

    def test_managed_component_catalogue_url_policy_requires_exact_bytes(self) -> None:
        source = (
            Path(validate_distribution.__file__).with_name("installer")
            / "community-components-v1.json"
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable = self.create_valid_distribution(Path(temporary_dir))
            relative = "_internal/installer/community-components-v1.json"
            catalogue = portable / relative
            catalogue.parent.mkdir()
            catalogue.write_bytes(source.read_bytes())
            self.assertEqual(find_distribution_issues(portable), [])

            catalogue.write_bytes(source.read_bytes() + b"\n")
            issues = find_distribution_issues(portable)
            self.assertIn(
                f"Artefato de componente homologado divergente: {relative}", issues
            )
            self.assertIn(
                f"URL de domínio não aprovado encontrada em: {relative}", issues
            )

    def test_pillow_license_sbom_and_composition_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            required = (*PILLOW_COMPLIANCE_SHA256, "PILLOW_COMPOSITION.md")
            for filename in required:
                (portable_dir / "Licencas" / filename).unlink()

            issues = find_distribution_issues(portable_dir)

        for filename in required:
            with self.subTest(filename=filename):
                self.assertIn(
                    f"Documento de terceiros ausente: Licencas/{filename}",
                    issues,
                )

    def test_modified_pillow_official_files_are_rejected(self) -> None:
        for filename in PILLOW_COMPLIANCE_SHA256:
            with (
                self.subTest(filename=filename),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                portable_dir = self.create_valid_distribution(Path(temporary_dir))
                path = portable_dir / "Licencas" / filename
                path.write_text("arquivo oficial alterado", encoding="utf-8")

                issues = find_distribution_issues(portable_dir)

            self.assertTrue(
                any(
                    f"Documento Pillow divergente da wheel 13.0.0 auditada: {filename}"
                    in issue
                    for issue in issues
                )
            )

    def test_pillow_sbom_component_is_not_treated_as_material_presence(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        sbom = json.loads(
            (project_dir / "Licencas" / "PILLOW_SBOM.cdx.json").read_text(
                encoding="utf-8"
            )
        )
        component_names = {component["name"] for component in sbom["components"]}
        composition = (project_dir / "Licencas" / "PILLOW_COMPOSITION.md").read_text(
            encoding="utf-8"
        )
        normalized_composition = " ".join(composition.split())

        self.assertIn("libimagequant", component_names)
        self.assertIn(
            "Um componente listado no SBOM não equivale automaticamente",
            normalized_composition,
        )
        self.assertIn(
            "não possui suporte libimagequant habilitado",
            normalized_composition,
        )

    def test_ytdlp_delivery_notices_are_required_without_internal_evidence(
        self,
    ) -> None:
        required = YTDLP_DELIVERY_FILES
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            for filename in required:
                (portable_dir / "Licencas" / filename).unlink()

            issues = find_distribution_issues(portable_dir)

        for filename in required:
            with self.subTest(filename=filename):
                self.assertIn(
                    f"Documento de terceiros ausente: Licencas/{filename}", issues
                )
        self.assertTrue(set(required) <= set(NOTICE_DELIVERY_SHA256))
        self.assertTrue(
            set(YTDLP_DERIVED_COMPLIANCE_FILES) - {"yt-dlp/RUNTIME_SOURCE_NOTICES.md"}
        )
        for internal in (
            "yt-dlp/COMPOSITION.md",
            "yt-dlp/PROVENANCE.json",
            "yt-dlp/SOURCE_CORRESPONDENCE.md",
            "yt-dlp/SOURCE_PROVENANCE.json",
        ):
            self.assertNotIn(internal, REQUIRED_LICENSE_FILES)

    def test_ytdlp_official_documents_are_pinned_and_tampering_is_rejected(
        self,
    ) -> None:
        for filename in YTDLP_OFFICIAL_DOCUMENT_SHA256:
            with (
                self.subTest(filename=filename),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                portable_dir = self.create_valid_distribution(Path(temporary_dir))
                document = portable_dir / "Licencas" / filename
                document.write_text("documento oficial alterado", encoding="utf-8")

                issues = find_distribution_issues(portable_dir)

            self.assertTrue(
                any(
                    f"Documento yt-dlp divergente da release 2026.08.19 auditada: {filename}"
                    in issue
                    for issue in issues
                )
            )

    def test_ytdlp_provenance_is_exact_deterministic_and_contains_no_local_path(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        path = project_dir / "Licencas" / "yt-dlp" / "PROVENANCE.json"
        text = path.read_text(encoding="utf-8")
        provenance = json.loads(text)

        self.assertEqual(provenance, dict(YTDLP_PROVENANCE_EXPECTED))
        self.assertEqual(provenance["version"], YTDLP_APPROVED_VERSION)
        self.assertEqual(provenance["release_tag"], YTDLP_APPROVED_VERSION)
        self.assertEqual(provenance["source_commit"], YTDLP_APPROVED_SOURCE_COMMIT)
        self.assertEqual(provenance["executable_sha256"], YTDLP_APPROVED_SHA256)
        self.assertEqual(
            set(provenance["official_documents"]),
            {Path(filename).name for filename in YTDLP_OFFICIAL_DOCUMENT_SHA256},
        )
        self.assertEqual(
            text,
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]")
        self.assertNotIn("USERPROFILE", text)

    def test_ytdlp_provenance_mismatch_fails_closed(self) -> None:
        mismatches = {
            "version": "2026.07.05",
            "release_tag": "2026.07.05",
            "source_commit": "0" * 40,
            "executable_sha256": "0" * 64,
            "executable_size": 1,
        }
        for field, value in mismatches.items():
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                portable_dir = self.create_valid_distribution(Path(temporary_dir))
                path = portable_dir / "Licencas" / "yt-dlp" / "PROVENANCE.json"
                source = (
                    Path(__file__).resolve().parents[1]
                    / "Licencas"
                    / "yt-dlp"
                    / "PROVENANCE.json"
                )
                path.write_bytes(source.read_bytes())
                provenance = json.loads(path.read_text(encoding="utf-8"))
                provenance[field] = value
                path.write_text(
                    json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )

                issues = find_distribution_issues(portable_dir)

            self.assertIn(
                "Manifesto de proveniência yt-dlp diverge da baseline auditada",
                issues,
            )

    def test_ytdlp_source_provenance_is_pinned_and_tampering_fails_closed(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        path = project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"

        self.assertNotIn("yt-dlp/SOURCE_PROVENANCE.json", PINNED_LICENSE_SHA256)
        self.assertNotIn("yt-dlp/SOURCE_PROVENANCE.json", REQUIRED_LICENSE_FILES)
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            copied = portable_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
            copied.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")

            issues = find_distribution_issues(portable_dir)

        self.assertIn("Manifesto de source provenance yt-dlp foi adulterado", issues)

    def test_ytdlp_composition_records_complete_technical_source_contract(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        composition = (
            project_dir / "Licencas" / "yt-dlp" / "COMPOSITION.md"
        ).read_text(encoding="utf-8")
        normalized = " ".join(composition.split())

        self.assertIn("CArchive: 150 entradas", normalized)
        self.assertIn("PYZ: 1.584 módulos", normalized)
        self.assertIn("yt_dlp_ejs` 0.8.0", normalized)
        self.assertIn("OpenSSL 1.1.1t", normalized)
        self.assertIn("36 archives externos mais o source principal", normalized)
        self.assertIn("sources externos dos lotes 1, 1B, 1C, 1D, 1E e 1F", normalized)
        self.assertIn("runtime CPython 3.10.11", normalized)
        self.assertIn("método definitivo de entrega", normalized)
        self.assertIn(
            "source chain material tecnicamente completa (classe A)", normalized
        )

    def test_ytdlp_source_correspondence_records_technical_class_a(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        document = (
            project_dir / "Licencas" / "yt-dlp" / "SOURCE_CORRESPONDENCE.md"
        ).read_text(encoding="utf-8")
        normalized = " ".join(document.split())

        self.assertIn("A — TECNICAMENTE COMPLETA PARA REVISÃO JURÍDICA", normalized)
        self.assertIn("PyInstaller 6.22.0", normalized)
        self.assertIn("source do PyInstaller/bootloader está preservado", normalized)
        self.assertIn("curl-impersonate `v2.0.0`", normalized)
        self.assertIn("Astring 1.9.0", normalized)
        self.assertIn("Meriyah 6.1.4", normalized)
        self.assertIn("4e9426ae522c67de47ff3e060774328b42df0134", normalized)
        self.assertIn("121 certificados", normalized)
        self.assertIn("Python P2 geral: **RESOLVIDO TECNICAMENTE**", normalized)
        self.assertIn("CPython 3.10.11", normalized)
        self.assertIn(
            "OpenSSL, SQLite, bzip2, zlib runtime, libffi e XZ",
            normalized,
        )
        self.assertIn("RUNTIME_SOURCE_NOTICES.md", normalized)
        self.assertIn("Não há source gap material conhecido", normalized)
        self.assertIn("não autoriza publicação", normalized)
        self.assertIn("R3 permanece evidência histórica imutável", normalized)

    def test_ytdlp_runtime_source_notice_reconciles_material_versions(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        notice = (
            project_dir / "Licencas" / "yt-dlp" / "RUNTIME_SOURCE_NOTICES.md"
        ).read_text(encoding="utf-8")

        for marker in YTDLP_RUNTIME_NOTICE_REQUIRED_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, notice)
        self.assertIn("closure nativa de curl", notice)
        self.assertIn("sdist do cffi 2.1.1", notice)
        self.assertIn("runtime CPython", notice)

    def test_personal_and_development_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "settings.json").write_text("{}", encoding="utf-8")
            (portable_dir / "tests").mkdir()
            issues = find_distribution_issues(portable_dir)
            self.assertIn(
                "Item de desenvolvimento ou pessoal incluído: settings.json", issues
            )
            self.assertIn("Item de desenvolvimento ou pessoal incluído: tests", issues)

    def test_runtime_component_staging_is_never_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            stage = portable_dir / "Componentes" / ".staging" / "yt-dlp"
            stage.mkdir(parents=True)
            (stage / "partial.exe").write_bytes(b"partial")
            issues = find_distribution_issues(portable_dir)
            self.assertIn(
                "Item de desenvolvimento ou pessoal incluído: Componentes", issues
            )

    def test_downloads_and_logs_must_start_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            for dirname in EMPTY_USER_DIRECTORIES:
                (portable_dir / dirname / "arquivo-pessoal.txt").touch()
            issues = find_distribution_issues(portable_dir)
            self.assertIn("A pasta Downloads deveria estar vazia", issues)
            self.assertIn("A pasta Logs deveria estar vazia", issues)

    def test_personal_windows_path_inside_text_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "README.txt").write_text(
                "C:\\Users\\Professor\\arquivo", encoding="utf-8"
            )
            issues = find_distribution_issues(portable_dir)
            self.assertTrue(
                any("Possível caminho absoluto" in issue for issue in issues)
            )

    def test_sensitive_files_and_secret_patterns_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "credencial.pem").write_text(
                "-----BEGIN PRIVATE KEY-----\nvalor-simulado",
                encoding="utf-8",
            )
            (portable_dir / "README.txt").write_text(
                "authorization = token_simulado_123456789",
                encoding="utf-8",
            )

            issues = find_distribution_issues(portable_dir)

            self.assertTrue(any("sensível" in issue for issue in issues))
            self.assertTrue(any("segredo ou chave" in issue for issue in issues))

    def test_private_signing_key_and_encrypted_backups_are_rejected(self) -> None:
        forbidden = (
            ("issuer-signing-key-v1.dpapi", b"opaque-dpapi"),
            (
                "issuer-key-backup.pem",
                b"-----BEGIN ENCRYPTED PRIVATE KEY-----\nopaque\n"
                b"-----END ENCRYPTED PRIVATE KEY-----\n",
            ),
            ("issuer-key-backup.pkcs8", b"EncryptedPrivateKeyInfo"),
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            for relative, content in forbidden:
                (portable_dir / relative).write_bytes(content)

            issues = find_distribution_issues(portable_dir)

        for relative, _content in forbidden:
            with self.subTest(relative=relative):
                self.assertTrue(any(relative in issue for issue in issues), issues)

    def test_media_and_cache_directories_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "video.mp4").touch()
            cache = portable_dir / "__pycache__"
            cache.mkdir()
            (cache / "arquivo.pyc").touch()

            issues = find_distribution_issues(portable_dir)

            self.assertTrue(any("video.mp4" in issue for issue in issues))
            self.assertTrue(any("__pycache__" in issue for issue in issues))

    def test_documents_engine_and_poc_payloads_are_rejected(self) -> None:
        forbidden = (
            "LibreOfficePortable.exe",
            "engine/LibreOfficePortable/App/libreoffice/program/soffice.com",
            "engine/LibreOfficePortable/App/libreoffice/program/soffice.bin",
            "engine/LibreOfficePortable/App/libreoffice/program/soffice.exe",
            "engine/LibreOfficePortable/App/libreoffice/share/fonts/truetype/opens___.ttf",
            "engine/LibreOfficePortable/App/AppInfo/Launcher/PortableApps.comLauncher.dll",
            "components/documents/component-manifest.json",
            "build-documents-poc/fixture.docx",
            "profiles/libreoffice/.lock",
            "engine/crash.dmp",
            "LibreOffice-source.tar.gz",
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            for relative in forbidden:
                path = portable_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic documents component payload")

            issues = find_distribution_issues(portable_dir)

        for relative in forbidden:
            with self.subTest(relative=relative):
                self.assertTrue(any(relative in issue for issue in issues), issues)

    def test_official_portableapps_url_is_allowed_but_lookalikes_are_rejected(
        self,
    ) -> None:
        official = "https://portableapps.com/apps/office/libreoffice_portable"
        self.assertEqual(find_unexpected_urls(official), [])
        for lookalike in (
            "https://downloads.portableapps.com/libreoffice",
            "https://portableapps.example/libreoffice",
        ):
            with self.subTest(lookalike=lookalike):
                self.assertEqual(find_unexpected_urls(lookalike), [lookalike])

    def test_licensing_test_artifacts_and_local_activation_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            (portable_dir / "activation.dat").write_bytes(b"opaque")
            fixture = portable_dir / "fixtures"
            fixture.mkdir()
            (fixture / "valid_receipt_v1.json").write_text("{}", encoding="utf-8")
            fake = portable_dir / "fakes"
            fake.mkdir()
            (fake / "activation_provider.py").write_text("fake", encoding="utf-8")

            issues = find_distribution_issues(portable_dir)

            self.assertTrue(any("activation.dat" in issue for issue in issues))
            self.assertTrue(any("fixtures" in issue for issue in issues))
            self.assertTrue(any("fakes" in issue for issue in issues))

    def test_release_mode_requires_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))

            issues = find_distribution_issues(portable_dir, require_manifest=True)

            self.assertIn("Arquivo obrigatório ausente: release-manifest.json", issues)

    def test_private_issuer_and_administrative_files_are_rejected(self) -> None:
        forbidden = (
            "license_manager/ui.py",
            "license-manager-private/settings.json",
            "license-manager-backup.sqlite3",
            "license_manager.exe",
            "activation_issuer.exe",
            "activation_issuer/keys.py",
            "admin/issuance-register.json",
            "backups/register.json",
            "requests/device.edureq",
            "licenses/device.edulic",
            "docs/ADMIN_RUNBOOK.md",
            "docs/SECURITY_DEVICE_MATRIX_6B.md",
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            portable_dir = self.create_valid_distribution(Path(temporary_dir))
            for relative in forbidden:
                path = portable_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("artefato administrativo", encoding="utf-8")

            issues = find_distribution_issues(portable_dir)

        for relative in forbidden:
            with self.subTest(relative=relative):
                self.assertTrue(any(relative in issue for issue in issues), issues)

    def test_only_approved_official_url_domains_are_accepted(self) -> None:
        self.assertEqual(find_unexpected_urls("https://ffmpeg.org/legal.html"), [])
        self.assertEqual(find_unexpected_urls("https://python-pillow.github.io/"), [])
        self.assertEqual(
            find_unexpected_urls(
                "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist"
            ),
            [],
        )
        for official_url in (
            "https://api.github.com/repos/google/boringssl/commits/revision",
            "https://codeload.github.com/google/boringssl/tar.gz/revision",
            "https://files.pythonhosted.org/packages/source.tar.gz",
            "https://pypi.org/project/curl-cffi/",
            "https://raw.githubusercontent.com/google/boringssl/revision/LICENSE",
            "https://registry.npmjs.org/astring/-/astring-1.9.0.tgz",
        ):
            with self.subTest(official_url=official_url):
                self.assertEqual(find_unexpected_urls(official_url), [])
        self.assertEqual(
            find_unexpected_urls("https://conteudo-exemplo.invalid/video"),
            ["https://conteudo-exemplo.invalid/video"],
        )
        for unauthorized_url in (
            "https://api.github.com.example.invalid/",
            "https://codeload.github.com.example.invalid/",
            "https://raw.githubusercontent.com.example.invalid/",
            "https://registry.npmjs.org.example.invalid/",
            "https://python-pillow.github.io.example.invalid/",
            "https://outro-projeto.github.io/",
            "https://learn.microsoft.com.example.invalid/",
            "https://microsoft.com/",
        ):
            with self.subTest(unauthorized_url=unauthorized_url):
                self.assertEqual(
                    find_unexpected_urls(unauthorized_url),
                    [unauthorized_url],
                )

    def test_build_files_do_not_contain_developer_absolute_path(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("build_editions.py", "build_pyinstaller.py", "EduDownloader.spec"):
            text = (root / name).read_text("utf-8")
            self.assertNotRegex(text, r"(?i)[a-z]:[\\/]Users[\\/]")

    def test_build_uses_tkinter_compatibility_helpers(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "build_pyinstaller.py").read_text("utf-8")
        spec = (root / "EduDownloader.spec").read_text("utf-8")
        self.assertIn("configure_tcl_tk(", build)
        self.assertIn("pyi_rth_edudownloader_tk.py", spec)

    def test_build_compileall_includes_current_tool_modules(self):
        root = Path(__file__).resolve().parents[1]
        from build_editions import source_inventory

        files = source_inventory(root)
        for file in (
            "documents_tools.py",
            "docx_writer.py",
            "media_tools.py",
            "app.py",
        ):
            self.assertIn(file, files)

    def test_build_runs_licensing_guards_in_an_isolated_candidate_area(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "build_editions.py").read_text("utf-8")
        self.assertIn('run("notices-source",', build)
        self.assertIn('"notices-delivery",', build)
        self.assertIn('"validate_edition_distribution.py",', build)
        self.assertIn('run("zip-guard",', build)

    def test_spec_excludes_tests_and_keeps_required_production_modules(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "EduDownloader.spec").read_text("utf-8")
        self.assertIn('["frozen_community.py"]', spec)
        self.assertIn('"pdf_tools",', spec)
        self.assertIn('"pypdfium2",', spec)
        self.assertIn('excludes=["tests",', spec)
        self.assertNotIn("licensing.", spec)

    def test_external_binaries_are_ignored_including_deno(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        gitignore = (project_dir / ".gitignore").read_text(encoding="utf-8")

        for executable in ("yt-dlp.exe", "deno.exe", "ffmpeg.exe", "ffprobe.exe"):
            self.assertIn(executable, gitignore.splitlines())

    def test_pdf_runtime_dependencies_are_pinned(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        requirements = (project_dir / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("pypdf==7.1.1", requirements.splitlines())
        self.assertIn("pypdfium2==5.12.1", requirements.splitlines())
        self.assertIn("Pillow==13.0.0", requirements.splitlines())

    def test_pdf_to_docx_poc_dependencies_are_absent_from_official_locks(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        dependency_files = (
            "requirements.txt",
            "requirements-build.lock",
            "requirements-build-hashes.lock",
        )
        forbidden = ("pdf2docx", "pymupdf", "opencv", "numpy")
        for filename in dependency_files:
            with self.subTest(filename=filename):
                normalized = (
                    (project_dir / filename).read_text(encoding="utf-8").casefold()
                )
                self.assertFalse(
                    any(dependency in normalized for dependency in forbidden)
                )


if __name__ == "__main__":
    unittest.main()
