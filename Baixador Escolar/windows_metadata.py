"""Windows version resources for future builds; no certified publisher implied."""

from constants import APP_NAME, PRODUCT_EDITION, ProductEdition, edition_version


def metadata(*, publisher="", edition=None):
    edition = PRODUCT_EDITION if edition is None else edition
    if not isinstance(edition, ProductEdition):
        raise ValueError("An explicit build edition is required")
    if (
        not isinstance(publisher, str)
        or len(publisher) > 160
        or any(ord(c) < 32 for c in publisher)
    ):
        raise ValueError("Explicit legal publisher must be plain text")
    return {
        "CompanyName": publisher,
        "FileDescription": APP_NAME,
        "FileVersion": edition_version(edition),
        "InternalName": "EduDownloader",
        "OriginalFilename": "EduDownloader.exe",
        "ProductName": "EduDownloader",
        "ProductVersion": edition_version(edition),
        "LegalCopyright": "Consulte LICENSE para autoria e termos do software.",
    }


def version_resource(*, publisher="", edition=None):
    """Build dependency imported only by explicit PyInstaller preparation."""
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo,
        FixedFileInfo,
        StringFileInfo,
        StringTable,
        StringStruct,
        VarFileInfo,
        VarStruct,
    )

    selected = PRODUCT_EDITION if edition is None else edition
    version = tuple(map(int, edition_version(selected).split(".")))
    if len(version) != 3 or any(not 0 <= n <= 65535 for n in version):
        raise ValueError("Invalid application version")
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(*version, 0),
            prodvers=(*version, 0),
            mask=0x3F,
            flags=0,
            OS=0x40004,
            fileType=1,
            subtype=0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "041604B0",
                        [
                            StringStruct(k, v)
                            for k, v in metadata(
                                publisher=publisher, edition=edition
                            ).items()
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )
