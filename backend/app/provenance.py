"""Build and test provenance values supplied by the execution environment."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Provenance:
    """Reproducibility metadata without secret or evidence content."""

    version: str
    commit_sha: str
    source: str


def current_provenance() -> Provenance:
    """Read provenance from explicit build variables, with honest local defaults."""

    return Provenance(
        version=os.getenv("RECLAIM_BUILD_VERSION", "unversioned"),
        commit_sha=os.getenv("RECLAIM_COMMIT_SHA", "unknown"),
        source=os.getenv("RECLAIM_PROVENANCE_SOURCE", "environment"),
    )
