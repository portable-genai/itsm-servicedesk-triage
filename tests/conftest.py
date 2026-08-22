"""Shared fixtures for every suite: the REAL local adapters, never bespoke fakes.

The offline implementation must live in exactly one place, so the unit suite drives
``adapters/local`` rather than a parallel set of in-memory doubles that can drift from it. Every
adapter constructs from a single ``Settings`` pointed at ``:memory:``, which is also the adapter
convention the contract suite asserts.

``no_cloud_sdk`` is the portability harness: it makes ``google`` and every submodule
UNIMPORTABLE for the duration of a test, so "the SDK-free profiles construct with no cloud SDK"
is proved by blocking the import rather than by hoping the machine has none installed.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from itsm_servicedesk_triage.config import (
    Container,
    Settings,
    build_container,
)
from itsm_servicedesk_triage.domain.triage_service import (
    TriageService,
)

from .fixtures import sample_cases

#: A loopback peer: the app-object exposure guard refuses the unauthenticated local posture to
#: any other peer, and TestClient's default peer is the literal host "testclient".
LOOPBACK_PEER = ("127.0.0.1", 50000)

#: The prefix whose imports the SDK-free proof blocks (every managed SDK this repo lazily uses).
BLOCKED_SDK_ROOTS: tuple[str, ...] = ("google",)


def local_settings(**overrides: Any) -> Settings:
    """``local`` profile settings on ephemeral stores, plus any per-test override."""
    base: dict[str, Any] = {
        "profile": "local",
        "audit_path": ":memory:",
        "tenant": sample_cases.TENANT,
    }
    base.update(overrides)
    return Settings(**base)


#: The fields of an outbound Hrz7 review that carry CASE CONTENT rather than attribution.
#: ``maker`` is the VERIFIED principal and is an address by design, exactly like the audit row's
#: ``actor``, and ``tenant`` is a partition name; a pattern scan over the whole payload would
#: therefore flag the two fields whose job is to say WHO and WHERE, could never go green, and a
#: check that can never go green is a check somebody switches off.
_REVIEW_CONTENT_FIELDS: tuple[str, ...] = (
    "subject",
    "summary",
    "case_ref",
    "source_key",
    "citations",
)


def audit_content(rows: Iterable[Mapping[str, Any]]) -> str:
    """The CONTENT-bearing fields of persisted audit rows, as one scannable string.

    The same field selection the shipped ``eval/run_eval.py:audit_surfaces`` makes, and for the
    same reason: ``redacted_summary`` is one field of several the WORM record keeps, and a check
    that reads it alone certifies a record whose citations still carry the identifier.
    """
    return json.dumps(
        [[row.get("redacted_summary", ""), row.get("citations", [])] for row in rows], default=str
    )


def outbound_content(review: Any) -> str:
    """The CONTENT-bearing fields of an outbound Hrz7 review payload, as one scannable string."""
    payload = review.to_payload()
    return json.dumps([payload[field] for field in _REVIEW_CONTENT_FIELDS], default=str)


def is_blocked_sdk(fullname: str, roots: Sequence[str] = BLOCKED_SDK_ROOTS) -> bool:
    """True when ``fullname`` is one of the blocked roots or lives under one."""
    return any(fullname == root or fullname.startswith(root + ".") for root in roots)


class _BlockedSdkFinder:
    """A meta-path finder that refuses the blocked roots, whatever is installed."""

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if is_blocked_sdk(fullname):
            raise ModuleNotFoundError(
                f"{fullname} is blocked: this profile must construct with no cloud SDK present"
            )
        return None


@pytest.fixture()
def settings() -> Settings:
    return local_settings()


@pytest.fixture()
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture()
def triage_service(container: Container) -> TriageService:
    return TriageService(container.audit, tracer=container.tracer)


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    """The API served to a loopback peer, which is the only posture the local profile allows."""
    from itsm_servicedesk_triage.api.app import app

    with TestClient(app, client=LOOPBACK_PEER) as client:
        yield client


@pytest.fixture()
def no_cloud_sdk() -> Iterator[None]:
    """Make the managed SDKs unimportable, and restore the interpreter afterwards."""
    finder = _BlockedSdkFinder()
    evicted: dict[str, ModuleType] = {
        name: module for name, module in sys.modules.items() if is_blocked_sdk(name)
    }
    for name in evicted:
        del sys.modules[name]
    sys.meta_path.insert(0, finder)  # type: ignore[arg-type]
    try:
        yield
    finally:
        sys.meta_path.remove(finder)  # type: ignore[arg-type]
        sys.modules.update(evicted)


def reimport(module_name: str) -> ModuleType:
    """Import ``module_name`` from scratch, so an import-time failure is actually observed."""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)
