"""Every name in STABILITY.md must resolve.

STABILITY.md is a promise about interfaces. A promise that names a command or an import path
the package no longer has is worse than no promise: it reads as verified. So the document is
parsed here and each name it mentions is looked up for real.

This is deliberately a check on the DOCUMENT, not a restatement of it. Hard-coding the list
here would let the two drift apart in exactly the way the document exists to prevent.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from pcraft.cli import app

STABILITY = Path(__file__).resolve().parent.parent / "STABILITY.md"

_CLI = re.compile(r"^pcraft ([a-z][a-z-]*)$")
_DOTTED = re.compile(r"^pcraft(?:\.[a-z_][a-z0-9_]*)+$")


def _backticked(text: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", text)


def test_the_document_exists_and_is_not_a_stub():
    assert STABILITY.is_file(), "STABILITY.md is criterion 4; without it the promise is unstated"
    assert len(STABILITY.read_text(encoding="utf-8")) > 2000


def test_every_cli_command_named_in_the_promise_exists():
    text = STABILITY.read_text(encoding="utf-8")
    named = {m.group(1) for tok in _backticked(text) if (m := _CLI.match(tok))}
    assert named, "the document names no CLI commands; it should name the covered ones"

    registered = {c.name or c.callback.__name__.replace("_", "-") for c in app.registered_commands}
    missing = sorted(named - registered)
    assert not missing, f"STABILITY.md promises CLI commands that do not exist: {missing}"


def test_every_module_path_named_in_the_promise_imports():
    text = STABILITY.read_text(encoding="utf-8")
    dotted = sorted({tok for tok in _backticked(text) if _DOTTED.match(tok)})
    assert dotted, "the document names no import paths"

    unresolved: list[str] = []
    for name in dotted:
        try:
            importlib.import_module(name)
            continue
        except ImportError:
            pass
        # `pcraft.package_version` is an attribute of a module, not a module. A name in the
        # promise resolves if it is either.
        parent, _, attr = name.rpartition(".")
        try:
            if not hasattr(importlib.import_module(parent), attr):
                unresolved.append(name)
        except ImportError:
            unresolved.append(name)
    assert not unresolved, f"STABILITY.md names paths that do not resolve: {unresolved}"


@pytest.mark.parametrize(
    ("module", "symbol"),
    [
        ("pcraft", "package_version"),
        ("pcraft.errors", "PromptCraftError"),
        ("pcraft.errors", "exit_code_for"),
        ("pcraft.sample", "load_sprite_example"),
        ("pcraft.sample", "load_store"),
        ("pcraft.sample", "load_workspace"),
        ("pcraft.sample", "run_mock_loop"),
        ("pcraft.core.contract.schema", "Contract"),
        ("pcraft.core.contract.schema", "ResolvedContract"),
        ("pcraft.core.contract.schema", "Atom"),
        ("pcraft.core.contract.schema", "MustNot"),
        ("pcraft.core.contract.schema", "Severity"),
        ("pcraft.core.contract.schema", "CheckType"),
        ("pcraft.core.receipt.asset_record", "AssetRecord"),
        ("pcraft.core.receipt.asset_record", "load"),
        ("pcraft.core.receipt.asset_record", "persist"),
        ("pcraft.core.receipt.asset_record", "replay"),
        ("pcraft.core.gate.harness", "GateTranscript"),
        ("pcraft.core.loop.retry_policy", "Verdict"),
        ("pcraft.core.loop.retry_policy", "OutcomeClass"),
        ("pcraft.core.loop.retry_policy", "RepairAction"),
        ("pcraft.core.loop.retry_policy", "Attempt"),
    ],
)
def test_every_promised_symbol_exists(module: str, symbol: str):
    """The import-paths table promises these by name. Each is a separate case so a failure
    names the one that broke rather than the whole table."""
    assert hasattr(importlib.import_module(module), symbol), f"{module}.{symbol} is promised"
    doc = STABILITY.read_text(encoding="utf-8")
    assert f"`{symbol}`" in doc or f"`{module}.{symbol}`" in doc, (
        f"{module}.{symbol} is asserted here but no longer named in STABILITY.md — "
        "the test and the promise have drifted apart"
    )


def test_the_excluded_names_are_real_too():
    """The exclusions have to be as accurate as the promises. Naming a module as out-of-scope
    when it does not exist would be reassurance about nothing."""
    for name in (
        "pcraft.domains.image.subdomains.sprite.identity_subgate",
        "pcraft.core.optimize",
        "pcraft.domains.image.subdomains.sprite",
    ):
        importlib.import_module(name)
        assert f"`{name}`" in STABILITY.read_text(encoding="utf-8")


def test_the_identity_subgate_is_still_unwired_as_the_promise_states():
    """STABILITY.md tells readers the sub-gate gates nothing. If it ever gets wired, that
    sentence becomes false and this test is where that gets caught."""
    from pcraft.core.loop import orchestrate

    src = Path(orchestrate.__file__).read_text(encoding="utf-8")
    assert "identity_subgate" not in src, (
        "the sub-gate appears to be wired into orchestrate; STABILITY.md says it gates nothing"
    )
