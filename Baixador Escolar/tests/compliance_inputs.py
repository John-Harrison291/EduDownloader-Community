"""Explicit input root for optional, large third-party source evidence."""

import os
from pathlib import Path
import unittest

PROJECT_DIR = Path(__file__).resolve().parents[1]


def evidence_path(relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected a project-relative evidence path")
    root = os.environ.get("EDUDOWNLOADER_COMPLIANCE_INPUTS")
    result = (Path(root).resolve(strict=True) if root else PROJECT_DIR) / path
    if not result.exists() and not root:
        raise unittest.SkipTest(f"Insumo externo de conformidade ausente: {relative}")
    return result
