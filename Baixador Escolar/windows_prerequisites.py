"""Read-only Windows x64 VC v14 prerequisite check for QA/future installers.

The audited Pillow wheels use MSVC linker 14.51. The existing Microsoft build
manifest records the same 14.51 baseline. UCRT and static MinGW components are
not evidence that the VC Redistributable is needed by themselves.
"""

from dataclasses import asdict, dataclass
import ctypes
import json
import os
import re


MINIMUM_VC_VERSION = (14, 51, 0, 0)
RUNTIME_KEY = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"


def native_architecture():
    """Query the OS, including under emulation; never trust an environment hint."""
    if os.name != "nt":
        return "unknown"
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetNativeSystemInfo.argtypes = [ctypes.c_void_p]
        kernel.GetNativeSystemInfo.restype = None
        info = ctypes.create_string_buffer(64)
        kernel.GetNativeSystemInfo(info)
        return {9: "x64", 0: "x86", 12: "arm64"}.get(
            int.from_bytes(info.raw[:2], "little"), "unknown"
        )
    except (OSError, AttributeError):
        return "unknown"


@dataclass(frozen=True)
class RuntimeCheck:
    status: str
    architecture: str
    minimum: str
    installed: str | None
    reason: str


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"v?\d{1,5}(?:\.\d{1,5}){3}", value
    ):
        raise ValueError("Invalid runtime version")
    result = tuple(map(int, value.removeprefix("v").split(".")))
    if any(n > 65535 for n in result):
        raise ValueError("Invalid runtime version")
    return result


def read_runtime_records():
    """Inspect both registry views explicitly; never inspect user activation."""
    import winreg

    records = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, RUNTIME_KEY, 0, winreg.KEY_READ | view
            ) as key:
                record = {}
                for name in ("Installed", "Version", "Major", "Minor", "Bld", "Rbld"):
                    try:
                        record[name] = winreg.QueryValueEx(key, name)[0]
                    except FileNotFoundError:
                        record[name] = None
                records.append(record)
        except FileNotFoundError:
            continue
    return records


def check_vc_runtime(*, minimum=MINIMUM_VC_VERSION, architecture=None, reader=None):
    """No installation, repair, elevation, download or DLL-existence inference."""
    required = version_tuple(".".join(map(str, minimum)))
    if required[0] != 14:
        raise ValueError("Only the audited v14 family is supported")
    architecture = architecture or native_architecture()
    minimum_text = ".".join(map(str, required))

    def result(status, reason, installed=None):
        return RuntimeCheck(status, architecture, minimum_text, installed, reason)

    if architecture.casefold() not in ("amd64", "x86_64", "x64"):
        return result("requires-attention", "architecture-not-x64")
    if reader is None and os.name != "nt":
        return result("not-tested", "windows-registry-unavailable")
    try:
        records = (reader or read_runtime_records)()
    except OSError:
        return result("not-tested", "registry-access-unavailable")
    if not records:
        return result("requires-attention", "runtime-absent")
    versions, absent = set(), False
    try:
        for record in records:
            if type(record.get("Installed")) is not int or record["Installed"] not in (
                0,
                1,
            ):
                raise ValueError
            if record["Installed"] == 0:
                absent = True
                continue
            version = version_tuple(record.get("Version"))
            numeric = tuple(record.get(n) for n in ("Major", "Minor", "Bld", "Rbld"))
            if (
                any(type(n) is not int for n in numeric)
                or numeric != version
                or version[0] != 14
            ):
                raise ValueError
            versions.add(version)
        if len(versions) > 1 or versions and absent:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return result("requires-attention", "runtime-records-inconsistent")
    if not versions:
        return result("requires-attention", "runtime-absent")
    installed = versions.pop()
    installed_text = ".".join(map(str, installed))
    return result(
        "ready" if installed >= required else "requires-attention",
        "runtime-sufficient" if installed >= required else "runtime-below-minimum",
        installed_text,
    )


if __name__ == "__main__":
    print(json.dumps(asdict(check_vc_runtime()), indent=2))
