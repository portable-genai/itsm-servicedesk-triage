"""The config boundary for triage and access packs: the only place a pack file is parsed.

A pack is the client's taxonomy or its segregation-of-duties policy, so validating one is domain
logic and lives in :mod:`itsm_servicedesk_triage.domain.packs`. What lives HERE is the half that
touches the world outside the hexagon: where packs sit, that there is exactly one of each,
reading those bytes, and turning YAML into a plain Python mapping.

The split runs along "fact about a filesystem" versus "rule about a policy". That a directory
exists and holds exactly one taxonomy file is the first kind and is refused here. That category
ids are unique, and that every entitlement in an SoD conflict is grantable by some role, is the
second kind and is refused by the core : which is why those refusals survive a pack that never
came from a file at all.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .domain.access_engine import AccessEngine
from .domain.packs import (
    AccessPolicy,
    PackError,
    TriagePack,
    build_access_policy,
    build_triage_pack,
)
from .domain.triage_engine import TriageEngine

__all__ = [
    "DEFAULT_PACKS_DIR",
    "default_access_engine",
    "default_access_policy",
    "default_triage_engine",
    "default_triage_pack",
    "load_access_policy",
    "load_triage_pack",
]

#: The default location packs are read from, relative to the process working directory (the repo
#: root under ``make`` targets and ``/app`` in the image). Overridable by passing an explicit path
#: to each loader; never read from the environment here (a two-state env read is exactly what the
#: repo's own gate forbids), so the caller owns any override.
DEFAULT_PACKS_DIR = Path("config") / "packs"
_TRIAGE_SUBDIR = "triage"
_ACCESS_SUBDIR = "access"


def _sole_pack_document(packs_dir: Path | None, subdir: str, kind: str) -> tuple[str, Any]:
    """Resolve the one pack file under ``<packs_dir>/<subdir>`` and parse it.

    An explicit directory that does not exist RAISES: somebody named a location, and running on
    an empty taxonomy instead is how an engine ends up routing on no policy at all. Finding
    zero or several files raises for the same reason : silently picking one would make which
    policy is in force depend on sort order.
    """
    root = (packs_dir if packs_dir is not None else DEFAULT_PACKS_DIR) / subdir
    if not root.exists():
        raise PackError(f"{kind} packs directory {root} does not exist")
    files = sorted(root.rglob("*.yaml"))
    if len(files) != 1:
        raise PackError(f"{root}: expected exactly one {kind} file, found {len(files)}")
    path = files[0]
    return str(path), yaml.safe_load(path.read_text(encoding="utf-8"))


def load_triage_pack(packs_dir: Path | None = None) -> TriagePack:
    """Read and validate the single triage taxonomy pack."""
    where, document = _sole_pack_document(packs_dir, _TRIAGE_SUBDIR, "triage taxonomy")
    return build_triage_pack(document, where=where)


def load_access_policy(packs_dir: Path | None = None) -> AccessPolicy:
    """Read and validate the single access / segregation-of-duties policy pack."""
    where, document = _sole_pack_document(packs_dir, _ACCESS_SUBDIR, "access policy")
    return build_access_policy(document, where=where)


@lru_cache(maxsize=1)
def default_triage_pack() -> TriagePack:
    """The taxonomy shipped under ``config/packs/triage``, loaded once. Callers may inject one."""
    return load_triage_pack()


@lru_cache(maxsize=1)
def default_access_policy() -> AccessPolicy:
    """The policy shipped under ``config/packs/access``, loaded once. Callers may inject one."""
    return load_access_policy()


def default_triage_engine() -> TriageEngine:
    """An engine bound to the shipped taxonomy (the offline default the surfaces build)."""
    return TriageEngine(default_triage_pack())


def default_access_engine() -> AccessEngine:
    """An engine bound to the shipped policy (the offline default the surfaces build)."""
    return AccessEngine(default_access_policy())
