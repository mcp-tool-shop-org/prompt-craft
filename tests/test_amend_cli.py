"""Regression tests for the wave-2 cli-surface amend (health-amend-a).

Written test-first: every test here was watched RED against the pre-fix code before the
corresponding fix landed in cli/__init__.py, errors.py, gate_report.py, sample.py, and
testing.py. Findings closed: F-fb4f116a (usage errors claiming a gate-failure exit code),
F-e829e81d (only PromptCraftError caught; compile had no handler at all), F-7dc5405a
(Zone.UNAVAILABLE excluded from gate_report's own flag filter), F-834dd470 (the demo mock
never actually executed Tier-0, so its own census line was already lying under a PASS),
plus the Director-requested `pcraft gate` / --generator-family same-family regression
(expected red in this worktree -- see its docstring below).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.contract.compile_questions import Polarity
from pcraft.core.contract.schema import Severity
from pcraft.core.gate.harness import AtomVerdict, GateTranscript
from pcraft.core.gate.thresholds import Zone
from pcraft.gate_report import format_transcript
from pcraft.sample import run_mock_loop

runner = CliRunner()


# --------------------------------------------------------------------------- F-fb4f116a
# Click/Typer's own parser errors (missing arg, bad option, unknown/missing command) must
# exit 1 ("bad user input"), never the library's built-in UsageError default of 2 -- this
# product's own errors.py already spends 2 on "ran, and a required atom failed".
#
# NOTE (wave-13, F-76b0940b): `gate`'s IMAGE argument became variadic when the batch door
# landed, so a bare `pcraft gate` is now refused by the command's OWN INPUT_GATE_TARGET
# rather than by Click's MissingParameter. The assertion below is unchanged and still the
# contract -- exit 1 either way -- and the Click path it was written for is still exercised
# by the other five rows, `["replay"]` most directly (a required, non-variadic argument).


@pytest.mark.parametrize(
    "argv",
    [
        ["gate"],  # missing IMAGE argument (the CLI's own refusal since wave-13)
        ["replay"],  # missing RECORD argument -- Click's MissingParameter
        ["synth", "--debug=notabool"],  # bad option value (--debug is a flag, takes none)
        ["frobnicate"],  # unknown command
        [],  # bare invocation -> Click's "Missing command."
        ["--nope"],  # unknown top-level option
    ],
    ids=["missing-image", "missing-record", "bad-option-value", "unknown-command", "bare", "unknown-option"],
)
def test_usage_errors_exit_1_not_2(argv):
    result = runner.invoke(app, argv)
    assert result.exit_code == 1, (
        f"pcraft {' '.join(argv)!r} exited {result.exit_code}, expected 1 -- "
        "Click's own UsageError default of 2 collides with this contract's GATE_/etc. exit 2"
    )


def test_missing_argument_message_still_explains_itself():
    """The remap must not go silent -- exit 1 with no explanation is its own defect."""
    result = runner.invoke(app, ["gate"])
    text = (result.stdout or "") + (result.stderr or "")
    assert "IMAGE" in text or "Missing argument" in text


def test_a_genuine_io_record_invalid_still_exits_2_not_1(tmp_path):
    """The other half: remapping Click's OWN usage-error 2 must not touch this
    product's deliberate PromptCraftError exit 2 (here: IO_RECORD_INVALID)."""
    path = tmp_path / "not-a-record.json"
    path.write_text('{"record_id": "only-one-field"}', encoding="utf-8")
    result = runner.invoke(app, ["replay", str(path)])
    assert result.exit_code == 2
    text = (result.stdout or "") + (result.stderr or "")
    assert "IO_RECORD_INVALID" in text


def test_help_still_exits_0():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_sync_rules_does_not_exec_a_cwd_planted_script(tmp_path, monkeypatch):
    """CLI-B-001: cwd-first search would exec a planted scripts/sync_rules_from_readouts.py."""
    planted = tmp_path / "scripts"
    planted.mkdir()
    planted.joinpath("sync_rules_from_readouts.py").write_text("raise SystemExit('planted')\n")
    monkeypatch.chdir(tmp_path)
    from pcraft.cli import _find_sync_script

    found = _find_sync_script()
    assert found is None or found.resolve() != (planted / "sync_rules_from_readouts.py").resolve()


def test_bind_honours_the_contract_flag(tmp_path):
    """CLI-W3-001: --contract used to be accepted and ignored; bind always resolved ashen-reaver."""
    result = runner.invoke(
        app, ["bind", "--contract", "char:does-not-exist", "--records-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code != 0
    assert "INPUT_UNKNOWN_CONTRACT" in text or "char:does-not-exist" in text
    assert "BOUND" not in text


def test_demo_announces_that_scores_did_not_read_pixels():
    """CLI-C-001: BOUND used to look like a real gate pass."""
    result = runner.invoke(app, ["demo"])
    text = (result.stdout or "") + (result.stderr or "")
    assert "mock:" in text
    assert "pixels were not read" in text


def test_synth_success_path_still_exits_0():
    result = runner.invoke(app, ["synth"])
    assert result.exit_code == 0


# --------------------------------------------------------------------------- F-e829e81d
# Every command must route an unexpected (non-PromptCraftError) exception through the
# structured error shape -- classified, not a raw traceback -- and `compile` (previously
# with NO try/except at all) must do the same.


def test_demo_with_a_records_dir_that_is_a_file_does_not_dump_a_traceback(tmp_path):
    blocker = tmp_path / "im-a-file-not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["demo", "--records-dir", str(blocker)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "Traceback" not in text
    assert "pydantic" not in text.lower()
    assert "RUNTIME_" in text
    # Exit 4, not 2. The generator raised on every attempt, so NOTHING was scored --
    # could-not-run, which the four-way contract keeps distinct from "it ran and a
    # required atom failed". This assertion said 2 while the command was still exiting
    # 0 (the escalated decision was a returned result, never a raised error), so the
    # number was never actually measured against a working exit path.
    assert result.exit_code == 4


def test_bind_with_a_records_dir_that_is_a_file_does_not_dump_a_traceback(tmp_path):
    blocker = tmp_path / "im-a-file-not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["bind", "--records-dir", str(blocker)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "Traceback" not in text
    assert "RUNTIME_" in text
    assert result.exit_code == 4  # could-not-run, not a failed atom (see the demo sibling)


def test_compile_seed_wraps_an_unexpected_exception_instead_of_a_raw_traceback(monkeypatch):
    """`compile` (cli/__init__.py:134-153 pre-fix) had zero exception handling of any
    kind. Monkeypatch the heavy artifact writer so this stays hermetic (no real write
    into the shipped compiled/ tree) while still exercising the new try/except."""
    import pcraft.core.optimize.compile as compile_mod

    def _boom(*_a, **_kw):
        raise ValueError("synthetic failure for the amend regression test")

    monkeypatch.setattr(compile_mod, "write_seed_artifact", _boom)
    result = runner.invoke(app, ["compile", "--seed"])
    text = (result.stdout or "") + (result.stderr or "")
    assert "Traceback" not in text
    assert "RUNTIME_" in text
    assert result.exit_code == 2


def test_a_promptcrafterror_raised_deep_inside_a_command_is_unaffected_by_the_backstop(tmp_path):
    """The new blanket `except Exception` must sit AFTER `except PromptCraftError`, not
    swallow it -- a structured error must still surface under its OWN code."""
    result = runner.invoke(app, ["gate", str(tmp_path / "does-not-exist.png")])
    assert result.exit_code == 4  # IO_GATE_INPUT: missing path is a refuse, not a failed atom
    text = (result.stdout or "") + (result.stderr or "")
    assert "IO_GATE_INPUT" in text
    assert "RUNTIME_" not in text


# --------------------------------------------------------------------------- F-7dc5405a
# format_transcript's own "flag this" filter must include Zone.UNAVAILABLE, per its
# module docstring ("PARTIAL / FAIL / UNAVAILABLE must not read as a wall of green
# PASSes... Unconfirmed and failed atoms print first").


def _mk_verdict(atom_id: str, zone: Zone) -> AtomVerdict:
    return AtomVerdict(
        atom_id=atom_id,
        polarity=Polarity.affirm,
        severity=Severity.required,
        score=None,
        zone=zone,
        tier_used=None,
        verifier_id=None,
        reason="synthetic verdict for the amend regression test",
    )


def test_format_transcript_flags_unavailable_when_mixed_with_a_pass():
    t = GateTranscript(
        contract_id="test:contract",
        overall=Zone.UNCERTAIN,
        verdicts=[_mk_verdict("scored_ok", Zone.PASS), _mk_verdict("never_scored", Zone.UNAVAILABLE)],
    )
    out = format_transcript(t)
    lines = out.splitlines()
    assert "unconfirmed / failed:" in lines
    header_idx = lines.index("unconfirmed / failed:")
    unavailable_idx = next(i for i, ln in enumerate(lines) if "never_scored" in ln)
    assert unavailable_idx > header_idx, (
        "an UNAVAILABLE atom must print under the flagged header, not silently among passes"
    )


def test_format_transcript_flags_unavailable_even_when_it_is_the_only_zone_present():
    """The fall-through defect: with no FAIL/UNCERTAIN/SKIPPED/NA present, `problem` was
    empty (UNAVAILABLE excluded), so `if problem and ...` was False and the whole
    function fell to the undifferentiated `else` branch -- no 'unconfirmed / failed:'
    header printed at all. That is exactly the 'wall of green' pattern the module
    docstring says must not happen, just with UNAVAILABLE standing in for PASS."""
    t = GateTranscript(
        contract_id="test:contract",
        overall=Zone.UNAVAILABLE,
        verdicts=[_mk_verdict("never_scored", Zone.UNAVAILABLE)],
    )
    out = format_transcript(t)
    assert "unconfirmed / failed:" in out


# --------------------------------------------------------------------------- F-834dd470
# The mock scenario behind `demo`/`bind --mock` must actually register a Tier-0 verifier,
# not rely on `_pick`'s tier-1 fallback -- otherwise the census undercounts a gate that
# in fact ran to completion, but a truly half-run gate would look identical to a clean one.


def test_demo_mock_actually_executes_both_required_tiers(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    assert res.decision == "bound"
    census = res.record.gate_transcript.tier_census
    assert census.required == [0, 1]
    assert census.executed == [0, 1], (
        "the default mock must register a Tier-0 verifier so the census counts what "
        "actually ran, not what fell forward to Tier-1"
    )
    assert census.n == census.m == 2


def test_demo_cli_output_shows_the_gate_fully_executed(tmp_path):
    result = runner.invoke(app, ["demo", "--records-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "tiers executed: 2 of 2" in result.stdout


# --------------------------------------------------------------------------- gate / generator-family
# Director-requested: `pcraft gate` must pass the generator family to the harness so the
# same-family guard can fire from the CLI path too (today it only fires inside
# orchestrate.run, which `pcraft gate` never goes through). `--generator-family` lets a
# test force the collision without needing real GPU verifiers.
#
# EXPECTED RED IN THIS WORKTREE. The new harness.evaluate(..., *, generator_family: str)
# keyword lands in a SIBLING worktree (gate-harness domain), not this one -- here,
# harness.evaluate still has the pre-fold signature and does not accept the kwarg, so
# this call raises TypeError, which this domain's OWN fix #2 (the blanket except) wraps
# into RUNTIME_UNEXPECTED instead of GATE_SAME_FAMILY. Same exit code (2) either way,
# by coincidence of errors.py's prefix table, so the assertion below checks the ERROR
# CODE STRING, not just the exit code, to actually catch that difference. This test
# should go green on its own once this worktree folds with the sibling's harness change
# -- do not weaken, skip, or xfail it to force green locally.


def test_gate_refuses_a_same_family_verifier(tmp_path):
    image = tmp_path / "fake.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")  # preflight only checks readability, not contents
    result = runner.invoke(app, ["gate", str(image), "--generator-family", "siglip2"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2
    assert "GATE_SAME_FAMILY" in text, (
        f"expected the same-family guard to refuse; got: {text!r}. "
        "If this fails with RUNTIME_UNEXPECTED / 'unexpected keyword argument "
        "generator_family', that's the documented expected-red-until-fold state -- "
        "the sibling gate-harness worktree has not landed the new harness.evaluate "
        "signature yet. Do not weaken this assertion to make it pass early."
    )


def test_gate_default_generator_family_comes_from_the_registered_plugin(tmp_path):
    """No --generator-family override: the CLI must derive it from
    get('image').generator().family ('stable-diffusion'), which does not collide with
    any of the shipped image-domain verifier families (siglip2/clip-flant5/dsg-qg), so
    this specific call should never raise GATE_SAME_FAMILY. Also expected red in this
    worktree for the same reason as above (TypeError on the not-yet-folded kwarg) --
    included so the fold's proof isn't only the collision case.
    """
    image = tmp_path / "fake.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = runner.invoke(app, ["gate", str(image)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "GATE_SAME_FAMILY" not in text
    assert "RUNTIME_UNEXPECTED" not in text, (
        f"expected the default generator-family plumbing to reach harness.evaluate "
        f"cleanly; got: {text!r}. Expected-red-until-fold (see test above)."
    )


# --------------------------------------------------------------------------- F-fd21bd37
# Non-ASCII in a --help string crashes the CLI on a cp437 console (the classic Windows
# OEM codepage): Click/Typer renders help OUTSIDE every command body's try/except, so the
# UnicodeEncodeError escapes as a raw traceback and exit 1 -- this contract's own code for
# "bad user input" -- while --debug, which the module docstring says gates raw tracebacks,
# changes nothing. The em-dash in `compile`'s docstring also rendered inside the ROOT
# `pcraft --help` listing, so a single character took the whole front door down.
#
# The assertion is a REAL subprocess with stdio pinned to cp437:strict -- the honest
# simulation of the classic Windows OEM console. The first form of this test rendered
# in-process and then encode()d the captured page, which asserted an ENVIRONMENT property
# instead of the repo's: Rich picks its panel glyphs from the attached terminal, drew
# rounded corners (U+256D -- not in cp437) on the Linux CI runner and square ones (which
# cp437 has) on every Windows box this was written on, so the test failed CI over glyphs
# this repo does not author. With the child's encoding pinned, Rich adapts exactly as it
# does on a real cp437 console, and a non-encodable character in OUR strings still dies
# as an unhandled UnicodeEncodeError with exit 1, outside every --debug gate.
# The source-declared strings are checked for pure ASCII separately, below.


def _help_argvs() -> list[list[str]]:
    group = typer.main.get_command(app)
    return [["--help"], *[[name, "--help"] for name in sorted(group.commands)]]


@pytest.mark.parametrize("argv", _help_argvs(), ids=lambda a: "-".join(a).replace("--", ""))
def test_every_rendered_help_page_encodes_on_a_cp437_console(argv):
    env = {**os.environ, "PYTHONIOENCODING": "cp437:strict", "PYTHONUTF8": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "pcraft", *argv],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,  # the return code IS the assertion below
    )
    assert proc.returncode == 0, (
        f"pcraft {' '.join(argv)} died on a cp437-pinned console: "
        f"{proc.stderr.decode('cp437', 'replace')[-400:]}"
    )


def _declared_help_strings() -> list[tuple[str, str]]:
    group = typer.main.get_command(app)
    out: list[tuple[str, str]] = [("pcraft (help)", group.help or "")]
    out += [(f"pcraft --{p.name}", getattr(p, "help", None) or "") for p in group.params]
    for name, sub in sorted(group.commands.items()):
        out.append((f"{name} (help)", sub.help or ""))
        out.append((f"{name} (short_help)", getattr(sub, "short_help", None) or ""))
        out += [(f"{name} --{p.name}", getattr(p, "help", None) or "") for p in sub.params]
    return out


def test_declared_help_and_docstrings_are_pure_ascii():
    """The source half of the same guard, independent of how Rich frames the page.

    Checks what this repo WROTE (command docstrings Typer renders as help, plus every
    option's help=) rather than what the renderer produced, so the class cannot come back
    through a string that happens not to be reachable on the terminal width of the day.
    """
    offenders = [
        (where, text) for where, text in _declared_help_strings() if not text.isascii()
    ]
    assert not offenders, "non-ASCII in help text the CLI renders: " + "; ".join(
        f"{where}: " + " ".join(f"U+{ord(c):04X}" for c in text if not c.isascii())
        for where, text in offenders
    )


# --------------------------------------------------------------------------- F-62bb6e8d
# bind --no-mock's live door and `doctor`'s [image] report were two different answers to
# "is the [image] extra installed": the door checked torch/diffusers/PIL, doctor checked
# those plus transformers, and pyproject's extra actually declares six distributions. An
# env missing only transformers therefore passed the door and crashed deep inside the
# VQA-family verifiers, downgrading an actionable DEP_IMAGE_MISSING refusal to the generic
# RUNTIME_UNEXPECTED backstop. Both codes exit 2, so the exit contract hid the difference.


def _find_spec_with(monkeypatch, absent: set[str], present: set[str]):
    """Force a specific [image] install shape without touching the real environment."""
    real = importlib.util.find_spec

    def fake(name, package=None):
        if name in absent:
            return None
        if name in present:
            return object()
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake)


def test_live_door_refuses_when_only_transformers_is_missing(monkeypatch, tmp_path):
    from pcraft.sample import IMAGE_EXTRA_MODULES

    _find_spec_with(
        monkeypatch,
        absent={"transformers"},
        present=set(IMAGE_EXTRA_MODULES) - {"transformers"},
    )
    result = runner.invoke(app, ["bind", "--no-mock", "--records-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "DEP_IMAGE_MISSING" in text, (
        f"a torch+diffusers+PIL env with no transformers walked past the live door; got {text!r}"
    )
    assert "RUNTIME_UNEXPECTED" not in text
    assert "Traceback" not in text
    assert result.exit_code == 2


def test_live_door_lets_a_complete_image_extra_through(monkeypatch, tmp_path):
    """The other half: the stricter door must not refuse a fully installed extra."""
    from pcraft.sample import IMAGE_EXTRA_MODULES, image_extra_present

    _find_spec_with(monkeypatch, absent=set(), present=set(IMAGE_EXTRA_MODULES))
    assert image_extra_present() is True


def test_doctor_and_the_live_door_check_the_same_module_list():
    """One list, two call sites -- the drift is what made the door the weaker check."""
    import json

    from pcraft.sample import IMAGE_EXTRA_MODULES

    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    image = next(e for e in data["extras"] if e["name"] == "image")
    assert set(image["modules"]) == set(IMAGE_EXTRA_MODULES), (
        "doctor's [image] report and bind --no-mock's door must read the same list"
    )


# --------------------------------------------------------------------------- F-4d031e47
# package_version() returns installed dist metadata and only falls back to the tree's
# declared version when NOTHING is installed. A stale editable dist-info (reproduced live
# in this checkout: metadata 0.2.1 against a 1.0.0 tree) is therefore reported as fact --
# silently wrong by a major version, with the only existing guard buried in the
# maintainer-only `verify.py --installed` leg. doctor already has a report shape; the
# coherence check belongs there, and on --version's stderr.


def _stale_metadata(monkeypatch, installed: str):
    import pcraft

    monkeypatch.setattr(pcraft, "version", lambda _name: installed)


def test_doctor_reports_a_stale_installed_version_loudly(monkeypatch):
    import json

    import pcraft

    _stale_metadata(monkeypatch, "0.2.1")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["version"] == "0.2.1"
    assert data["version_coherent"] is False, (
        "doctor read stale 0.2.1 metadata against a "
        f"{pcraft._FALLBACK_VERSION} tree and called it coherent"
    )
    assert pcraft._FALLBACK_VERSION in (data["version_warning"] or "")
    banner = (result.stderr or "") + (result.stdout or "")
    assert "0.2.1" in banner and pcraft._FALLBACK_VERSION in banner


def test_doctor_is_quiet_when_the_installed_version_matches_the_tree(monkeypatch):
    import json

    import pcraft

    _stale_metadata(monkeypatch, pcraft._FALLBACK_VERSION)
    result = runner.invoke(app, ["doctor", "--json"])
    data = json.loads(result.stdout)
    assert data["version_coherent"] is True
    assert data["version_warning"] is None


def test_version_flag_warns_on_stderr_and_keeps_stdout_a_bare_version(monkeypatch):
    """--version's stdout shape is covered by STABILITY.md, so the warning goes to stderr."""
    import pcraft

    _stale_metadata(monkeypatch, "0.2.1")
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert (result.stdout or "").strip() == "pcraft 0.2.1"
    assert pcraft._FALLBACK_VERSION in (result.stderr or ""), (
        "a stale dist-info must say so somewhere; stdout stays the bare version line"
    )


# --------------------------------------------------------------------------- F-dc0ca73f
# sync-rules was the one command body with no try/except PromptCraftError wrap: the
# dynamic load (_find_sync_script / spec_from_file_location / exec_module) and any
# PromptCraftError out of module.generate() bypassed this module's documented error
# contract entirely and produced a raw traceback with Python's default exit code.


def _plant_sync_script(monkeypatch, tmp_path, body: str) -> None:
    import pcraft.cli as cli_mod

    script = tmp_path / "sync_rules_from_readouts.py"
    script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cli_mod, "_find_sync_script", lambda: script)


def test_sync_rules_wraps_a_promptcrafterror_from_the_loaded_script(monkeypatch, tmp_path):
    _plant_sync_script(
        monkeypatch,
        tmp_path,
        "from pcraft.errors import PromptCraftError\n"
        "DEFAULT_OUT = 'out.md'\n"
        "DEFAULT_DB = 'recipes.db'\n"
        "def generate(db, out):\n"
        "    raise PromptCraftError('IO_SYNC_DB', 'synthetic sync failure for the amend test')\n",
    )
    result = runner.invoke(app, ["sync-rules"])
    text = (result.stdout or "") + (result.stderr or "")
    assert "Traceback" not in text, f"sync-rules leaked a raw traceback: {text!r}"
    assert "error[IO_SYNC_DB]" in text
    assert result.exit_code == 2


def test_sync_rules_wraps_interface_drift_in_the_loaded_script(monkeypatch, tmp_path):
    """The loaded script's interface drifting (no DEFAULT_OUT / no generate) is an
    internal defect, so it must arrive as RUNTIME_UNEXPECTED / exit 2 -- not as a bare
    AttributeError traceback exiting 1, which is this contract's 'user error' band."""
    _plant_sync_script(monkeypatch, tmp_path, "SOMETHING_ELSE = 1\n")
    result = runner.invoke(app, ["sync-rules"])
    text = (result.stdout or "") + (result.stderr or "")
    assert "Traceback" not in text, f"sync-rules leaked a raw traceback: {text!r}"
    assert "RUNTIME_UNEXPECTED" in text
    assert result.exit_code == 2


# --------------------------------------------------------------------------- F-df34f27e
# Ctrl-C exits 130, and that is DELIBERATE -- not an oversight in the 0/1/2/3/4 table.
#
# What the machinery actually does (typer 0.26.7, core.py:197-198): a KeyboardInterrupt
# raised anywhere inside `self.invoke(ctx)` is caught by typer itself and re-raised as
# `_click.exceptions.Exit(130)`, never as Abort. `_ExitContractGroup.main` forces
# `standalone_mode=False` on the inner call, so that Exit hits core.py's outer handler,
# which returns the int 130 instead of raising -- meaning `super().main(...)` RETURNS
# 130 with no exception at all. Neither `except _ClickException` nor `except _ClickAbort`
# ever fires; control falls through to the final `sys.exit(rv)`.
#
# 130 is 128 + SIGINT, the universal shell convention for "the operator interrupted this."
# Remapping it into the 0/1/2/3/4 band would DESTROY information a scripted caller relies
# on: exit 1 already means "bad user input", and a wrapper that retries on 1 but bails on
# an interrupt could no longer tell the two apart. So the number is pinned here rather
# than normalised, and named as a documented exception in STABILITY.md.
#
# These two tests are the reason the `except _ClickAbort:` clause STAYS despite being
# unreachable for Ctrl-C: the second one proves the branch is live for the paths that do
# raise Abort (typer core.py:194-196 converts a bare EOFError into one, and core.py's
# `except Abort: if not standalone_mode: raise` hands it straight to us). Deleting the
# clause as "dead" would turn an Abort into an uncaught RuntimeError subclass -- a raw
# traceback, exiting 1, which is strictly worse than the banner it prints today.


def _scratch_group_app() -> typer.Typer:
    """A throwaway Typer app built on the REAL, imported ``_ExitContractGroup``.

    The override under test lives in ``main()``, which ``CliRunner`` reaches but cannot
    drive into an interrupt: no shipped command body raises KeyboardInterrupt or EOFError
    on demand. A scratch app on the same class exercises the identical code path with a
    body we control.

    The ``@scratch.callback()`` is load-bearing, not decoration: Typer folds a
    single-command app into a bare ``Command`` and never consults ``cls=`` at all, so
    without it this harness silently measures stock Click instead of the override. The
    ``isinstance`` guard in ``_run_scratch`` is the standing check on that.
    """
    from pcraft.cli import _ExitContractGroup

    scratch = typer.Typer(cls=_ExitContractGroup, add_completion=False)

    @scratch.callback()
    def _scratch_root() -> None:
        """scratch root"""

    return scratch


def _run_scratch(scratch: typer.Typer, argv: list[str]) -> int | str | None:
    """Invoke the way the installed console script does, and return the exit code.

    ``typer.Typer.__call__`` is ``get_command(self)(*args)`` -> ``BaseCommand.__call__``
    -> ``self.main(...)`` with ``standalone_mode`` defaulting True at the outer layer.
    This calls that same ``main`` directly, skipping only ``__call__``'s assignment to
    ``sys.excepthook`` -- a process-global mutation that has nothing to do with the exit
    contract and should not leak out of a test.
    """
    from pcraft.cli import _ExitContractGroup

    command = typer.main.get_command(scratch)
    assert isinstance(command, _ExitContractGroup), (
        f"the scratch app collapsed to {type(command).__name__}, so cls=_ExitContractGroup "
        "was never consulted and this test would be measuring stock Click"
    )
    with pytest.raises(SystemExit) as excinfo:
        command.main(args=argv, prog_name="pcraft-scratch", standalone_mode=True)
    return excinfo.value.code


def test_an_interrupted_run_exits_130_outside_the_documented_code_table(capsys):
    """Ctrl-C during a long bind/gate run. 130 is the contract, and it is intentional."""
    scratch = _scratch_group_app()

    @scratch.command(name="longrun")
    def _longrun() -> None:
        """stands in for the bind/gate run the operator interrupts"""
        raise KeyboardInterrupt

    code = _run_scratch(scratch, ["longrun"])
    captured = capsys.readouterr()
    assert code == 130, (
        f"an interrupted run exited {code!r}, expected 130 (128 + SIGINT). Folding the "
        "interrupt into the 0/1/2/3/4 band collides with exit 1 (bad user input) and "
        "leaves a scripted caller no way to tell a typo from a Ctrl-C"
    )
    assert "Aborted!" not in captured.err, (
        "the interrupt path never reaches the Abort branch -- if this banner appears, the "
        "flow changed and the 130 above is no longer the pass-through this test pins"
    )


def test_the_abort_branch_is_live_for_the_paths_that_really_do_raise_abort(capsys):
    """Why ``except _ClickAbort:`` is kept even though Ctrl-C bypasses it.

    typer core.py:194-196 converts a bare EOFError raised anywhere inside ``invoke`` into
    ``Abort()``, and its outer ``except Abort: if not standalone_mode: raise`` hands that
    straight to ``_ExitContractGroup.main``. Abort subclasses RuntimeError, so nothing
    else in this module would catch it: remove the clause and this becomes a raw
    traceback exiting 1 instead of a one-line banner exiting 1.
    """
    scratch = _scratch_group_app()

    @scratch.command(name="eof")
    def _eof() -> None:
        """stands in for a read that hits a closed stdin"""
        raise EOFError

    code = _run_scratch(scratch, ["eof"])
    captured = capsys.readouterr()
    assert code == 1, f"an aborted run exited {code!r}, expected 1"
    assert "Aborted!" in captured.err, (
        "the Abort branch did not fire; if `except _ClickAbort:` were deleted as dead "
        "code this path would escape as an uncaught RuntimeError subclass"
    )


# --------------------------------------------------------------------------- F-f31c4b10
# The private-typer import in cli/__init__.py has broken twice, each time at IMPORT, before
# any command runs: ModuleNotFoundError on <0.26, then an uncaught ImportError on 0.27 from
# a module that still exists (which `except ModuleNotFoundError` cannot see). Both times the
# only thing that caught it was CI's ambient mypy leg resolving a non-blessed typer -- an
# environment property nothing in this repo asserts. afb391c moved Abort to the public
# `typer.Abort` and measured the identity by hand; these two tests make that measurement a
# standing assertion instead of a note in a commit message.


def test_the_public_abort_name_is_what_the_cli_imports():
    """The literal claim afb391c measured by hand, now run on every suite."""
    from pcraft.cli import _ClickAbort

    assert typer.Abort is _ClickAbort, (
        "cli/__init__.py's _ClickAbort has drifted off the public typer.Abort; on a layout "
        "where the vendored and public classes differ, the handler would catch a class the "
        "machinery never raises"
    )


def test_abort_is_a_runtimeerror_not_a_clickexception():
    """The structural half, and the one that is not a tautology.

    ``_ExitContractGroup``'s own docstring rests on this: it claims typer.Exit/typer.Abort
    "subclass RuntimeError, not Click's ClickException, so they are a structurally
    different type and this override can never intercept one." If Abort ever became a
    ClickException subclass, the `except _ClickException` clause above it would swallow
    every abort into the INPUT_-class exit-1 path and the Abort branch would go dead for
    real -- silently, since both branches exit 1.
    """
    from pcraft.cli import _ClickAbort, _ClickException

    assert issubclass(_ClickAbort, RuntimeError)
    assert not issubclass(_ClickAbort, _ClickException), (
        "Abort became a ClickException subclass; the clause ordering in "
        "_ExitContractGroup.main is no longer sound"
    )


# --------------------------------------------------------------------------- F-08baabcc
# The `except ModuleNotFoundError` fallback under the private-typer import is DEAD on every
# typer CI resolves today (measured: 0.27.2 on both legs, where `typer._click.exceptions`
# resolves and the try succeeds). It executes locally only by the accident of a venv holding
# a stale typer<0.26 -- an install-history artifact, not an assertion. A `pip install -e
# ".[dev]"` in that venv would flip local coverage to the untested branch too, with nothing
# red anywhere. The branch exists because this exact shape (a typer/click layout change
# breaking the CLI at IMPORT, before any command runs) has already happened twice.
#
# So the branch is forced rather than waited for, using this repo's own established
# convention -- `sys.modules[name] = None`, the same trick tests/test_feat_palette.py's
# _hide_pillow uses for Pillow -- which makes `import typer._click.exceptions` raise
# ModuleNotFoundError on a layout that has it. A real pinned-old-typer CI leg would prove
# more, but it costs a permanent matrix slot for a two-version shim; this costs nothing.
#
# The fresh module is exec'd from its own spec and never installed into sys.modules: a
# reload would leave `pcraft.cli._ClickException` bound to the fallback class for every
# later test in the session, which on a >=0.26 layout is a DIFFERENT class from the one the
# machinery raises. submodule_search_locations is load-bearing -- without it the spec's
# parent is "pcraft" instead of "pcraft.cli" and every `from ..` in the module dies as
# "attempted relative import beyond top-level package".


@pytest.mark.skipif(
    importlib.util.find_spec("click") is None,
    reason="typer >= 0.27 ships no standalone click, so the pre-0.26 fallback cannot bind there",
)
def test_the_pre_026_click_exception_fallback_still_binds_when_forced(monkeypatch):
    import click.exceptions

    import pcraft.cli as cli_mod

    monkeypatch.setitem(sys.modules, "typer._click", None)
    monkeypatch.setitem(sys.modules, "typer._click.exceptions", None)

    source = Path(cli_mod.__file__)
    spec = importlib.util.spec_from_file_location(
        "pcraft.cli", source, submodule_search_locations=[str(source.parent)]
    )
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)

    assert fresh._ClickException is click.exceptions.ClickException, (
        "the typer<0.26 fallback did not bind click.exceptions.ClickException; on that "
        "layout the CLI would fail at import, before any command runs"
    )
    assert fresh._ClickAbort is typer.Abort, (
        "Abort must come from the public name on every layout -- that is the whole point of "
        "it not being in the two-branch import"
    )


# --------------------------------------------------------------------------- F-90a9872f
# `_say` writes through whatever encoding the interpreter derived from the locale/console
# codepage, with errors='strict' -- this CLI never reconfigured it. So a --contracts-dir
# path containing perfectly ordinary non-English characters broke `--json` two different
# ways, both MEASURED against a real subprocess before the fix:
#
#   1. SILENT. A path representable in the ambient codepage but not ASCII (cp1252 on the rig
#      this was written on) exits 0 with a complete-looking document on stdout whose bytes
#      are NOT valid UTF-8 ("'utf-8' codec can't decode byte 0xdc"). A caller doing the
#      ordinary json.loads(stdout.decode('utf-8')) gets a decode error from a command that
#      reported success.
#   2. LOUD BUT MISCLASSIFIED. A path outside the codepage entirely raises UnicodeEncodeError
#      inside _say, caught only by the outer `except Exception` backstop -- exit 2,
#      RUNTIME_UNEXPECTED, stdout completely empty (0 bytes), even though the contract was
#      found and would have listed fine. A purely representational failure read by the
#      exit-code contract as a runtime error.
#
# This is the same defect CLASS the file already fixed four times for its OWN static strings
# (F-fd21bd37, F-a6acaab1, F-df1c6b0a, F-de08ba2e), surviving on the one vector an ASCII
# sweep of the source structurally cannot reach: user-supplied path content.
#
# The cp437-pinned leg is deliberate and is NOT redundant with the ambient one. An explicit
# PYTHONIOENCODING is an operator override and keeps winning -- the help-page tests above
# depend on exactly that -- so on that leg the fix may not simply reconfigure the stream to
# UTF-8. It has to hold anyway, which is what pins the two halves of the fix that survive an
# override: the human banner degrades readably instead of raising, and the --json document
# is escaped to pure ASCII, so it parses out of any console codepage at all.

_LATIN1_STORE = "store-\u00dc\u00ef\u00f8\u00e9"  # cp1252 has all four; cp437 does not have o-slash
_OUTSIDE_STORE = "store-\u6f22\u5b57"  # in neither legacy codepage


def _non_ascii_store(tmp_path, name: str) -> Path:
    from pcraft.domains.image.subdomains.sprite import CONTRACTS_DIR

    dest = tmp_path / name
    shutil.copytree(CONTRACTS_DIR, dest)
    return dest


def _list_json_under(store: Path, *, pythonioencoding: str | None):
    """Run the real CLI in a subprocess with the console codepage pinned like an operator's.

    A subprocess, not CliRunner: the defect lives in the encoding the INTERPRETER picks for
    its own stdout, which CliRunner replaces with a UTF-8 buffer of its own and therefore
    cannot see.
    """
    env = {**os.environ, "PYTHONUTF8": "0"}
    env.pop("PYTHONIOENCODING", None)
    if pythonioencoding is not None:
        env["PYTHONIOENCODING"] = pythonioencoding
    return subprocess.run(
        [sys.executable, "-m", "pcraft", "list", "--contracts-dir", str(store), "--json"],
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    "pythonioencoding", [None, "cp437:strict"], ids=["ambient-console", "cp437-pinned"]
)
@pytest.mark.parametrize(
    "dirname", [_LATIN1_STORE, _OUTSIDE_STORE], ids=["in-legacy-codepage", "outside-codepage"]
)
def test_json_stdout_parses_whatever_codepage_the_console_reports(tmp_path, dirname, pythonioencoding):
    store = _non_ascii_store(tmp_path, dirname)
    proc = _list_json_under(store, pythonioencoding=pythonioencoding)
    tail = proc.stderr.decode("utf-8", "backslashreplace")[-400:]
    assert proc.returncode == 0, (
        f"`pcraft list --json` under a non-ASCII --contracts-dir exited {proc.returncode}; "
        "the contract was found and only its NAME could not be represented, so this is not "
        f"a runtime error: {tail}"
    )
    try:
        text = proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionError(
            "`--json` wrote a document that is not valid UTF-8, on a command that exited 0 "
            f"-- an ordinary json.loads(stdout.decode('utf-8')) caller sees: {exc}"
        ) from None
    doc = json.loads(text)
    sources = [c["source"] for c in doc["contracts"]]
    assert sources, "the store listed no contracts"
    assert all(dirname in s for s in sources), (
        f"the --json document lost the directory name it was given: {sources!r}"
    )


@pytest.mark.parametrize(
    "pythonioencoding", [None, "cp437:strict"], ids=["ambient-console", "cp437-pinned"]
)
def test_the_human_banner_degrades_readably_instead_of_taking_the_command_down(tmp_path, pythonioencoding):
    """The other half: stderr must still say something, and say it without raising.

    Under `--json` the banner is the only human-readable output there is. Losing it to a
    UnicodeEncodeError takes stdout with it (measured: 0 bytes), so "the banner survives" is
    what keeps the document from being collateral damage on a legacy console.
    """
    store = _non_ascii_store(tmp_path, _OUTSIDE_STORE)
    proc = _list_json_under(store, pythonioencoding=pythonioencoding)
    banner = proc.stderr.decode("utf-8", "backslashreplace")
    assert "char:ashen-reaver" in banner, (
        f"the --json banner did not survive an unrepresentable path: {banner[-400:]!r}"
    )
    assert "RUNTIME_UNEXPECTED" not in banner, (
        "a path that cannot be printed is not an unclassified runtime failure"
    )


# --------------------------------------------------------------------------- F-b795e5ca
# `--image-name local=cloud` split on the FIRST '=', so a local plate filename containing an
# '=' (a legal Windows/POSIX filename character) silently folded its own tail into the CLOUD
# name: measured, _parse_image_names(['weird=name.png=cloud-upload.png']) returned
# {'weird': 'name.png=cloud-upload.png'} with no refusal. `recipe` writes the graph that gets
# uploaded and submitted to Comfy Cloud at real spend, and bind_cloud_names' documented
# behaviour for a key it does not recognise is "missing keys stay" -- so a wrong split is
# invisible all the way to the money.
#
# The split moves to the LAST '=', not to a refusal: the local side is a free-form plate
# filename (kontext_fill builds it from Path(lock.identity[0]).name -- arbitrary user
# content), while the cloud side is a Comfy upload name, which cannot contain '='. Refusing
# would leave an operator whose plate legitimately contains an '=' with no way to use the
# flag at all. Both directions are pinned below so the choice is a decision, not a guess.


def test_image_name_splits_on_the_last_equals_so_a_local_plate_may_contain_one():
    from pcraft.cli import _parse_image_names

    names = _parse_image_names(["weird=name.png=cloud-upload.png"])
    assert names == {"weird=name.png": "cloud-upload.png"}, (
        "the extra '=' belongs to the local filename; folding it into the cloud name "
        "produces an upload name Comfy never issued"
    )
    assert "weird" not in names, "the first-'=' split is back"


def test_image_name_leaves_an_ordinary_pair_exactly_as_it_was():
    from pcraft.cli import _parse_image_names

    assert _parse_image_names(["ashen-reaver-front.png=cloud-face.png"]) == {
        "ashen-reaver-front.png": "cloud-face.png"
    }


@pytest.mark.parametrize("raw", ["=cloud.png", "local.png=", "="], ids=["no-local", "no-cloud", "bare"])
def test_image_name_still_refuses_an_empty_side(raw):
    from pcraft.cli import _parse_image_names
    from pcraft.errors import PromptCraftError

    with pytest.raises(PromptCraftError) as excinfo:
        _parse_image_names([raw])
    assert excinfo.value.code == "INPUT_IMAGE_NAME"


def test_image_name_still_refuses_a_pair_with_no_equals():
    from pcraft.cli import _parse_image_names
    from pcraft.errors import PromptCraftError

    with pytest.raises(PromptCraftError) as excinfo:
        _parse_image_names(["ashen-reaver-front.png"])
    assert excinfo.value.code == "INPUT_IMAGE_NAME"


# --------------------------------------------------------------------------- F-5b655328
# doctor reported `python` as a bare version string ('3.14.5') and never sys.executable. On a
# machine with more than one interpreter satisfying the same floor -- pyenv, conda, a project
# venv beside a global install, or the npm launcher's own PCRAFT_PYTHON candidate list -- the
# version number alone cannot say WHICH one answered. doctor is the one command whose entire
# job is answering that for an operator debugging a confusing environment.


def test_doctor_names_the_interpreter_it_actually_ran_under():
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["executable"] == sys.executable, (
        "doctor's report does not name the interpreter that produced it, so a version "
        "number is the only clue about which of several Pythons answered"
    )
    assert sys.executable in ((result.stderr or "") + (result.stdout or "")), (
        "the human banner must name it too; --json is not the only way people run doctor"
    )


def test_doctor_shows_the_configured_pcraft_python_beside_the_one_that_answered(monkeypatch):
    """'What I configured' next to 'what is actually running' is the whole diagnosis.

    This is the companion half of the npm launcher finding: once a broken PCRAFT_PYTHON has
    been rejected, `pcraft doctor` is the natural next step, and it has to be able to show
    the mismatch rather than report a version and leave the operator guessing.
    """
    monkeypatch.setenv("PCRAFT_PYTHON", "C:/definitely/not/a/real/path/python.exe")
    result = runner.invoke(app, ["doctor", "--json"])
    data = json.loads(result.stdout)
    assert data["pcraft_python"] == "C:/definitely/not/a/real/path/python.exe"
    assert data["executable"] == sys.executable


def test_doctor_reports_no_configured_interpreter_when_the_env_var_is_unset(monkeypatch):
    monkeypatch.delenv("PCRAFT_PYTHON", raising=False)
    result = runner.invoke(app, ["doctor", "--json"])
    data = json.loads(result.stdout)
    assert data["pcraft_python"] is None


# --------------------------------------------------------------------------- F-d7c0c054 / F-32b0166f
# The npm launcher. Two findings, one file.
#
# F-d7c0c054: locate() tried PCRAFT_PYTHON first, then took the SAME silent `continue` for
# every reason it could fail -- not on PATH, real interpreter without the toolkit, wrong
# permissions -- and quietly fell through to the next PATH candidate. MEASURED end to end:
# `PCRAFT_PYTHON=C:/definitely/not/a/real/path/python.exe node npm/bin/pcraft.mjs --version`
# exited 0 and printed an ordinary version banner, with nothing anywhere saying the
# configured interpreter had been rejected or that a different one answered. The population
# npm/README.md aims that variable at ("if you keep several") is exactly the population most
# likely to have another pcraft on PATH to absorb the mistake -- a different version, with
# different pins, quite possibly not the code the operator meant to exercise. `bind --no-mock`
# spends real GPU/Cloud money on that assumption.
#
# F-32b0166f: the launcher goes out of its way to guarantee one clean, actionable stderr
# message for every missing-dependency case -- and then imported `node:child_process` at the
# top level, so on a Node too old to resolve the `node:` protocol the process died in module
# resolution before locate(), fail(), or any of that machinery could run.

_LAUNCHER = Path("npm") / "bin" / "pcraft.mjs"
_NODE = shutil.which("node")
requires_node = pytest.mark.skipif(_NODE is None, reason="the npm launcher needs node on PATH")


def _launch(args: list[str], env: dict[str, str]):
    return subprocess.run(
        [_NODE, str(_LAUNCHER), *args], capture_output=True, env=env, timeout=120, check=False
    )


@requires_node
def test_a_broken_pcraft_python_is_refused_by_name_never_silently_replaced():
    bogus = "C:/definitely/not/a/real/path/python.exe"
    proc = _launch(["--version"], {**os.environ, "PCRAFT_PYTHON": bogus})
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode != 0, (
        f"a broken PCRAFT_PYTHON produced a successful run: {out!r}. Some other interpreter "
        "answered, and nothing said so"
    )
    assert "PCRAFT_PYTHON" in err, f"the rejection does not name the variable: {err!r}"
    assert bogus in err, f"the rejection does not name the path it rejected: {err!r}"
    assert "pcraft " not in out, "a version banner was printed by a fallback interpreter"


@requires_node
def test_a_pcraft_python_that_cannot_import_the_toolkit_says_which_of_the_two_it_is(tmp_path):
    """The module's own doctrine: "no interpreter" and "interpreter, no package" are
    different problems and telling them apart is the whole value of the check. That
    distinction existed for the PATH candidates and not for the configured one."""
    shadow = tmp_path / "shadow"
    (shadow / "pcraft").mkdir(parents=True)
    (shadow / "pcraft" / "__init__.py").write_text(
        "raise ImportError('no toolkit in this interpreter')\n", encoding="utf-8"
    )
    env = {**os.environ, "PCRAFT_PYTHON": sys.executable, "PYTHONPATH": str(shadow)}
    proc = _launch(["--version"], env)
    err = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode != 0
    # Naming the PATH is the assertion, not naming the variable: the pre-fix message already
    # ended with the generic advice line "Point at a specific interpreter with PCRAFT_PYTHON
    # if you use one", so a substring check on the variable name alone passes vacuously
    # against the very defect this pins.
    assert sys.executable in err, (
        f"the configured interpreter was rejected without being named: {err!r}"
    )
    assert "prompt-crafter" in err, "the actionable install line is missing"


@requires_node
def test_the_launcher_checks_its_node_floor_before_any_node_protocol_import():
    source = _LAUNCHER.read_text(encoding="utf-8")
    # STATIC declarations only. `import(...)` -- no space, an opening paren -- is the dynamic
    # form, which is evaluated where it is written and is the fix here, not the defect.
    offenders = re.findall(r'^\s*import\s+(?!\()[^\n]*"node:[^\n]*$', source, re.MULTILINE)
    assert not offenders, (
        "a top-level `node:` import is resolved before any statement in the file runs, so on "
        "a Node too old to support the protocol the process dies with a raw module-resolution "
        f"error instead of this launcher's own clean message: {offenders!r}"
    )
    proc = _launch(["--node-selftest"], dict(os.environ))
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "node >=" in out, f"the selftest does not report the floor it enforces: {out!r}"


def test_the_launchers_hard_floor_is_calibrated_to_the_code_not_to_engines():
    """A guard that mirrors `engines` would reject installs that work fine today.

    npm/package.json declares `>=18` -- the supported-and-tested range. The launcher's own
    hard floor is a different question: the oldest Node on which this FILE can run at all,
    which is set by the `node:` protocol (unflagged from 14.18), not by the support policy.
    """
    engines = json.loads(Path("npm/package.json").read_text(encoding="utf-8"))["engines"]["node"]
    declared_major = int(re.search(r">=\s*(\d+)", engines).group(1))
    source = _LAUNCHER.read_text(encoding="utf-8")
    match = re.search(r"MIN_NODE\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", source)
    assert match, "the launcher declares no explicit Node floor to check against"
    floor = tuple(int(g) for g in match.groups())
    assert floor <= (declared_major, 0, 0), (
        f"the runtime guard's floor {floor} is above the engines range {engines!r}; it would "
        "refuse Node versions this package currently supports"
    )
    assert floor >= (14, 18, 0), (
        f"floor {floor} is below 14.18, where `node:` protocol imports became unflagged -- "
        "the guard would pass a Node that cannot resolve this file's own imports"
    )


# --------------------------------------------------------------------------- F-70ea9458
# The CLI half of the threshold VALUE-drift check. `pcraft replay` already LOADED the
# threshold table and then read only `.version` off it, so the comparison it performed was
# label against label. That catches a retune whose author remembered to bump the version and
# misses the one that has no other signal at all: band values edited under an unchanged
# version string. The receipt then replays "clean" against a table that would have decided
# it differently -- the same "looks like a live check while checking less than it appears
# to" shape the version comparison itself was added to close.
#
# EXPECTED RED IN THIS WORKTREE. `do_replay`'s new `thresholds=` parameter lands in the
# SIBLING core-gate-loop worktree; here `replay()` still has the pre-fold signature and
# raises TypeError on the keyword, which the command's blanket backstop wraps into
# RUNTIME_UNEXPECTED. Both that and the real refusal exit 2, by coincidence of errors.py's
# prefix table (STATE_ -> 2), so the assertions below check the ERROR CODE STRING rather than
# the exit code alone -- otherwise the pre-fold TypeError would read as a pass. This goes
# green on the fold. Do not weaken, skip, or xfail it to force green locally.


def _retuned_table_keeping_the_same_version(tmp_path) -> Path:
    """A different table wearing the same label -- the case a version match cannot see."""
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    data = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    assert data["version"] == "sprite.cal.v1", "fixture assumes the shipped sprite table"
    for band in [*data["bands"].values(), data["default"]]:
        band["high"], band["low"] = 0.99, 0.98  # every PASS the receipt recorded now misses
    tables = tmp_path / "tables"
    tables.mkdir()
    out = tables / "retuned.calibration.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def test_cli_replay_refuses_a_receipt_whose_band_values_moved_under_the_same_version(tmp_path):
    bind = runner.invoke(app, ["bind", "--records-dir", str(tmp_path)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")
    receipts = list(tmp_path.glob("*.json"))
    assert receipts, "bind wrote no receipt"

    retuned = _retuned_table_keeping_the_same_version(tmp_path)
    result = runner.invoke(app, ["replay", str(receipts[0]), "--thresholds", str(retuned)])
    text = (result.stdout or "") + (result.stderr or "")

    assert "RUNTIME_UNEXPECTED" not in text, (
        f"got the unclassified backstop instead of a drift refusal: {text!r}. If this says "
        "'unexpected keyword argument thresholds', that is the documented "
        "expected-red-until-fold state -- the sibling core-gate-loop worktree has not landed "
        "the new do_replay signature yet."
    )
    assert "STATE_REPLAY_DRIFT" in text, (
        f"a receipt decided under different band values replayed as clean: {text!r}. The "
        "version label matched, so only the VALUES could have caught this."
    )
    assert result.exit_code == 2


def test_cli_replay_still_accepts_the_table_the_receipt_was_actually_decided_under(tmp_path):
    """The other direction: the value check must not refuse an honest replay.

    A drift check that fires on the unchanged table would make `pcraft replay` useless, and
    it would fail in the direction nobody notices until a real receipt is rejected. Also
    EXPECTED RED until the fold, for the same reason as its sibling above.
    """
    bind = runner.invoke(app, ["bind", "--records-dir", str(tmp_path)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")
    receipts = list(tmp_path.glob("*.json"))
    assert receipts

    result = runner.invoke(app, ["replay", str(receipts[0])])
    text = (result.stdout or "") + (result.stderr or "")
    assert "STATE_REPLAY_DRIFT" not in text, f"the shipped table refused its own receipt: {text!r}"
    assert result.exit_code == 0, text


# =========================================================================== wave-8
# Stage-C polish (health-amend-c). Everything below was watched RED against the tree at
# 04adc79 before the matching fix landed in cli/__init__.py, sample.py and testing.py.


# --------------------------------------------------------------------------- F-5b783e17
# `_print_result` hardcoded the prefix `records/` in the one line that says WHERE the
# receipt landed, so every non-default --records-dir was misreported -- and the
# IO_RECORD_READ hint the user then hits sends them back to that same line ("pcraft bind
# prints the path it wrote"), closing the recovery loop instead of opening it. MEASURED
# before the fix: `bind --records-dir out/receipts` wrote out/receipts/char_...json and
# printed `receipt: records/char_...json`; feeding the printed path to `replay` refused
# with IO_RECORD_READ at exit 2.


def _printed_receipt_path(text: str) -> Path:
    """The path the run told the operator to hand to ``replay``.

    Reads the LAST non-empty line, which is precisely the promise `bind --help` makes
    ("The last line names the receipt it wrote"). Until wave-10 this parsed
    ``^receipt: (.+?)\\s+hash=`` instead, because the path shared its line with the
    contract hash -- so the helper had to know a layout in order to recover a promise
    that the layout was breaking (F-d4e6686f). Reading the last line means the helper
    asserts the promise rather than working around it.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines, f"no output at all: {text!r}"
    return Path(lines[-1].strip())


def test_bind_prints_the_receipt_path_it_actually_wrote(tmp_path):
    records = tmp_path / "out" / "receipts"
    result = runner.invoke(app, ["bind", "--records-dir", str(records)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    printed = _printed_receipt_path(result.stdout)
    assert printed.is_file(), (
        f"bind printed a receipt path that does not exist: {str(printed)!r}. On disk: "
        f"{[str(p) for p in records.glob('*.json')]}"
    )


def test_demo_prints_the_receipt_path_it_actually_wrote(tmp_path):
    records = tmp_path / "out2"
    result = runner.invoke(app, ["demo", "--records-dir", str(records)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    printed = _printed_receipt_path(result.stdout)
    assert printed.is_file(), f"demo printed a receipt path that does not exist: {str(printed)!r}"


def test_the_path_bind_prints_is_the_path_replay_accepts(tmp_path):
    """The handoff the product exists to connect: bind writes the receipt, replay reads it.

    This is the assertion the defect actually broke -- not "a string is wrong" but "the
    documented next command refuses the path the previous command told you to use".
    """
    records = tmp_path / "somewhere" / "else"
    bind = runner.invoke(app, ["bind", "--records-dir", str(records)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")
    printed = _printed_receipt_path(bind.stdout)

    result = runner.invoke(app, ["replay", str(printed)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "IO_RECORD_READ" not in text, f"the path bind printed could not be read back: {text!r}"
    assert result.exit_code == 0, text


def test_bind_json_carries_the_receipt_path_so_callers_need_not_reconstruct_it(tmp_path):
    """Additive key. The --json document carried record_id and image_path but never said
    where the receipt itself landed, so a machine caller had to rejoin record_id with the
    flag it passed -- i.e. reimplement the very line that was wrong."""
    records = tmp_path / "json-run"
    result = runner.invoke(app, ["bind", "--records-dir", str(records), "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    doc = json.loads(result.stdout)
    assert "receipt_path" in doc, f"--json has no receipt_path: {sorted(doc)}"
    assert Path(doc["receipt_path"]).is_file(), doc["receipt_path"]


def test_bind_json_omits_receipt_path_when_no_receipt_was_written(tmp_path):
    """Omitted, not null: a key whose value is None reads as "there is a path and it is
    empty". The house rule is to leave the key out when there is nothing to say."""
    blocker = tmp_path / "im-a-file-not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["bind", "--records-dir", str(blocker), "--json"])
    stdout = result.stdout or ""
    if stdout.strip():
        doc = json.loads(stdout)
        assert "receipt_path" not in doc, f"receipt_path present with no receipt: {doc!r}"


# --------------------------------------------------------------------------- F-b1b8fd21
# The CLI-C-001 mock disclaimer was printed unconditionally by the shared reporter, so a
# real GPU run reported its own scores as scripted constants -- the exact inverse of the
# defect the line was added to fix. The banner now keys on the generator identity the
# receipt stamps, never on the --mock flag, so it cannot disagree with what ran.


def _live_bind(monkeypatch, tmp_path, argv_extra=()):
    """Drive `bind --no-mock` through the real plugin generator with generate() stubbed.

    Same shape as tests/test_feat_cli.py's live-door test: the GENERATOR IDENTITY stays
    the real one (that is the whole point -- it is what the receipt stamps), only the
    pixels are faked, so the suite stays GPU-free.
    """
    from pcraft import sample
    from pcraft.core.loop.generator_iface import GenerationResult
    from pcraft.domains.image import ImagePlugin
    from pcraft.domains.image.generator.sdxl_generator import SDXLGenerator
    from pcraft.testing import passing_verifiers, write_solid_png

    monkeypatch.setattr(sample, "image_extra_present", lambda: True)
    monkeypatch.setattr(ImagePlugin, "verifiers", lambda self: passing_verifiers())
    png = write_solid_png(tmp_path / "live.png")

    def fake_generate(self, prompt, negative_prompt, conditioning, seed):
        return GenerationResult(
            image_path=str(png),
            seed=seed,
            sampler="test",
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning=conditioning,
        )

    monkeypatch.setattr(SDXLGenerator, "generate", fake_generate)
    return runner.invoke(
        app, ["bind", "--no-mock", "--records-dir", str(tmp_path / "rec"), *argv_extra]
    )


def test_a_live_bind_does_not_report_its_scores_as_scripted(monkeypatch, tmp_path):
    result = _live_bind(monkeypatch, tmp_path)
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, text
    assert "scripted constants" not in text, (
        "a --no-mock run printed the mock disclaimer above its own BOUND verdict; the "
        f"receipt's narration disowns the measurement it certifies: {text!r}"
    )


def test_a_live_bind_says_positively_that_the_scores_are_real(monkeypatch, tmp_path):
    """Absence of a disclaimer is easy to misread as a stripped banner. A positive line
    is checkable; silence is not."""
    result = _live_bind(monkeypatch, tmp_path)
    text = (result.stdout or "") + (result.stderr or "")
    assert "live:" in text, f"the live path marks itself with nothing: {text!r}"


def test_a_mock_bind_still_says_the_scores_are_scripted(tmp_path):
    """The direction the banner was added for, unchanged."""
    result = runner.invoke(app, ["bind", "--mock", "--records-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "scripted constants" in result.stdout
    assert "the image pixels were not read" in result.stdout


def test_demo_still_says_the_scores_are_scripted(tmp_path):
    result = runner.invoke(app, ["demo", "--records-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "scripted constants" in result.stdout


# --------------------------------------------------------------------------- F-339753d3
# --debug was a bare typer.Option(False) on all twelve commands, so the one flag the
# CLI's own refusals tell users to reach for ("Re-run with --debug for pydantic's full
# report") was the one flag --help declined to explain. The exit-code contract -- this
# product's machine-facing API -- appeared nowhere in --help either.


def _every_declared_param():
    group = typer.main.get_command(app)
    out = [(f"pcraft --{p.name}", p) for p in group.params]
    for name, sub in sorted(group.commands.items()):
        out += [(f"{name} --{p.name}", p) for p in sub.params]
    return out


def test_every_rendered_flag_and_argument_carries_a_help_string():
    """No flag is documented on three commands and blank on two.

    Blanket rather than per-flag on purpose: the defect was an inconsistency, and a test
    that names today's offenders would go quiet the moment a new one is added.
    """
    naked = [where for where, p in _every_declared_param() if not (getattr(p, "help", None) or "")]
    assert not naked, "flags/arguments rendered with no description: " + ", ".join(naked)


def test_debug_is_explained_everywhere_it_is_offered():
    group = typer.main.get_command(app)
    offenders = []
    for name, sub in sorted(group.commands.items()):
        for p in sub.params:
            if p.name != "debug":
                continue
            help_text = (getattr(p, "help", None) or "").lower()
            if "traceback" not in help_text:
                offenders.append(f"{name}: {help_text!r}")
    assert not offenders, (
        "the CLI's own error text sends users to --debug; these pages do not say what it "
        "does: " + "; ".join(offenders)
    )


@pytest.mark.parametrize(
    ("command", "codes"),
    # Each command's OWN reachable codes, not one shared list: replay cannot exit 4 (it
    # scores nothing), and asserting a code a command cannot produce would document a
    # promise the CLI does not keep.
    [
        ("gate", ("0", "2", "3", "4")),
        ("bind", ("0", "2", "3", "4")),
        ("replay", ("0", "1", "2")),
    ],
    ids=["gate", "bind", "replay"],
)
def test_the_commands_a_script_calls_name_their_exit_codes_in_help(command, codes):
    """`gate` and `bind` are called from CI. A script author who reaches for --help must
    be able to learn the 2-vs-4 distinction without leaving the CLI for STABILITY.md."""
    group = typer.main.get_command(app)
    body = group.commands[command].help or ""
    assert "exit" in body.lower(), f"{command} --help says nothing about exit status: {body!r}"
    for code in codes:
        assert code in body, f"{command} --help never names exit {code}: {body!r}"


# --------------------------------------------------------------------------- F-3c6d9f4f
# The DEP_IMAGE_MISSING hint -- the product's principal "how do I go live" unblock -- named
# `pip install -e '.[image]'`, which requires a buildable project in the cwd. README.md:50
# makes `pip install prompt-crafter` (PyPI, no checkout) the primary documented install and
# the npm launcher installs no checkout either, so for the majority install the hinted
# command fails inside pip -- a second wall, reached by following the CLI's own advice.
# npm/bin/pcraft.mjs already uses the registry form (lines 137, 206).


def test_the_dep_image_missing_hint_leads_with_the_install_the_readme_documents(monkeypatch, tmp_path):
    from pcraft import sample

    monkeypatch.setattr(sample, "image_extra_present", lambda: False)
    result = runner.invoke(app, ["bind", "--no-mock", "--records-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "DEP_IMAGE_MISSING" in text, text
    hint = text.split("hint:")[-1]
    assert "pip install 'prompt-crafter[image]'" in hint, (
        f"the hint does not name the registry install the README leads with: {text!r}"
    )
    lead, _, rest = hint.partition("pip install 'prompt-crafter[image]'")
    assert "-e" not in lead, f"the checkout-only form still leads the hint: {text!r}"
    assert "-e '.[image]'" in rest, (
        "the source-checkout form should survive as the parenthetical secondary case, so a "
        f"developer in a clone is not sent to the registry: {text!r}"
    )


# --------------------------------------------------------------------------- F-710c9599
# `bind` printed nothing between invocation and final verdict, and the loop it drives can
# run many generate-and-verify cycles inside that silence -- on live hardware, minutes of
# it on this product's one spend path, during which an operator cannot tell "attempt 5 of
# 7" from "hung on a model load". The progress lines go to stderr (the channel this file
# already owns for non-document output) so stdout stays a parseable --json document.


def test_a_live_bind_narrates_each_attempt_while_it_is_still_useful(monkeypatch, tmp_path):
    result = _live_bind(monkeypatch, tmp_path)
    err = result.stderr or ""
    assert "[attempt 1]" in err, (
        f"a --no-mock run emitted no progress before its verdict; stderr was: {err!r}"
    )
    assert "seed=" in err


def test_progress_lines_never_contaminate_the_json_document(monkeypatch, tmp_path):
    result = _live_bind(monkeypatch, tmp_path, argv_extra=["--json"])
    assert "[attempt" not in (result.stdout or ""), (
        "progress went to stdout and broke the document contract"
    )
    json.loads(result.stdout)  # still parseable
    assert "[attempt 1]" in (result.stderr or "")


def test_the_mock_path_stays_quiet(tmp_path):
    """Nothing in the mock path takes long enough to need narrating, and unconditional
    chatter would be a regression for the command the test suite calls most."""
    result = runner.invoke(app, ["bind", "--mock", "--records-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "[attempt" not in text, text


# =========================================================================== wave-10
# Stage-D polish (cli-ux amend). Terminal-visual layout only: every fix below moves
# characters on the HUMAN channel, which STABILITY.md puts under "Not covered ... Log
# and human-readable output wording. Parse --json, not the banner." Each test here was
# watched RED against the tree at 6838d85 before the matching fix landed.


def _stdout_at(argv, columns="100"):
    """Render a command in a FRESH SUBPROCESS at a PINNED width so a layout assertion
    measures layout.

    Terminal width is an input to every wrap in this section. The first form of this
    helper pinned COLUMNS through in-process CliRunner, which is order-dependent: the
    help renderer's console is created once per process and caches the width it saw
    first, so these tests reported whichever geometry an EARLIER test had baked in --
    green on wide developer consoles, red on CI's 80 columns, in the same suite. A
    fresh process is the only rendering both halves of that split agree on (the same
    reasoning as the cp437 subprocess tests above: pin the console, not the weather).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pcraft", *argv],
        capture_output=True,
        # NO_COLOR: the GitHub runner makes Rich force ANSI even when piped, so every
        # rendered line starts with an escape sequence instead of its indent and the
        # layout regexes match nothing -- same class as the width cache, third axis
        # (color). And NO_COLOR alone is not enough: Rich reads it as "no colors" and
        # STILL emits style escapes (dim/bold), measured on the runner. The env pin
        # stays for the axes it does hold (width, encoding), and the return strips
        # whatever escapes survive -- these tests assert the geometry a human sees.
        env={**os.environ, "COLUMNS": columns, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"},
        timeout=60,
        check=False,
        text=True,
        encoding="utf-8",
    )
    return re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout or "")


@pytest.mark.parametrize("module", ["pcraft", "pcraft.cli"])
def test_python_dash_m_reports_the_console_script_name(module):
    """Phase 9 (F7): the npm launcher spawns `python -m pcraft.cli`, and click derives the
    usage line from argv -- so every launcher user read `Usage: python -m pcraft.cli ...`
    for a command they typed as `pcraft` and may not even have on PATH as `python`. Both
    -m doors pin prog_name to the one name every door answers to.
    """
    proc = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        env={**os.environ, "COLUMNS": "100", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"},
        timeout=60,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    out = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout or "")
    first = next(line for line in out.splitlines() if line.strip())
    assert "Usage: pcraft " in first, f"the -m door leaks its own invocation: {first!r}"
    assert "python -m" not in first, first


def test_calibrate_help_does_not_swallow_the_extra_name():
    """Phase 9 (F4): Rich parsed `[image]` in the rendered docstring panel as a markup tag
    and dropped it, so the exit-2 line read "the  extra is missing" -- subject deleted, on
    the one page that explains that exit code. The docstring escapes the bracket; this
    renders the page the way an operator sees it and reads the sentence back.
    """
    text = _stdout_at(["calibrate", "--help"])
    assert "[image] extra is missing" in text, (
        f"the exit-2 line lost its subject to markup again: {text!r}"
    )
    assert r"\[image]" not in text, "the escape itself leaked into the rendered page"


# --------------------------------------------------------------------------- F-f880d5a4
# The exit-code tables in the gate/bind/replay long-help docstrings put every code and
# every following sentence at the same rendered margin, so prose that happens to open
# with a numeral was indistinguishable from a code entry. MEASURED at COLUMNS=100 on the
# shipped tree: `gate --help` rendered two consecutive lines beginning "4 " (one the
# definition of exit 4, one the sentence "4 is never folded into 2 ..."), and
# `bind --help` rendered the sequence 0,1,2,3,4,2 -- a five-code contract that appears to
# redefine 2 on its own help page. `replay --help` wrapped code 1's text onto a second
# source line, leaving "re-bind." as an unnumbered orphan entry between codes 1 and 2.
# This is the table STABILITY.md declares covered and the only structured content on any
# of the twelve help pages.

# An entry is indented under the heading AND separates its digit from its description by
# a real column of whitespace. Prose reflowed by the renderer can do neither.
_EXIT_ENTRY = re.compile(r"^ +(\d) {2,}\S")
# What the eye actually does: read the first token of every line in the block.
_LEADING_DIGIT = re.compile(r"^(\d)[ .)]")


def _exit_code_block(cmd: str) -> list[str]:
    text = _stdout_at([cmd, "--help"])
    start = text.find("Exit codes:")
    assert start >= 0, f"{cmd} --help has no `Exit codes:` block: {text!r}"
    body = text[start:].splitlines()[1:]
    out = []
    for line in body:
        # The help page continues past the docstring into Typer's options table.
        if line.strip().startswith(("Options", "--", "─", "╭", "│")):
            break
        out.append(line.rstrip())
    return out


@pytest.mark.parametrize(
    ("cmd", "codes"),
    [
        ("gate", ["0", "1", "2", "3", "4"]),
        ("bind", ["0", "1", "2", "3", "4"]),
        ("replay", ["0", "1", "2"]),
    ],
)
def test_the_exit_code_table_renders_as_a_table_not_a_paragraph(cmd, codes):
    """MEASURED red: zero lines matched _EXIT_ENTRY on all three pages, because every
    code sat at the docstring's common indent with a single space after the digit -- the
    same shape the surrounding prose has."""
    block = _exit_code_block(cmd)
    entries = [m.group(1) for line in block if (m := _EXIT_ENTRY.match(line))]
    assert entries == codes, (
        f"`pcraft {cmd} --help` does not render its exit codes as entries. Parsed "
        f"{entries}, expected {codes}. Block was:\n" + "\n".join(block)
    )


@pytest.mark.parametrize("cmd", ["gate", "bind", "replay"])
def test_prose_starting_with_a_numeral_cannot_be_read_as_a_code_entry(cmd):
    """MEASURED red: gate read 0,1,2,3,4,4 and bind read 0,1,2,3,4,2 -- a contract that
    contradicts itself in the one place a scripted caller is sent to read it.

    The trailing commentary on two of these pages legitimately opens with a numeral ("4 is
    never folded into 2 ...", "2 means the gate ran and refused ..."), so the fix is not to
    forbid that -- it is to make the two readable apart. A margin does that: entries render
    indented under the heading, commentary renders shallower and behind a blank line. This
    asserts the margin, because stripping it is exactly what made the two look alike.
    """
    block = _exit_code_block(cmd)
    entries = [line for line in block if _EXIT_ENTRY.match(line)]
    entry_indent = len(entries[0]) - len(entries[0].lstrip())
    codes = [_EXIT_ENTRY.match(line).group(1) for line in entries]
    assert len(codes) == len(set(codes)), (
        f"`pcraft {cmd} --help` defines a code twice: {','.join(codes)}"
    )
    prose = [
        line
        for line in block
        if line.strip() and line not in entries and _LEADING_DIGIT.match(line.strip())
    ]
    for line in prose:
        assert len(line) - len(line.lstrip()) < entry_indent, (
            f"`pcraft {cmd} --help` renders a sentence at the exit-entry margin, so it reads "
            f"as a redefinition of code {line.strip()[0]}: {line!r}"
        )


@pytest.mark.parametrize("cmd", ["gate", "bind", "replay"])
def test_the_commentary_under_an_exit_table_is_separated_from_it(cmd):
    """A blank line is what makes the trailing paragraph read as commentary rather than
    as more entries; it is also what stops the renderer from reflowing prose into the
    table. MEASURED red: no blank line anywhere inside the block on any of the three."""
    block = _exit_code_block(cmd)
    entries = [i for i, line in enumerate(block) if _EXIT_ENTRY.match(line)]
    assert entries, "no entries parsed at all"
    tail = block[entries[-1] + 1:]
    if any(line.strip() for line in tail):
        assert not tail[0].strip(), (
            f"`pcraft {cmd} --help` runs commentary straight on from the last exit code "
            f"with no separating blank line: {tail[:3]!r}"
        )


def test_every_exit_entry_wraps_under_its_own_description_column():
    """`replay`'s code 1 is the only entry whose text needs two rows. MEASURED red: the
    continuation `re-bind.` rendered at the entry margin, so it read as an unnumbered
    entry sitting between code 1 and code 2."""
    block = _exit_code_block("replay")
    entries = [i for i, line in enumerate(block) if _EXIT_ENTRY.match(line)]
    assert entries, "no entries parsed at all"
    first, last = entries[0], entries[-1]
    entry_indent = len(block[first]) - len(block[first].lstrip())
    for i in range(first, last):
        line = block[i]
        if i in entries or not line.strip():
            continue
        assert len(line) - len(line.lstrip()) > entry_indent, (
            "a continuation line inside `pcraft replay --help`'s exit table sits at the "
            f"entry margin and reads as an entry of its own: {line!r}"
        )


# --------------------------------------------------------------------------- F-1e1af911
# `decision: {DECISION}  ({reason})` was written when `reason` was one line. Since wave-8
# an escalation's reason IS the multi-line build_checkpoint artifact, so the opening
# parenthesis at column 21 of the decision line closed four lines and ~790 characters
# later, glued to a question mark. MEASURED through the owned render path: the single
# _say call emitted 911 characters, `attempts:` appeared only AFTER the parenthetical,
# and the bullets (204/225/157/199 chars) soft-wrapped with zero continuation indent, so
# the tail of one ran straight into the next bullet's `  - ` marker. The one block in the
# output written to be read by a person was the only one with no visual frame.

_ESCALATING_SCORES = {
    "tabard": 0.05,
    "palette": 0.30,
    "face": 0.60,
    "sigil": 0.95,
    "skin": 0.95,
    "weapon": 0.95,
}


def _escalated_render(tmp_path, columns=100):
    """Drive the owned render path directly: the checkpoint is what is under test, and
    reaching it through the CLI would also drag in the ten-row transcript."""
    import contextlib as _ctx
    import io as _io

    from pcraft.cli import _print_result

    result = run_mock_loop(records_dir=str(tmp_path), verifier_scores=_ESCALATING_SCORES)
    assert "\n" in result.reason, "this fixture only means anything on a multi-line reason"
    buf = _io.StringIO()
    previous = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(columns)
    try:
        with _ctx.redirect_stdout(buf):
            _print_result(result, records_dir=str(tmp_path))
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous
    return result, buf.getvalue()


def _reason_block(out):
    lines = out.splitlines()
    i = next(i for i, ln in enumerate(lines) if ln.startswith("decision:"))
    j = next(j for j, ln in enumerate(lines) if ln.startswith("attempts:"))
    return [ln for ln in lines[i + 1:j] if ln.strip()]


def test_the_decision_line_is_one_readable_line(tmp_path):
    """MEASURED red: 122 characters and one unbalanced `(` left open for four lines."""
    _r, out = _escalated_render(tmp_path)
    line = next(ln for ln in out.splitlines() if ln.startswith("decision:"))
    assert len(line) <= 100, f"the decision line is {len(line)} chars: {line!r}"
    assert line.count("(") == line.count(")"), (
        f"the decision line opens a parenthesis it never closes: {line!r}"
    )


def test_the_checkpoint_renders_as_an_indented_block_under_the_decision(tmp_path):
    """The UNCERTAINTY_GATED_HUMANS artifact gets the same headline/indented-body shape
    the npm launcher uses for its own multi-line output. MEASURED red: the whole
    checkpoint was inside the decision line's parenthetical, so there was no block."""
    result, out = _escalated_render(tmp_path)
    block = _reason_block(out)
    assert block, "the reason did not render below the decision at all"
    stray = [ln for ln in block if not ln.startswith("  ")]
    assert not stray, f"a reason line escaped the block indent: {stray!r}"
    # Composed-seam ruling (wave-10 fold): checkpoint.py owns the body's shape and no
    # longer emits "- " bullets -- per-atom entries are an id/zone/score head row plus
    # labelled claim:/thought:/chose: lines under the errors.py wrapping convention. The
    # CLI frames that block; it does not re-compose it. Assert the canonical shape.
    assert any(re.match(r"^\s+claim:\s+\S", ln) for ln in block), (
        "the per-atom entries vanished (no labelled claim lines in the block)"
    )
    # MEASURED red on this assertion: the contrastive headline was the FIRST thing inside
    # the decision line's parenthetical, so none of it appeared in the block below.
    headline = result.reason.partition("\n")[0]
    assert headline.split()[0] in " ".join(block[:3]), (
        f"the contrastive headline did not move into the block: {block[:3]!r}"
    )
    assert headline not in next(ln for ln in out.splitlines() if ln.startswith("decision:"))


def test_no_reason_line_overruns_the_terminal(tmp_path):
    """MEASURED red at COLUMNS=100: bullets of 204/225/157/199 characters, each
    soft-wrapping to two or three rows with no continuation indent."""
    _r, out = _escalated_render(tmp_path)
    long = [ln for ln in _reason_block(out) if len(ln) > 100]
    assert not long, f"lines wider than the terminal: {[(len(ln), ln) for ln in long]}"


def test_a_wrapped_bullet_continues_under_its_own_text(tmp_path):
    """Without a continuation indent the tail of one entry is visually the head of the
    next. Composed-seam ruling (wave-10 fold): the body is checkpoint.py's pre-wrapped
    text under the errors.py convention -- a wrapped ``claim:`` value continues under
    its own TEXT column (label width deep), never back at the block margin -- and the
    CLI's framing must PRESERVE that hang, which is exactly what the first form of this
    test caught it destroying."""
    _r, out = _escalated_render(tmp_path)
    block = _reason_block(out)
    label_rows = [
        (k, m.end())
        for k, ln in enumerate(block)
        if (m := re.match(r"^\s+(claim|thought|chose):\s+", ln))
    ]
    assert label_rows, "no labelled entry lines to check"
    continuations = []
    for k, text_col in label_rows:
        j = k + 1
        while j < len(block) and block[j].strip() and not re.match(
            r"^\s+(claim|thought|chose):\s|^\s+\S+\s+(PASS|FAIL|UNCERTAIN|NA|SKIPPED)\b",
            block[j],
        ):
            continuations.append((block[j], text_col))
            j += 1
    if not continuations:
        pytest.skip("every labelled value fitted on one row; nothing to prove")
    for line, text_col in continuations:
        indent = len(line) - len(line.lstrip())
        assert indent >= text_col - 1, (
            f"a wrapped value resumed at the margin instead of under its text: {line!r}"
        )


def test_a_single_line_reason_keeps_its_compact_form(tmp_path):
    """The BOUND line was never the defect -- 44 characters, correctly grouped. The fix
    restructures the multi-line case and leaves this one alone."""
    out = _stdout_at(["bind", "--records-dir", str(tmp_path)])
    line = next(ln for ln in out.splitlines() if ln.startswith("decision:"))
    assert line == "decision: BOUND  (all required atoms passed)", line


# --------------------------------------------------------------------------- F-d4e6686f
# The receipt line is the one artifact the operator carries to the next command, and it
# was the longest line in the product's output, had no blank line above it, and was not
# actually a path: `receipt: {path}  hash={hash}...` on one physical line directly under
# the last row of the ten-row atom table. `bind --help` promises "The last line names the
# receipt it wrote ... run `pcraft replay` on exactly that path", but `tail -1` yielded
# path + two spaces + hash, which `replay` refuses -- the same recovery loop F-5b783e17
# closed, reopened at the layout level.


def test_the_last_line_is_the_receipt_path_and_nothing_else(tmp_path):
    """MEASURED red: the last line was path + `  hash=sha256:...` on one row."""
    out = _stdout_at(["bind", "--records-dir", str(tmp_path / "recs")])
    last = [ln for ln in out.splitlines() if ln.strip()][-1]
    assert "hash" not in last, f"the hash still shares the last line: {last!r}"
    assert Path(last.strip()).is_file(), (
        f"the last line is not a readable receipt path: {last!r}"
    )


def test_the_receipt_gets_its_own_block(tmp_path):
    """It is the most important line on screen and it was jammed against a ten-row table
    of 121-125 character rows that it visually continued. The function already
    blank-lines the block ABOVE the transcript and gave the receipt nothing."""
    out = _stdout_at(["demo", "--records-dir", str(tmp_path)])
    lines = out.splitlines()
    i = next(i for i, ln in enumerate(lines) if ln.rstrip() == "receipt:")
    assert not lines[i - 1].strip(), (
        f"no blank line above the receipt block: {lines[i - 2:i + 1]!r}"
    )
    assert lines[i + 1].strip().startswith("hash:"), (
        f"the hash did not get its own labelled line: {lines[i + 1]!r}"
    )


def test_tail_minus_one_is_exactly_what_replay_accepts(tmp_path):
    """The promise in `bind --help`, asserted end to end rather than described."""
    out = _stdout_at(["bind", "--records-dir", str(tmp_path / "deep" / "er")])
    printed = [ln for ln in out.splitlines() if ln.strip()][-1].strip()
    result = runner.invoke(app, ["replay", printed])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, f"replay refused the line bind printed last: {text!r}"


# --------------------------------------------------------------------------- F-2d223d8e
# Five human-facing lines interpolated a Python list straight into an f-string, so
# brackets, quotes and `', '` separators reached the terminal as though the operator were
# reading a repl -- and inside a single block whose line above already joined FOR humans
# (`lineage: faction:ashen-pact -> char:ashen-reaver`). `doctor` compounded it with a
# duplicated word: `mark` is already "missing" and `detail` opened with "  missing ", so
# the row read `[image] missing  missing ['torch', ...]`. All five values are already
# carried as real arrays in --json, so the repr on the human channel buys nothing.


@pytest.mark.parametrize(
    ("command", "label"),
    [
        ("validate", "required:"),
        ("validate", "must_not:"),
        ("demo", "required atoms:"),
        ("demo", "must_not:"),
    ],
)
def test_a_human_line_never_shows_python_list_syntax(command, label, tmp_path):
    argv = [command] + (["--records-dir", str(tmp_path)] if command == "demo" else [])
    line = next(ln for ln in _stdout_at(argv).splitlines() if ln.startswith(label))
    assert "[" not in line and "'" not in line, f"repr leaked to the terminal: {line!r}"
    assert ", " in line, f"the values were not joined for a reader: {line!r}"


def test_doctor_does_not_say_missing_twice():
    """MEASURED red: `[image] missing  missing ['torch', 'diffusers', ...]`."""
    rows = [ln for ln in _stdout_at(["doctor"]).splitlines() if ln.startswith("[")]
    assert rows, "doctor reported no extras at all"
    for line in rows:
        assert "missing  missing" not in line, line
        assert "[" not in line[line.index("]"):], f"repr leaked: {line!r}"
        assert "'" not in line, f"repr leaked: {line!r}"


# --------------------------------------------------------------------------- F-3c91e814
# The version-mismatch warning is the line `doctor` exists to surface and the only one in
# its report that loses its own hierarchy when rendered: a single 219-character string
# whose entire structure was a leading two-space indent. MEASURED at COLUMNS=80 the line
# occupied three visual rows, and rows two and three began at column 0 -- the same level
# as the sibling top-level rows -- so the actionable half, `(reinstall: pip install -e .
# --no-deps)`, ended up at column 0 reading as an unrelated top-level status. Every other
# line doctor prints fits inside 80.

_WARNING = (
    "installed prompt-crafter metadata says 0.2.1, but this source tree declares 1.0.0; "
    "the dist-info is stale, so the version above is not the code you are running "
    "(reinstall: pip install -e . --no-deps)"
)


def test_the_version_warning_wraps_and_stays_a_child_of_the_line_above():
    from pcraft.cli import _version_mismatch_lines

    lines = _version_mismatch_lines(_WARNING, 80)
    assert len(lines) > 1, "a 219-character warning still rendered as one line"
    assert lines[0].startswith("  VERSION MISMATCH: "), lines[0]
    assert all(len(ln) <= 80 for ln in lines), [(len(ln), ln) for ln in lines]
    assert all(ln.startswith("    ") for ln in lines[1:]), (
        f"a continuation row fell back to column 0 and reads as a sibling: {lines[1:]!r}"
    )


def test_the_remedy_gets_its_own_copy_pasteable_line():
    from pcraft.cli import _version_mismatch_lines

    lines = _version_mismatch_lines(_WARNING, 80)
    fix = [ln for ln in lines if ln.strip().startswith("fix:")]
    assert len(fix) == 1, f"no single `fix:` line: {lines!r}"
    assert fix[0].strip() == "fix: pip install -e . --no-deps", fix[0]
    assert "reinstall:" not in "\n".join(lines), "the parenthetical survived"


def test_an_unparseable_warning_still_wraps_rather_than_overrunning():
    """Graceful degradation: if `version_coherence` ever stops ending in a remedy
    parenthetical, the layout fix must still do the half it can."""
    from pcraft.cli import _version_mismatch_lines

    lines = _version_mismatch_lines("x " * 90, 80)
    assert len(lines) > 1 and all(len(ln) <= 80 for ln in lines)


def test_the_warning_the_shipped_check_produces_is_the_one_that_was_measured():
    """Couples the layout helper to the string it splits. If `version_coherence` stops
    ending in `(reinstall: ...)`, this fails here rather than silently degrading in
    doctor's report."""
    import pcraft

    warning = pcraft.version_coherence()
    if warning is None:
        pytest.skip("installed metadata agrees with the tree; nothing to split")
    assert warning.endswith("(reinstall: pip install -e . --no-deps)"), warning
