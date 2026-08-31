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
from pcraft.errors import PromptCraftError

STABILITY = Path(__file__).resolve().parent.parent / "STABILITY.md"

_CLI = re.compile(r"^pcraft ([a-z][a-z-]*)$")
_DOTTED = re.compile(r"^pcraft(?:\.[a-z_][a-z0-9_]*)+$")

# A row of the "Import paths" table: a backticked module in the first cell, its promise in the
# second. Rows whose first cell is not a single backticked token (the on-disk-formats table) and
# rows naming a CLI command rather than a module are filtered out by _DOTTED below.
_TABLE_ROW = re.compile(r"^\|\s*`([^`\n]+)`\s*\|(.+)\|\s*$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Named in the `pcraft.errors` row as the SHAPE of PromptCraftError ("its `code` / `message` /
# `hint` shape"), not as module-level names -- so they cannot be looked up with getattr on the
# module the way every other promised symbol can. They are still promised, and they are still
# checked: by test_the_error_shape_exposes_code_message_and_hint below, which is where an
# assertion about a class's attributes belongs. This set is the exemption's whole extent; it is
# not a place to park a symbol nobody wants to test.
_ATTRIBUTES_OF_THE_ERROR_TYPE = frozenset({"code", "message", "hint"})


def _backticked(text: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", text)


def _symbols_the_document_names() -> set[tuple[str, str]]:
    """Every (module, symbol) pair the import-paths table promises, read out of the document.

    This is the doc -> test direction. Without it the surface check only ran test -> doc: the
    parametrize list below asserts each symbol it names is still IN the document, so a symbol
    the document names and the list never picked up was simply never checked (F-41dfcced --
    `Verifier` had been in that gap since the row was written).
    """
    pairs: set[tuple[str, str]] = set()
    for line in STABILITY.read_text(encoding="utf-8").splitlines():
        row = _TABLE_ROW.match(line.strip())
        if not row or not _DOTTED.match(row.group(1)):
            continue
        module = row.group(1)
        for token in _backticked(row.group(2)):
            if _IDENTIFIER.match(token) and token not in _ATTRIBUTES_OF_THE_ERROR_TYPE:
                pairs.add((module, token))
    return pairs


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


_PROMISED_SYMBOLS: list[tuple[str, str]] = [
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
        # F-41dfcced: promised by the harness row since it was written, checked by nothing until
        # the doc -> test direction below started reading the table.
        ("pcraft.core.gate.harness", "Verifier"),
        ("pcraft.core.loop.retry_policy", "Verdict"),
        ("pcraft.core.loop.retry_policy", "OutcomeClass"),
        ("pcraft.core.loop.retry_policy", "RepairAction"),
        ("pcraft.core.loop.retry_policy", "Attempt"),
]


@pytest.mark.parametrize(("module", "symbol"), _PROMISED_SYMBOLS)
def test_every_promised_symbol_exists(module: str, symbol: str):
    """The import-paths table promises these by name. Each is a separate case so a failure
    names the one that broke rather than the whole table."""
    assert hasattr(importlib.import_module(module), symbol), f"{module}.{symbol} is promised"
    doc = STABILITY.read_text(encoding="utf-8")
    assert f"`{symbol}`" in doc or f"`{module}.{symbol}`" in doc, (
        f"{module}.{symbol} is asserted here but no longer named in STABILITY.md — "
        "the test and the promise have drifted apart"
    )


def test_the_checked_list_covers_every_symbol_the_document_names():
    """F-41dfcced: the missing direction. The per-symbol test above only fires test -> doc --
    it catches a symbol dropped from STABILITY.md, and cannot catch a symbol the document
    promises that this file never picked up. That gap was not hypothetical: the
    `pcraft.core.gate.harness` row has always promised "GateTranscript and the `Verifier`
    protocol", the list carried only GateTranscript, and no test anywhere in the suite
    referenced harness.Verifier -- it resolved purely because harness.py imports it from
    verifier_iface for its own type hints, an incidental re-export nothing pinned.

    A promise-verification test that silently covers less than the promise is the exact pattern
    this repo exists to prosecute, so the coverage is now read out of the document itself."""
    named = _symbols_the_document_names()
    assert named, "parsed no symbols out of the import-paths table; the parser has drifted"
    missing = sorted(named - set(_PROMISED_SYMBOLS))
    assert not missing, (
        f"STABILITY.md promises these and nothing checks them: {missing}. Add them to "
        "_PROMISED_SYMBOLS -- an unadded symbol must fail loudly, not go unchecked."
    )


def test_the_error_shape_exposes_code_message_and_hint():
    """The `pcraft.errors` row promises `PromptCraftError`'s `code` / `message` / `hint` shape.
    Those are attributes of the class, not module-level names, so the table-driven check above
    exempts them -- this is the assertion that exemption is paid for with. Nothing asserted the
    triple before, which meant the covered surface included a shape no test looked at."""
    err = PromptCraftError("INPUT_STABILITY_PROBE", "probe message", "probe hint")
    doc = STABILITY.read_text(encoding="utf-8")
    for attr in sorted(_ATTRIBUTES_OF_THE_ERROR_TYPE):
        assert hasattr(err, attr), f"PromptCraftError.{attr} is promised by STABILITY.md"
        assert f"`{attr}`" in doc, (
            f"{attr} is exempted from the table check here but STABILITY.md no longer names it"
        )
    assert (err.code, err.message, err.hint) == (
        "INPUT_STABILITY_PROBE", "probe message", "probe hint",
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
