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


@pytest.mark.parametrize(
    "argv",
    [
        ["gate"],  # missing IMAGE argument
        ["replay"],  # missing RECORD argument
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
# cp437 is the assertion rather than str.isascii() on the RENDERED page because Rich draws
# the help panels with box characters (U+2500/2502/250C/2510/2514/2518) that cp437 encodes
# fine. The source-declared strings are checked for pure ASCII separately, below.


def _help_argvs() -> list[list[str]]:
    group = typer.main.get_command(app)
    return [["--help"], *[[name, "--help"] for name in sorted(group.commands)]]


@pytest.mark.parametrize("argv", _help_argvs(), ids=lambda a: "-".join(a).replace("--", ""))
def test_every_rendered_help_page_encodes_on_a_cp437_console(argv):
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, f"pcraft {' '.join(argv)} did not render"
    text = (result.stdout or "") + (result.stderr or "")
    try:
        text.encode("cp437")
    except UnicodeEncodeError as exc:
        offending = text[exc.start : exc.end]
        pytest.fail(
            f"pcraft {' '.join(argv)} renders U+{ord(offending[0]):04X} ({offending!r}), which a "
            "cp437 console cannot encode -- on such a console this help page dies with an "
            "unhandled UnicodeEncodeError and exit 1, outside every --debug gate"
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
