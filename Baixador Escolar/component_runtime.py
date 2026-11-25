"""Mantém os consumidores compartilhados independentes do atualizador Community."""

from contextlib import nullcontext
from pathlib import Path

from constants import PRODUCT_EDITION, ProductEdition


def active_component(base_dir: Path, name: str):
    if PRODUCT_EDITION is ProductEdition.COMMUNITY:
        from component_updates import active_component as resolve

        return resolve(base_dir, name)
    return None


def active_ocr(base_dir: Path):
    if PRODUCT_EDITION is ProductEdition.COMMUNITY:
        from component_updates import active_ocr as resolve

        return resolve(base_dir)
    return None


def component_use(base_dir: Path, *names: str):
    if PRODUCT_EDITION is ProductEdition.COMMUNITY:
        from component_updates import component_use as lease

        return lease(base_dir, *names)
    return nullcontext()
