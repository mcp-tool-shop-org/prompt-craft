"""The domain-plugin registry + fail-closed ``detect`` (the readouts shared-core/plugins pattern).

A plugin declares its three secrets -- a ``Generator``, a tiered set of ``Verifier``s, and the path to
its (generated) encoder-craft rules -- plus an optional subdomain hook. Adding ``video`` or
``workflow`` is one ``register`` call; ``core/`` never changes. ``detect`` selects a plugin by name and
FAILS CLOSED when none matches (no silent default -- a silent fallback would bind the wrong
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
    """Add a domain plugin. FAIL-CLOSED on a malformed plugin or a name already taken.

    [!] Both guards added for F-d1d2833f. This was a bare ``_REGISTRY[plugin.name] = plugin``:

    * A second registration under an existing name SILENTLY overwrote the first -- no warning,
      no log, no error -- against the strong precedent set twice in this same package:
      ``ContractStore.__init__`` raises INPUT_DUPLICATE_CONTRACT_ID and
      ``schema._reject_duplicate_ids`` raises CONTRACT_DUPLICATE_ATOM_ID, both fail-closed on
      "two things claiming the same identity". The registry is the higher-stakes of the three:
      ``get(name)`` is what ``cli/__init__.py`` uses to select the Generator that gets bound
      (real GPU / Cloud spend), so a clobbered registration misroutes generation with no
      signal anywhere.
    * Nothing checked that the object actually satisfies ``DomainPlugin`` (already declared
      ``@runtime_checkable``), so a malformed plugin registered cleanly and failed later as a
      raw AttributeError at whatever call site first touched the missing method.

    Not reachable today -- ``register`` is called from exactly one site, the sole shipped
    domain plugin -- but this module's own docstring names the intended near-future shape
    ("Adding ``video`` or ``workflow`` is one ``register`` call"), and ``_REGISTRY`` is
    unscoped module-global state with no reset hook, so a future second domain reusing a name
    would go undetected.
    """
    if not isinstance(plugin, DomainPlugin):
        raise PromptCraftError(
            "INPUT_INVALID_DOMAIN_PLUGIN",
            f"{type(plugin).__name__} does not satisfy the DomainPlugin protocol",
            hint="A domain plugin needs a `name` plus generator(), verifiers() and "
            "encoder_rules_path(). Registering without them defers the failure to the first "
            "call site that touches the missing member, as a raw AttributeError.",
        )
    if plugin.name in _REGISTRY:
        raise PromptCraftError(
            "INPUT_DUPLICATE_DOMAIN",
            f"a domain plugin named {plugin.name!r} is already registered",
            hint="Two plugins may not claim one domain name: get(name) selects the generator "
            "that gets bound, so the second registration would silently misroute generation. "
            "Give the new domain its own name.",
        )
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
