"""Identidade e layout do candidato Community."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

from constants import ProductEdition, edition_version


@dataclass(frozen=True, slots=True)
class EditionBuildProfile:
    """Candidato de compilação local da Community."""

    edition: ProductEdition

    def __post_init__(self) -> None:
        if not isinstance(self.edition, ProductEdition):
            raise ValueError("An explicit ProductEdition is required")

    @property
    def production_ready(self) -> bool:
        return False

    @property
    def public_release_allowed(self) -> bool:
        return False

    @property
    def app_version(self) -> str:
        return edition_version(self.edition)

    @property
    def output_directory(self) -> str:
        return f"EduDownloader-{self.app_version}-{self.edition.value.title()}"

    @property
    def entrypoint(self) -> str:
        return "frozen_community.py"

    def as_contract(self) -> dict[str, object]:
        return {
            **asdict(self),
            "app_version": self.app_version,
            "production_ready": self.production_ready,
            "public_release_allowed": self.public_release_allowed,
            "output_directory": self.output_directory,
            "entrypoint": self.entrypoint,
            "spec": "EduDownloader.spec",
            "candidate_pipeline_ready": True,
        }


def select_build_profile(edition: str) -> EditionBuildProfile:
    """Select only known identities; never default an invalid value."""

    return EditionBuildProfile(ProductEdition(edition))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", required=True, choices=list(ProductEdition))
    args = parser.parse_args()
    print(json.dumps(select_build_profile(args.edition).as_contract(), sort_keys=True))


if __name__ == "__main__":
    main()
