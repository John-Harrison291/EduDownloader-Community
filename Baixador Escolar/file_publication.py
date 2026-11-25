"""Exclusive publication of an already-flushed, parent-local temporary file.

Windows rename fails if the target exists, including on FAT/exFAT. It avoids
requiring NTFS hard links. POSIX keeps link-based exclusive publication.
Destination validation, ownership and temporary cleanup remain with callers.
"""

import errno
import os
from pathlib import Path
import stat


def publish_new_file(staged: Path, destination: Path, *, check_cancel=lambda: None):
    if (
        not staged.is_absolute()
        or not destination.is_absolute()
        or any(p.is_symlink() or p.is_junction() for p in staged.parents)
        or any(p.is_symlink() or p.is_junction() for p in destination.parents)
        or staged.parent.resolve(strict=True) != destination.parent.resolve(strict=True)
        or staged == destination
        or staged.is_symlink()
        or staged.is_junction()
        or not stat.S_ISREG(staged.stat().st_mode)
    ):
        raise OSError(errno.EXDEV, "Publication requires an owned parent-local file")
    check_cancel()
    if os.name == "nt":
        os.rename(staged, destination)  # Windows: no replacement, same volume.
    else:
        os.link(staged, destination)
