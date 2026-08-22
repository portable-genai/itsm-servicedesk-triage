"""Policy packs as data: the versioned, cited policy the deterministic engines compute from.

A pack is CONFIGURATION, not code. Each file under ``config/packs/`` is a small, falsifiable
rule set. The loaders are strict on purpose: an UNKNOWN field, a missing required field or a
malformed value REFUSES at load rather than being ignored, because a pack that silently drops a
field it did not recognise is a policy nobody reviewed. This mirrors H2's entitlement-pack
convention (the wave's shared pack shape); the engines are not shared, only the shape is.

Pure stdlib plus ``yaml`` (itself stdlib-only at runtime); no web framework, no cloud SDK. Every
rule carries its own :class:`~.kernel.Citation` so a routing verdict or a segregation-of-duties
finding is traceable to a clause.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .kernel import Citation

#: The default location packs are read from, relative to the process working directory (the repo
#: root under ``make`` targets and ``/app`` in the image). Overridable by passing an explicit path
#: to each loader; never read from the environment here (a two-state env read is exactly what the
#: repo's own gate forbids), so the caller owns any override.
DEFAULT_PACKS_DIR = Path("config") / "packs"
_TRIAGE_SUBDIR = "triage"
_ACCESS_SUBDIR = "access"


class PackError(ValueError):
    """A pack is malformed, carries an unknown field, or fails a schema rule."""


def _require_mapping(data: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PackError(f"{where}: expected a mapping, got {type(data).__name__}")
    return data


def _reject_unknown(data: Mapping[str, Any], allowed: frozenset[str], *, where: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise PackError(
            f"{where}: unknown field(s) {sorted(unknown)}; a pack that carried a field the "
            "engine does not read would be a policy nobody reviewed"
        )


def _str_list(value: Any, *, field: str, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise PackError(f"{where}: field {field!r} must be a non-empty list")
    out: list[str] = []
    for item in value:
        text = str(item).strip().lower()
        if not text:
            raise PackError(f"{where}: field {field!r} contains an empty entry")
        out.append(text)
    return tuple(out)


# --------------------------------------------------------------------------------------------- #
# Triage taxonomy pack.
# --------------------------------------------------------------------------------------------- #

_ALLOWED_TAXONOMY_FIELDS = frozenset(
    {
        "version",
        "source_id",
        "source_title",
        "categories",
        "priority_severity",
        "default_category",
        "default_affected_service",
        "default_priority",
        "default_queue",
    }
)
_ALLOWED_CATEGORY_FIELDS = frozenset(
    {"category_id", "keywords", "affected_service", "priority", "queue", "citation_clause"}
)
_PRIORITY_BANDS = ("p1", "p2", "p3", "p4")


@dataclass(frozen=True, slots=True)
class TriageCategory:
    """One category rule: the keywords that select it and the routing it implies."""

    category_id: str
    keywords: tuple[str, ...]
    affected_service: str
    priority: str
    queue: str
    source_id: str
    source_title: str
    citation_clause: str

    def citation(self) -> Citation:
        return Citation(
            source_id=self.source_id,
            title=f"{self.source_title} {self.citation_clause}".strip(),
            snippet=self.category_id,
        )


@dataclass(frozen=True, slots=True)
class TriagePack:
    """The whole triage taxonomy, indexed for the engine. Immutable once built."""

    categories: tuple[TriageCategory, ...]
    priority_severity: Mapping[str, str]
    default_category: str
    default_affected_service: str
    default_priority: str
    default_queue: str
    source_id: str
    source_title: str

    def default_citation(self) -> Citation:
        return Citation(
            source_id=self.source_id,
            title=f"{self.source_title} default routing",
            snippet=self.default_category,
        )


def _category_from(raw: Any, *, source_id: str, source_title: str, where: str) -> TriageCategory:
    data = _require_mapping(raw, where=where)
    category_id = str(data.get("category_id") or "").strip()
    if not category_id:
        raise PackError(f"{where}: a category is missing its category_id")
    _reject_unknown(data, _ALLOWED_CATEGORY_FIELDS, where=category_id)
    missing = _ALLOWED_CATEGORY_FIELDS - set(data)
    if missing:
        raise PackError(f"{category_id}: missing required field(s) {sorted(missing)}")
    priority = str(data["priority"]).strip().lower()
    if priority not in _PRIORITY_BANDS:
        raise PackError(f"{category_id}: priority {priority!r} is not one of {_PRIORITY_BANDS}")
    return TriageCategory(
        category_id=category_id,
        keywords=_str_list(data["keywords"], field="keywords", where=category_id),
        affected_service=str(data["affected_service"]).strip(),
        priority=priority,
        queue=str(data["queue"]).strip(),
        source_id=source_id,
        source_title=source_title,
        citation_clause=str(data["citation_clause"]).strip(),
    )


def _priority_severity_from(raw: Any, *, where: str) -> dict[str, str]:
    data = _require_mapping(raw, where=f"{where}.priority_severity")
    mapping = {str(k).strip().lower(): str(v).strip().lower() for k, v in data.items()}
    missing = set(_PRIORITY_BANDS) - set(mapping)
    if missing:
        raise PackError(f"{where}: priority_severity is missing band(s) {sorted(missing)}")
    for band, sev in mapping.items():
        if band not in _PRIORITY_BANDS:
            raise PackError(f"{where}: priority_severity has unknown band {band!r}")
        if sev not in ("low", "medium", "high", "critical"):
            raise PackError(f"{where}: priority_severity[{band}] is not a severity: {sev!r}")
    return mapping


def load_triage_pack(packs_dir: Path | None = None) -> TriagePack:
    """Load and validate the single triage taxonomy pack.

    An explicit directory that does not exist RAISES: somebody named a location and running on an
    empty taxonomy instead is how an engine ends up routing on no policy at all. Exactly one
    taxonomy file is expected under ``<packs_dir>/triage``; category ids must be unique.
    """
    root = (packs_dir if packs_dir is not None else DEFAULT_PACKS_DIR) / _TRIAGE_SUBDIR
    if not root.exists():
        raise PackError(f"triage packs directory {root} does not exist")
    files = sorted(root.rglob("*.yaml"))
    if len(files) != 1:
        raise PackError(f"{root}: expected exactly one triage taxonomy file, found {len(files)}")
    path = files[0]
    data = _require_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), where=str(path))
    _reject_unknown(data, _ALLOWED_TAXONOMY_FIELDS, where=str(path))
    source_id = str(data.get("source_id") or "").strip()
    source_title = str(data.get("source_title") or "").strip()
    if not (source_id and source_title):
        raise PackError(f"{path}: source_id and source_title are required")
    raw_categories = data.get("categories")
    if not isinstance(raw_categories, list) or not raw_categories:
        raise PackError(f"{path}: 'categories' must be a non-empty list")
    categories: list[TriageCategory] = []
    seen: set[str] = set()
    for raw in raw_categories:
        category = _category_from(
            raw, source_id=source_id, source_title=source_title, where=str(path)
        )
        if category.category_id in seen:
            raise PackError(f"{path}: duplicate category_id {category.category_id!r}")
        seen.add(category.category_id)
        categories.append(category)
    default_priority = str(data.get("default_priority") or "").strip().lower()
    if default_priority not in _PRIORITY_BANDS:
        raise PackError(f"{path}: default_priority {default_priority!r} is not a priority band")
    for field_name in ("default_category", "default_affected_service", "default_queue"):
        if not str(data.get(field_name) or "").strip():
            raise PackError(f"{path}: {field_name} is required")
    return TriagePack(
        categories=tuple(categories),
        priority_severity=_priority_severity_from(data.get("priority_severity"), where=str(path)),
        default_category=str(data["default_category"]).strip(),
        default_affected_service=str(data["default_affected_service"]).strip(),
        default_priority=default_priority,
        default_queue=str(data["default_queue"]).strip(),
        source_id=source_id,
        source_title=source_title,
    )


# --------------------------------------------------------------------------------------------- #
# Access / segregation-of-duties policy pack.
# --------------------------------------------------------------------------------------------- #

_ALLOWED_POLICY_FIELDS = frozenset(
    {"version", "source_id", "source_title", "roles", "sod_conflicts", "approval_chains"}
)
_ALLOWED_ROLE_FIELDS = frozenset({"role_id", "entitlements", "risk_tier", "citation_clause"})
_ALLOWED_CONFLICT_FIELDS = frozenset({"conflict_id", "entitlements", "detail", "citation_clause"})
_RISK_TIERS = ("low", "medium", "high", "critical")


@dataclass(frozen=True, slots=True)
class Role:
    """One catalog role: the entitlements it grants and its risk tier."""

    role_id: str
    entitlements: frozenset[str]
    risk_tier: str
    source_id: str
    source_title: str
    citation_clause: str

    def citation(self) -> Citation:
        return Citation(
            source_id=self.source_id,
            title=f"{self.source_title} {self.citation_clause}".strip(),
            snippet=self.role_id,
        )


@dataclass(frozen=True, slots=True)
class SoDConflict:
    """One toxic combination: a pair of entitlements that must never coexist."""

    conflict_id: str
    entitlements: frozenset[str]
    detail: str
    source_id: str
    source_title: str
    citation_clause: str

    def citation(self) -> Citation:
        return Citation(
            source_id=self.source_id,
            title=f"{self.source_title} {self.citation_clause}".strip(),
            snippet=self.conflict_id,
        )


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """The whole access policy, indexed for the engine. Immutable once built."""

    roles: Mapping[str, Role]
    conflicts: tuple[SoDConflict, ...]
    approval_chains: Mapping[str, tuple[str, ...]]
    source_id: str
    source_title: str

    def role(self, role_id: str) -> Role | None:
        """The role for this id, or ``None`` when nothing matches (the engine fails closed)."""
        return self.roles.get(role_id.strip())

    def conflicts_for(self, entitlements: frozenset[str]) -> tuple[SoDConflict, ...]:
        """Every toxic combination FULLY present in ``entitlements``. Empty means clean."""
        return tuple(c for c in self.conflicts if c.entitlements <= entitlements)

    def chain_for(self, risk_tier: str) -> tuple[str, ...]:
        """The approver chain for a risk tier; the critical chain if the tier is unknown."""
        return self.approval_chains.get(risk_tier, self.approval_chains["critical"])


def _role_from(raw: Any, *, source_id: str, source_title: str, where: str) -> Role:
    data = _require_mapping(raw, where=where)
    role_id = str(data.get("role_id") or "").strip()
    if not role_id:
        raise PackError(f"{where}: a role is missing its role_id")
    _reject_unknown(data, _ALLOWED_ROLE_FIELDS, where=role_id)
    missing = _ALLOWED_ROLE_FIELDS - set(data)
    if missing:
        raise PackError(f"{role_id}: missing required field(s) {sorted(missing)}")
    risk_tier = str(data["risk_tier"]).strip().lower()
    if risk_tier not in _RISK_TIERS:
        raise PackError(f"{role_id}: risk_tier {risk_tier!r} is not one of {_RISK_TIERS}")
    return Role(
        role_id=role_id,
        entitlements=frozenset(
            _str_list(data["entitlements"], field="entitlements", where=role_id)
        ),
        risk_tier=risk_tier,
        source_id=source_id,
        source_title=source_title,
        citation_clause=str(data["citation_clause"]).strip(),
    )


def _conflict_from(raw: Any, *, source_id: str, source_title: str, where: str) -> SoDConflict:
    data = _require_mapping(raw, where=where)
    conflict_id = str(data.get("conflict_id") or "").strip()
    if not conflict_id:
        raise PackError(f"{where}: a conflict is missing its conflict_id")
    _reject_unknown(data, _ALLOWED_CONFLICT_FIELDS, where=conflict_id)
    missing = _ALLOWED_CONFLICT_FIELDS - set(data)
    if missing:
        raise PackError(f"{conflict_id}: missing required field(s) {sorted(missing)}")
    entitlements = _str_list(data["entitlements"], field="entitlements", where=conflict_id)
    if len(set(entitlements)) < 2:
        raise PackError(f"{conflict_id}: a conflict needs at least two distinct entitlements")
    return SoDConflict(
        conflict_id=conflict_id,
        entitlements=frozenset(entitlements),
        detail=str(data["detail"]).strip(),
        source_id=source_id,
        source_title=source_title,
        citation_clause=str(data["citation_clause"]).strip(),
    )


def _approval_chains_from(raw: Any, *, where: str) -> dict[str, tuple[str, ...]]:
    data = _require_mapping(raw, where=f"{where}.approval_chains")
    chains: dict[str, tuple[str, ...]] = {}
    for tier, approvers in data.items():
        tier_name = str(tier).strip().lower()
        if tier_name not in _RISK_TIERS:
            raise PackError(f"{where}: approval_chains has unknown risk tier {tier_name!r}")
        chains[tier_name] = _str_list(approvers, field=f"approval_chains.{tier_name}", where=where)
    missing = set(_RISK_TIERS) - set(chains)
    if missing:
        raise PackError(f"{where}: approval_chains is missing tier(s) {sorted(missing)}")
    return chains


def _conflicts_from(
    raw: Any, *, source_id: str, source_title: str, where: str
) -> Iterable[SoDConflict]:
    if not isinstance(raw, list) or not raw:
        raise PackError(f"{where}: 'sod_conflicts' must be a non-empty list")
    seen: set[str] = set()
    out: list[SoDConflict] = []
    for item in raw:
        conflict = _conflict_from(item, source_id=source_id, source_title=source_title, where=where)
        if conflict.conflict_id in seen:
            raise PackError(f"{where}: duplicate conflict_id {conflict.conflict_id!r}")
        seen.add(conflict.conflict_id)
        out.append(conflict)
    return out


def load_access_policy(packs_dir: Path | None = None) -> AccessPolicy:
    """Load and validate the single access / segregation-of-duties policy pack.

    An explicit directory that does not exist RAISES. Exactly one policy file is expected under
    ``<packs_dir>/access``; role ids must be unique. Every entitlement named in an SoD conflict
    must be grantable by some role, so a conflict can never reference a typo that no role emits.
    """
    root = (packs_dir if packs_dir is not None else DEFAULT_PACKS_DIR) / _ACCESS_SUBDIR
    if not root.exists():
        raise PackError(f"access packs directory {root} does not exist")
    files = sorted(root.rglob("*.yaml"))
    if len(files) != 1:
        raise PackError(f"{root}: expected exactly one access policy file, found {len(files)}")
    path = files[0]
    data = _require_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), where=str(path))
    _reject_unknown(data, _ALLOWED_POLICY_FIELDS, where=str(path))
    source_id = str(data.get("source_id") or "").strip()
    source_title = str(data.get("source_title") or "").strip()
    if not (source_id and source_title):
        raise PackError(f"{path}: source_id and source_title are required")
    raw_roles = data.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise PackError(f"{path}: 'roles' must be a non-empty list")
    roles: dict[str, Role] = {}
    for raw in raw_roles:
        role = _role_from(raw, source_id=source_id, source_title=source_title, where=str(path))
        if role.role_id in roles:
            raise PackError(f"{path}: duplicate role_id {role.role_id!r}")
        roles[role.role_id] = role
    conflicts = tuple(
        _conflicts_from(
            data.get("sod_conflicts"),
            source_id=source_id,
            source_title=source_title,
            where=str(path),
        )
    )
    grantable = frozenset().union(*(role.entitlements for role in roles.values()))
    for conflict in conflicts:
        orphan = conflict.entitlements - grantable
        if orphan:
            raise PackError(
                f"{conflict.conflict_id}: entitlement(s) {sorted(orphan)} are named in a conflict "
                "but no role grants them; a conflict must reference real entitlements"
            )
    return AccessPolicy(
        roles=roles,
        conflicts=conflicts,
        approval_chains=_approval_chains_from(data.get("approval_chains"), where=str(path)),
        source_id=source_id,
        source_title=source_title,
    )
