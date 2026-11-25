"""Explicit Authenticode preparation; never signs originals or selects /a.

An operator must supply a trusted code-signing certificate already provisioned
by an authorized CA/HSM provider. No enrollment, costs, PFX passwords, private
key export, trust-store changes or automatic build invocation occur here.
"""

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

from file_publication import publish_new_file


class SigningError(RuntimeError):
    pass


def system_powershell():
    if os.name != "nt":
        raise SigningError("Windows is required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetWindowsDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetWindowsDirectoryW.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetWindowsDirectoryW(buffer, len(buffer))
    if not 0 < size < len(buffer):
        raise SigningError("Windows directory unavailable")
    path = Path(buffer.value) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not path.is_file():
        raise SigningError("Windows PowerShell unavailable")
    return path


def _powershell_json(script, values):
    try:
        powershell = system_powershell()
        result = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
                + script,
            ],
            env={
                **os.environ,
                "PSModulePath": str(powershell.parent / "Modules"),
                **values,
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode or len(result.stdout) > 128 * 1024:
            raise SigningError("Windows signature query failed")
        data = json.loads(result.stdout.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise SigningError("Invalid signature query result")
        return data
    except (OSError, subprocess.SubprocessError, ValueError):
        raise SigningError("Windows signature query unavailable") from None


SIGNATURE_SCRIPT = r"""
Import-Module Microsoft.PowerShell.Security -ErrorAction Stop
$s=Get-AuthenticodeSignature -LiteralPath $env:EDU_SIGNATURE_FILE
$v=(Get-Item -LiteralPath $env:EDU_SIGNATURE_FILE).VersionInfo
$c=$s.SignerCertificate
$t=$s.TimeStamperCertificate
[ordered]@{
 status=[string]$s.Status
 type=[string]$s.SignatureType
 publisher=if($c){$c.Subject}else{''}
 simple_publisher=if($c){$c.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false)}else{''}
 thumbprint=if($c){$c.Thumbprint}else{''}
 not_before=if($c){$c.NotBefore.ToUniversalTime().ToString('o')}else{''}
 not_after=if($c){$c.NotAfter.ToUniversalTime().ToString('o')}else{''}
 certificate_expired_now=if($c){$c.NotAfter.ToUniversalTime() -lt [DateTime]::UtcNow}else{$null}
 timestamp_present=($null -ne $t)
 timestamp_publisher=if($t){$t.Subject}else{''}
 file_version=[string]$v.FileVersion
 product_version=[string]$v.ProductVersion
 product=[string]$v.ProductName
 description=[string]$v.FileDescription
 company=[string]$v.CompanyName
}|ConvertTo-Json -Compress
"""

CERTIFICATE_SCRIPT = r"""
$store=[Security.Cryptography.X509Certificates.X509Store]::new('My',$env:EDU_CERT_STORE)
$store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
try {
 $found=$store.Certificates.Find([Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint,$env:EDU_CERT_THUMBPRINT,$false)
 if($found.Count -ne 1){throw 'Explicit certificate missing or ambiguous'}
 $c=$found[0]
 [ordered]@{
  publisher=$c.Subject;thumbprint=$c.Thumbprint;private_key_present=$c.HasPrivateKey
  trusted=$c.Verify()
  not_before=$c.NotBefore.ToUniversalTime().ToString('o')
  not_after=$c.NotAfter.ToUniversalTime().ToString('o')
  code_signing=(@($c.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.37'} | ForEach-Object {$_.EnhancedKeyUsages} | ForEach-Object {$_.Value}) -contains '1.3.6.1.5.5.7.3.3')
 }|ConvertTo-Json -Compress
} finally {$store.Close()}
"""


def _regular_file(path):
    path = Path(path)
    if (
        not path.is_absolute()
        or path.is_symlink()
        or path.is_junction()
        or not path.is_file()
    ):
        raise SigningError("A regular absolute file is required")
    if any(p.is_symlink() or p.is_junction() for p in path.parents):
        raise SigningError("Reparse paths are not signing inputs")
    return path


def inspect_signature(path):
    """Windows trust result, public signer metadata and version, without signing."""
    path = _regular_file(path)
    return _powershell_json(SIGNATURE_SCRIPT, {"EDU_SIGNATURE_FILE": str(path)})


def _thumbprint(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise SigningError("An exact certificate thumbprint is required")
    return value.upper()


def _publisher(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 1024
        or any(ord(c) < 32 for c in value)
    ):
        raise SigningError("An explicit expected publisher subject is required")
    return value


def certificate_preflight(thumbprint, publisher, *, machine_store=False):
    thumbprint, publisher = _thumbprint(thumbprint), _publisher(publisher)
    data = _powershell_json(
        CERTIFICATE_SCRIPT,
        {
            "EDU_CERT_THUMBPRINT": thumbprint,
            "EDU_CERT_STORE": "LocalMachine" if machine_store else "CurrentUser",
        },
    )
    try:
        now = datetime.now(timezone.utc)
        valid_time = (
            datetime.fromisoformat(data["not_before"])
            <= now
            <= datetime.fromisoformat(data["not_after"])
        )
    except (KeyError, ValueError, TypeError):
        valid_time = False
    if (
        data.get("publisher") != publisher
        or data.get("thumbprint", "").upper() != thumbprint
        or not valid_time
        or any(
            data.get(key) is not True
            for key in ("trusted", "private_key_present", "code_signing")
        )
    ):
        raise SigningError(
            "Certificate identity, validity, trust, EKU or private key unavailable"
        )
    return data


def validate_signtool(path):
    path = _regular_file(path)
    signature = inspect_signature(path)
    if (
        path.name.casefold() != "signtool.exe"
        or signature.get("status") != "Valid"
        or signature.get("simple_publisher") != "Microsoft Corporation"
        or not any(
            marker in signature.get("description", "").casefold()
            for marker in ("signtool", "signing and verifying tool")
        )
    ):
        raise SigningError("A trusted Microsoft Windows SDK SignTool is required")
    libraries = list(path.parent.glob("*.dll"))
    if len(libraries) > 128:
        raise SigningError("Unexpected SDK library directory")
    for library in libraries:
        sig = inspect_signature(library)
        if (
            sig.get("status") != "Valid"
            or sig.get("simple_publisher") != "Microsoft Corporation"
        ):
            raise SigningError("Untrusted SDK support library")
    return path


def _run_tool(tool, arguments):
    with tempfile.TemporaryDirectory(prefix="edudownloader-signing-") as cwd:
        try:
            completed = subprocess.run(
                [str(tool), *map(str, arguments)],
                cwd=cwd,
                env={
                    **os.environ,
                    "PATH": str(system_powershell().parents[2])
                    + os.pathsep
                    + str(tool.parent),
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            raise SigningError("SignTool operation unavailable") from None
        if completed.returncode:
            raise SigningError(
                f"SignTool rejected signature operation or verification (exit {completed.returncode})"
            )


def verify_signature(
    path,
    *,
    expected_publisher,
    expected_thumbprint=None,
    require_timestamp=True,
    signtool=None,
):
    expected_publisher = _publisher(expected_publisher)
    data = inspect_signature(path)
    if (
        data.get("status") != "Valid"
        or data.get("publisher") != expected_publisher
        or data.get("type") != "Authenticode"
    ):
        raise SigningError(
            "Signature integrity, trust or publisher verification failed"
        )
    if expected_thumbprint is not None and data.get(
        "thumbprint", ""
    ).upper() != _thumbprint(expected_thumbprint):
        raise SigningError("Signing certificate does not match the authorized identity")
    if require_timestamp and data.get("timestamp_present") is not True:
        raise SigningError("A verified timestamp is required")
    if signtool is not None:
        tool = validate_signtool(signtool)
        _run_tool(
            tool,
            [
                "verify",
                "/pa",
                "/all",
                *(["/tw"] if require_timestamp else []),
                str(_regular_file(path)),
            ],
        )
    return data


def sign_copy(
    source,
    destination,
    *,
    signtool,
    thumbprint,
    expected_publisher,
    timestamp_url,
    machine_store=False,
):
    """Sign and verify a new output; failed operations never publish a result."""
    source, destination = _regular_file(source), Path(destination)
    if (
        source.suffix.casefold() not in (".exe", ".dll", ".pyd")
        or destination.suffix.casefold() != source.suffix.casefold()
        or not destination.is_absolute()
        or destination.exists()
        or destination.is_symlink()
        or destination.is_junction()
    ):
        raise SigningError("A new PE output with matching extension is required")
    if not destination.parent.is_dir() or any(
        p.is_symlink() or p.is_junction()
        for p in (destination.parent, *destination.parent.parents)
    ):
        raise SigningError("An ordinary existing output directory is required")
    if not isinstance(timestamp_url, str):
        raise SigningError("An explicit public RFC 3161 timestamp URL is required")
    try:
        url = urlsplit(timestamp_url)
    except ValueError:
        raise SigningError("Invalid RFC 3161 timestamp URL") from None
    if (
        url.scheme not in ("https", "http")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or any(ord(c) < 33 for c in timestamp_url)
    ):
        raise SigningError("An explicit RFC 3161 timestamp URL is required")
    thumbprint, expected_publisher = (
        _thumbprint(thumbprint),
        _publisher(expected_publisher),
    )
    tool = validate_signtool(signtool)
    certificate_preflight(thumbprint, expected_publisher, machine_store=machine_store)
    if inspect_signature(source).get("status") != "NotSigned":
        raise SigningError(
            "Existing signatures are preserved; supply a fresh unsigned own build"
        )
    staged = None
    try:
        fd, name = tempfile.mkstemp(
            prefix=".edu-signing-", suffix=source.suffix, dir=destination.parent
        )
        staged = Path(name)
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        arguments = [
            "sign",
            "/fd",
            "SHA256",
            "/sha1",
            thumbprint,
            "/s",
            "My",
            *(["/sm"] if machine_store else []),
            "/tr",
            timestamp_url,
            "/td",
            "SHA256",
            str(staged),
        ]
        _run_tool(tool, arguments)
        result = verify_signature(
            staged,
            expected_publisher=expected_publisher,
            expected_thumbprint=thumbprint,
            signtool=tool,
        )
        publish_new_file(staged, destination)
        with destination.open("rb") as signed:
            digest = hashlib.file_digest(signed, "sha256").hexdigest()
        return {
            "status": "verified",
            "sha256": digest,
            "publisher": result["publisher"],
            "thumbprint": thumbprint,
            "timestamp_present": True,
        }
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--signtool", type=Path)
    parser.add_argument("--thumbprint")
    parser.add_argument("--publisher")
    parser.add_argument("--timestamp-url")
    parser.add_argument("--machine-store", action="store_true")
    args = parser.parse_args()
    try:
        if args.destination is None:
            result = inspect_signature(args.source)
        else:
            if not all(
                (args.signtool, args.thumbprint, args.publisher, args.timestamp_url)
            ):
                raise SigningError(
                    "Signing requires explicit SDK, certificate, publisher and timestamp"
                )
            result = sign_copy(
                args.source,
                args.destination,
                signtool=args.signtool,
                thumbprint=args.thumbprint,
                expected_publisher=args.publisher,
                timestamp_url=args.timestamp_url,
                machine_store=args.machine_store,
            )
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except SigningError as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
