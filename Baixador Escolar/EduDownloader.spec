"""Configuração controlada do PyInstaller para a distribuição portátil."""

analysis = Analysis(
    ["frozen_community.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("branding/edudownloader-logo-original.png", "branding"),
        ("installer/libreoffice-image.json", "installer"),
        ("installer/libreoffice-signatures.json", "installer"),
        ("installer/libreoffice-ui-resources.txt", "installer"),
        ("installer/community-components-v1.json", "installer"),
        ("installer/component-assets/DENO-2.9.8-DEPENDENCIAS.txt", "installer/component-assets"),
        ("installer/component-assets/DENO-BASELINE-LICENSES.txt", "installer/component-assets"),
        ("installer/component-assets/FFMPEG_BTBN_LICENSE.txt", "installer/component-assets"),
        ("installer/component-assets/FFMPEG_BTBN_NOTICE.txt", "installer/component-assets"),
    ],
    hiddenimports=[
        "pdf_tools",
        "pypdfium2",
        "pypdfium2.raw",
        "pypdfium2_raw",
        "file_publication",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_rth_edudownloader_tk.py"],
    excludes=["tests", "bootstrap", "docx", "lxml", "pytesseract", "sqlite3", "_sqlite3"],
    noarchive=False,
    optimize=0,
)

# PyInstaller deliberately discovers VC dependencies of CPython. Exclude the
# two app-local DLLs at the Analysis-to-COLLECT boundary, never after a build.
external_runtime_names = {"vcruntime140.dll", "vcruntime140_1.dll"}
analysis.binaries = [
    entry
    for entry in analysis.binaries
    if entry[0].replace("\\", "/").split("/")[-1].casefold()
    not in external_runtime_names
]

# A SBOM distribuída no metadado da dependência descreve a cadeia de build do
# fornecedor e não é necessária em runtime. As licenças permanecem no pacote.
# .DS_Store é resíduo de empacotamento, sem função runtime; só afeta novos builds.
analysis.datas = [
    data_entry
    for data_entry in analysis.datas
    if not (
        data_entry[0].casefold().startswith("cryptography-")
        and ".dist-info/sboms/"
        in data_entry[0].replace("\\", "/").casefold()
    )
    and ".ds_store" not in data_entry[0].replace("\\", "/").casefold().split("/")
]

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="EduDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon='branding/edudownloader-symbol.ico',
    version="version_info.txt",
    uac_admin=False,
    uac_uiaccess=False,
)

distribution = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EduDownloader-Portable",
)
