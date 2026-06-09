"""The domain-plugin registry + fail-closed ``detect`` (the readouts shared-core/plugins pattern).

A plugin declares its three secrets — a ``Generator``, a tiered set of ``Verifier``s, and the path to
its (generated) encoder-craft rules — plus an optional subdomain hook. Adding ``video`` or
``workflow`` is one ``register`` call; ``core/`` never changes. ``detect`` selects a plugin by name and
FAILS CLOSED when none matches (no silent default — a silent fallback would bind the wrong
generator to the wrong contract)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..errors import PromptCraftError
from .gate.verifier_iface import Verifier
from .loop.generator_iface import Generator


@runtime_checkable
class DomainPlugin(Protocol):
    name: str

    def generator(self) -> Generator: ...
    def verifiers(self) -> dict[int, Verifier]: ...  # keyed by tier (0/1/2)
    def encoder_rules_path(self) -> Path: ...


_REGISTRY: dict[str, DomainPlugin] = {}


def register(plugin: DomainPlugin) -> None:
    _REGISTRY[plugin.name] = plugin


def get(name: str) -> DomainPlugin:
    if name not in _REGISTRY:
        raise PromptCraftError(
            "INPUT_UNKNOWN_DOMAIN",
            f"no domain plugin named {name!r} is registered (have: {sorted(_REGISTRY)})",
            hint="Import the domain package (e.g. `import pcraft.domains.image`) to register it.",
        )
    return _REGISTRY[name]


def detect(name: str | None) -> DomainPlugin:
    """Fail-closed selection: a name must resolve to a registered plugin; never a default."""
    if not name:
        raise PromptCraftError("INPUT_NO_DOMAIN", "a domain name is required (no default)")
    return get(name)


def registered() -> list[str]:
    return sorted(_REGISTRY)
