"""Every quality tool configured in pyproject must actually be a verify.py leg.

The defect this pins is not "mypy was wrong". It is that ``[tool.mypy]`` existed in
pyproject, no workflow and no script ever invoked it, and so when the ``[image]`` extra
pulled numpy 2.5 the typecheck began aborting on numpy's PEP 695 stubs *before checking a
single pcraft file* -- and nothing noticed. It read as a configured gate for as long as
nobody ran it. It was hiding 7 real errors when it was finally run by hand.

That is this repo's own subject matter pointed at its own toolchain: a check that reports
nothing while doing nothing. Asserting "mypy is clean" here would be the wrong test -- it
would be slow, environment-dependent, and it would still pass if someone deleted the leg.
The invariant that actually protects the gate is *reachability*: a tool configured as a
gate must be wired to something that runs.

So this reads verify.py's own call graph rather than matching strings, and generalizes --
add ``[tool.bandit]`` to pyproject without a leg and this fails.

The file has since grown three more sections, and they belong here for one reason: this is
where the repo pins the behaviour of its OWN gate tooling, as opposed to the behaviour of
the package. The gate is not only verify.py. It is also scripts/wheel_smoke.py (the only
check in this repo that runs against a NON-editable install, and therefore the only one that
sees the packaging rule at all), release.yml's refusals (the last thing an operator reads
before an irreversible publish) and scripts/mutate_predicates.py (which rewrites tracked
source files in place, and until it grew a consent flag did so on any invocation, ``--help``
included). Each section says in its own docstring exactly how much it proves, because
several of them read a file as text and text is easy to over-claim from.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "verify.py"
PYPROJECT = ROOT / "pyproject.toml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
MUTATE = ROOT / "scripts" / "mutate_predicates.py"
WHEEL_SMOKE = ROOT / "scripts" / "wheel_smoke.py"

# `[tool.X]` tables that are quality GATES (a tool that can fail a build), mapped to the
# module verify.py runs. Config-only tables (tool.pytest.ini_options, tool.hatch,
# tool.coverage) are settings for something already covered and are deliberately absent.
GATE_TOOLS = {"ruff": "ruff", "mypy": "mypy"}


def _str_items(node: ast.AST) -> list[str]:
    """String constants in a list literal. Non-constant elements (f-strings, vars) drop."""
    if not isinstance(node, ast.List):
        return []
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _verify_legs() -> dict[str, list[str]]:
    """Map each ``_run("<label>", <argv>, ...)`` in verify.py to its argv strings, in
    SOURCE order.

    Parsed from the AST, not grepped: a leg written but commented out, or moved into a
    branch that never executes, should not read as wired.

    Two shapes matter and both are real in this file. The static legs pass a list literal
    inline; the suite leg builds ``pytest = [...]`` first and passes the name. An earlier
    version of this parser only understood the literal, silently found no "suite" leg, and
    the ordering assertion blew up with a ValueError instead of a useful message -- a test
    whose own blind spot looked like a failure of the thing under test. Simple local
    list assignments are therefore resolved.

    Ordering comes from ``lineno``, not dict insertion: ``ast.walk`` yields breadth-first,
    so insertion order is not source order and the "static legs run first" assertion would
    have been checking nothing meaningful.
    """
    tree = ast.parse(VERIFY.read_text(encoding="utf-8"))

    assigned: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                items = _str_items(node.value)
                if items:
                    assigned[target.id] = items

    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "_run" or len(node.args) < 2:
            continue
        label, argv = node.args[0], node.args[1]
        if not (isinstance(label, ast.Constant) and isinstance(label.value, str)):
            continue
        if isinstance(argv, ast.List):
            items = _str_items(argv)
        elif isinstance(argv, ast.Name):
            items = assigned.get(argv.id, [])
        else:
            items = []
        found.append((node.lineno, label.value, items))

    return {label: argv for _, label, argv in sorted(found)}


def _leg_env_var(label: str) -> str | None:
    """The NAME of the env mapping handed to the ``_run`` call labelled ``label``.

    Read from the call graph for the same reason ``_verify_legs`` is. Half of what the
    ``-O`` leg does lives in its third argument and nowhere else, so a grep for
    ``PYTHONOPTIMIZE`` anywhere in the file would still pass if the variable carrying it
    were never handed to this leg. Returns None when the argument is not a bare name --
    which is itself a finding, not a pass.
    """
    tree = ast.parse(VERIFY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "_run" or len(node.args) < 3:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == label:
            env = node.args[2]
            return env.id if isinstance(env, ast.Name) else None
    return None


def _env_overrides(var: str) -> dict[str, str]:
    """Constant ``<var>["KEY"] = "VALUE"`` assignments in verify.py, as a mapping.

    Non-constant values (``env["PYTHONPATH"]`` is built from a conditional) drop rather
    than being guessed at; nothing here needs them.
    """
    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(VERIFY.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)):
            continue
        if target.value.id != var:
            continue
        key, value = target.slice, node.value
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
            out[str(key.value)] = str(value.value)
    return out


def _configured_gate_tools() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return {name for name in data.get("tool", {}) if name in GATE_TOOLS}


def test_verify_parses_and_has_legs():
    legs = _verify_legs()
    assert legs, "no _run(...) legs found in verify.py -- the parser or the file shape changed"


@pytest.mark.parametrize("tool", sorted(GATE_TOOLS))
def test_each_configured_gate_tool_is_a_verify_leg(tool: str):
    if tool not in _configured_gate_tools():
        pytest.skip(f"[tool.{tool}] is not configured in pyproject")
    invoked = {t for argv in _verify_legs().values() for t in argv}
    assert GATE_TOOLS[tool] in invoked, (
        f"[tool.{tool}] is configured in pyproject but verify.py never invokes it. "
        f"A gate nothing runs cannot fail -- wire it as a _run leg or drop the config."
    )


def test_coverage_tooling_is_declared_only_if_something_invokes_it():
    """``pytest-cov>=5.0`` sat in the ``dev`` extra with no ``--cov`` anywhere in the tree.

    The same "configured but invoked by nothing" shape as ``[tool.mypy]``, landing on a
    dependency instead of a tool table -- so nothing read as a false-green gate, but every
    ``pip install -e ".[dev]"`` still paid install time for a plugin that measured nothing.
    It was removed rather than wired up, because ``--cov`` with no threshold is a number
    nobody agreed to. Written as an implication rather than as "must be absent": bring the
    dependency back in the same commit as the leg that uses it and this passes.
    """
    dev = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["dev"]
    declared = any(req.startswith("pytest-cov") for req in dev)
    invoked = "--cov" in VERIFY.read_text(encoding="utf-8")
    assert not (declared and not invoked), (
        "pytest-cov is in the [dev] extra but verify.py never passes --cov, so every "
        "contributor installs a plugin that measures nothing and gates nothing. Wire it to "
        "the suite leg or drop the dependency."
    )


def test_the_suite_is_still_a_leg():
    """Static legs must not have displaced the deterministic floor."""
    invoked = {t for argv in _verify_legs().values() for t in argv}
    assert "pytest" in invoked, "verify.py must still run the suite"
    assert "build" in invoked, "verify.py must still build the wheel/sdist"


def test_static_legs_run_before_the_suite():
    """Ordering is deliberate: seconds-long checks should not queue behind the suite."""
    labels = list(_verify_legs())
    for fast in ("lint", "typecheck"):
        assert fast in labels, f"verify.py has no {fast!r} leg"
        assert labels.index(fast) < labels.index("suite"), (
            f"{fast!r} leg runs after the suite; put the fast static checks first"
        )


def test_the_optimized_pass_is_still_a_leg():
    """The leg that catches a gate written as a bare ``assert``.

    ``assert`` is stripped under -O, so a refusal written as one silently disappears --
    the risk verify.py's own docstring names ("gates must still raise"). Every OTHER leg
    in this file was pinned for reachability and this one was not: nothing failed if a
    refactor deleted the call, and the label would have gone with it, so not even the
    summary would have looked different.

    That gap is this repo's recurring shape landing in the one file whose job is closing
    it -- after ``[tool.mypy]`` configured and invoked by nothing, and after lint running
    ``src tests`` while exempting the file that defines the gate.
    """
    legs = _verify_legs()
    assert "suite under -O" in legs, (
        "verify.py has no 'suite under -O' leg -- a gate written as a bare assert can go "
        "inert with nothing failing"
    )
    assert "-O" in legs["suite under -O"], (
        "the 'suite under -O' leg does not pass -O to the interpreter; the label claims an "
        "optimized run the argv does not perform"
    )
    assert "pytest" in legs["suite under -O"], "the -O leg must still run the suite"


def test_the_optimized_leg_carries_optimization_into_child_processes():
    """``-O`` and ``PYTHONOPTIMIZE=1`` are not redundant, and the difference was measured.

    ``-O`` sets ``sys.flags.optimize`` for the pytest process only. A child interpreter
    the suite launches inherits the ENVIRONMENT, not the flag, and comes up at
    ``optimize=0``; ``PYTHONOPTIMIZE=1`` is what carries the setting across that process
    boundary. Measured both ways rather than assumed. This suite does launch child
    interpreters -- ``_run`` is exercised against ``sys.executable`` further down this
    file -- so the env var is the half that covers them.

    Drop it and the leg keeps its label, keeps its ``-O``, still costs a full suite, and
    quietly stops covering anything that runs in a subprocess. A leg reporting more scope
    than it has is the defect this repo is built around, so the binding is read from the
    call rather than grepped for anywhere in the file.
    """
    var = _leg_env_var("suite under -O")
    assert var is not None, (
        "the 'suite under -O' leg is not handed a named env mapping, so what it sets "
        "cannot be checked"
    )
    assert _env_overrides(var).get("PYTHONOPTIMIZE") == "1", (
        f"the -O leg is handed {var!r}, which never has PYTHONOPTIMIZE set to '1' -- "
        f"optimization stops at the pytest process and never reaches what it spawns"
    )
    assert var != _leg_env_var("suite"), (
        "the -O leg and the plain suite share one env mapping -- either the -O run is not "
        "optimized or the plain run is, and neither is what the two labels claim"
    )


def test_the_optimized_pass_runs_after_the_plain_suite():
    """Order is diagnostic, not cosmetic.

    A tree whose plain suite is already red says nothing about the -O pass -- the reason
    ci.yml gives for running the audit last. Reversed, the first red a developer reads is
    the harder one. Membership is asserted before ``index`` for the reason recorded in
    ``_verify_legs``: a missing leg here once surfaced as a ValueError, which reads as a
    broken test rather than as the finding it is.
    """
    labels = list(_verify_legs())
    for leg in ("suite", "suite under -O"):
        assert leg in labels, f"verify.py has no {leg!r} leg"
    assert labels.index("suite") < labels.index("suite under -O"), (
        "the -O pass runs before the plain suite; the plain failure is the one to read "
        "first"
    )


def _load_verify():
    """Import verify.py by path.

    Loaded under a private name so its ``__main__`` guard does not fire and run the
    entire gate as a side effect of importing it.
    """
    spec = importlib.util.spec_from_file_location("_verify_under_test", VERIFY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_coherence_rejects_the_stale_install_that_actually_happened():
    """0.2.1 metadata against a 0.3.0 tree: ``f23f345``, and again on 2026-08-18.

    Both times the environment reported the previous release's number from a tree that
    had already been bumped, and nothing failed.
    """
    verify = _load_verify()
    with pytest.raises(SystemExit) as excinfo:
        verify._check_installed_version("0.2.1", "0.3.0")
    message = str(excinfo.value)
    assert "0.2.1" in message and "0.3.0" in message, (
        "the refusal must name both versions -- 'version mismatch' on its own does not "
        "say which side is stale, and the fix depends on knowing that"
    )


def test_version_coherence_passes_when_metadata_matches_the_tree():
    _load_verify()._check_installed_version("0.3.0", "0.3.0")


def test_declared_version_reads_pyproject_not_installed_metadata():
    """The check must not consult the metadata it exists to catch.

    If ``_declared_version`` imported the package instead of reading the file, it would
    compare installed metadata against installed metadata, agree with itself, and never
    fire -- passing hardest in exactly the case it was written for.
    """
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert _load_verify()._declared_version() == declared


def test_the_version_check_is_reachable():
    """A check defined but never called is this file's whole subject matter."""
    tree = ast.parse(VERIFY.read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_check_installed_version" in called, (
        "_check_installed_version is defined but nothing calls it -- a gate nothing runs "
        "cannot fail"
    )


def test_the_summary_declares_what_it_did_not_check():
    """A bare ``VERIFY OK`` implies a scope this gate does not have.

    Asserted against the source text rather than the call graph because here the printed
    string *is* the deliverable: the defect is a human reading an unqualified success
    token and concluding CI will be green too.
    """
    source = VERIFY.read_text(encoding="utf-8")
    assert "NOT CHECKED" in source and "pip-audit" in source, (
        "verify.py must name the dependency audit as out of its scope; CI runs pip-audit "
        "as a separate step, so a green verify.py is not yet a green CI"
    )


def test_run_records_into_the_callers_list_not_shared_state():
    """The summary must describe *this* run, not every run in the process.

    The accumulator was module-level for one commit. A second in-process ``main()``
    appended to the first run's list, so the summary printed a leg twice -- the exact
    drift the accumulator was introduced to prevent, one layer up. Found in review
    rather than by a gate, which is why it is pinned here now.
    """
    verify = _load_verify()
    first: list[str] = []
    second: list[str] = []
    noop = [sys.executable, "-c", ""]
    verify._run("noop", noop, dict(os.environ), first)
    verify._run("noop", noop, dict(os.environ), second)
    assert first == ["noop"], f"first run recorded {first}"
    assert second == ["noop"], (
        f"second run recorded {second} -- legs are leaking across invocations, so the "
        f"summary no longer describes the run it is printed for"
    )


def test_a_failing_leg_is_not_recorded_as_checked():
    """A leg that exits non-zero must halt, and must not appear in the summary."""
    verify = _load_verify()
    ran: list[str] = []
    with pytest.raises(SystemExit):
        verify._run("boom", [sys.executable, "-c", "raise SystemExit(3)"], dict(os.environ), ran)
    assert ran == [], f"a failed leg was recorded as checked: {ran}"


def _fail_leg(verify, label: str) -> str:
    """Run a guaranteed-failing leg under ``label`` and return the refusal text."""
    ran: list[str] = []
    with pytest.raises(SystemExit) as excinfo:
        verify._run(label, [sys.executable, "-c", "raise SystemExit(1)"], dict(os.environ), ran)
    return str(excinfo.value)


def test_every_leg_carries_its_own_failure_guidance():
    """One template for five legs is true of all of them and diagnostic for none.

    Read from the call graph rather than from the hint table, so the direction of the
    check is right: adding a sixth leg without a hint fails here, while a hint for a leg
    that no longer exists does not. Reachability again -- the same reason
    ``_each_configured_gate_tool_is_a_verify_leg`` reads pyproject and not verify.py.
    """
    verify = _load_verify()
    for label in _verify_legs():
        assert label in verify._LEG_HINTS, (
            f"the {label!r} leg falls through to the shared 'VERIFY FAIL: {label} exited N' "
            f"template, which says what happened and nothing about what to do next"
        )


def test_the_optimized_leg_failure_sends_the_fix_to_src_not_to_the_test():
    """The one leg whose failure means something different from every other leg.

    ``suite under -O`` fails when application code enforces an invariant with a bare
    ``assert``, which -O strips. A contributor reading the shared template right after the
    plain ``suite`` leg passed concludes "a test regressed" and goes to tests/ -- the wrong
    file. This is that reasoning, which already lived in this file's own docstrings, moved
    to where it is read at the moment it matters.
    """
    message = _fail_leg(_load_verify(), "suite under -O")
    assert "assert" in message, "the -O refusal never names the bare assert it exists to catch"
    assert "raise" in message, "the -O refusal never names the replacement (an explicit raise)"
    assert "src/" in message, "the -O refusal does not say which tree the fix belongs in"


def test_a_leg_with_no_hint_still_refuses_cleanly():
    """The hint table is an addition, not a dependency -- an unknown label must still halt."""
    message = _fail_leg(_load_verify(), "boom")
    assert message.startswith("VERIFY FAIL: boom exited 1")


def test_legs_are_collapsible_in_actions_logs(capsys, monkeypatch):
    """ci.yml runs all five legs as ONE step, so the reader gets one flat log without these.

    Only the framing is asserted. What each child process prints is its own business and
    is deliberately left uncaptured; this pins that the markers wrap it.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    verify = _load_verify()
    ran: list[str] = []
    verify._run("noop", [sys.executable, "-c", ""], dict(os.environ), ran)
    out = capsys.readouterr().out
    assert "::group::noop" in out and "::endgroup::" in out
    assert out.index("::group::noop") < out.index("-- noop:"), (
        "the leg header prints outside its own group, so the collapsed group is unlabelled"
    )


def test_a_failing_leg_still_closes_its_log_group(capsys, monkeypatch):
    """An unclosed group swallows every later leg into the failing one's collapsed block."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _fail_leg(_load_verify(), "boom")
    out = capsys.readouterr().out
    assert out.count("::group::") == out.count("::endgroup::") == 1


def test_local_runs_print_no_actions_markers(capsys, monkeypatch):
    """Outside Actions the markers are noise, so the local run reads exactly as before."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    verify = _load_verify()
    ran: list[str] = []
    verify._run("noop", [sys.executable, "-c", ""], dict(os.environ), ran)
    out = capsys.readouterr().out
    assert "::group::" not in out and "::endgroup::" not in out
# A pip-audit report with one of every case that matters, in the real JSON shape:
# a clean dep, an advisory with no published fix, an advisory with one (emitted TWICE,
# as pip-audit really does), and a distribution it could not audit at all. Skipped
# entries carry only ``name`` and ``skip_reason`` -- no ``version`` key.
AUDIT_PAYLOAD = {
    "dependencies": [
        {"name": "pydantic", "version": "2.9.0", "vulns": []},
        {
            "name": "diskcache",
            "version": "5.6.3",
            "vulns": [{"id": "PYSEC-2026-2447", "fix_versions": []}],
        },
        {
            "name": "setuptools",
            "version": "78.1.0",
            "vulns": [
                {"id": "PYSEC-2026-3447", "fix_versions": ["83.0.0"]},
                {"id": "PYSEC-2026-3447", "fix_versions": ["83.0.0"]},
            ],
        },
        {
            "name": "torch",
            "skip_reason": "Dependency not found on PyPI and could not be audited: "
            "torch (2.13.0+cu130)",
        },
    ]
}


def test_an_advisory_with_a_published_fix_is_actionable():
    """Something to upgrade to means the gate can demand it."""
    fixable, _unfixable, _unauditable = _load_verify()._split_audit(AUDIT_PAYLOAD)
    assert fixable == [("setuptools", "78.1.0", "PYSEC-2026-3447", ["83.0.0"])]


def test_an_advisory_with_no_published_fix_is_reported_not_failed():
    """diskcache 5.6.3 / PYSEC-2026-2447 is real, and there is nothing to upgrade to.

    Failing on it would make the gate permanently red with no move available on any box
    carrying ``[synth]``, which is how people learn to skip gates. It is a third
    category, not a pass and not a failure.
    """
    fixable, unfixable, _ = _load_verify()._split_audit(AUDIT_PAYLOAD)
    assert unfixable == [("diskcache", "5.6.3", "PYSEC-2026-2447", [])]
    assert not any(entry[0] == "diskcache" for entry in fixable), (
        "an advisory with no published fix must never reach the failing category"
    )


def test_a_distribution_that_could_not_be_audited_is_surfaced():
    """The one that would otherwise read as clean coverage.

    On a box with ``[image]``, torch is a local ``+cu130`` build that is not on PyPI, so
    pip-audit cannot check the largest dependency in the tree. Reporting nothing here
    would be "could not check" printed as "checked clean" -- this repo's whole subject.
    """
    _fixable, _unfixable, unauditable = _load_verify()._split_audit(AUDIT_PAYLOAD)
    assert len(unauditable) == 1
    name, reason = unauditable[0]
    assert name == "torch"
    assert "could not be audited" in reason


def test_duplicate_advisory_rows_are_counted_once():
    """pip-audit emits the same advisory twice; the count must not inherit that."""
    fixable, _, _ = _load_verify()._split_audit(AUDIT_PAYLOAD)
    assert len(fixable) == 1, f"duplicate rows were not deduped: {fixable}"


def test_an_empty_report_is_not_mistaken_for_a_finding():
    assert _load_verify()._split_audit({"dependencies": []}) == ([], [], [])


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("dspy-ai>=2.5", "dspy-ai"),
        ("ruff>=0.6,<0.17", "ruff"),
        ("torch>=2.4", "torch"),
        # Mirrors what the [image] extra actually declares, comma and all. It was
        # `pillow>=10.0` here because that is what pyproject said at the time; the extra
        # has since gained an upper bound, and `_installed_extras()` feeds this parser the
        # real string. A row that quietly stops matching the declaration it was copied from
        # is coverage of a requirement nobody writes.
        ("pillow>=10.0,<14", "pillow"),
        ("numpy", "numpy"),
    ],
)
def test_requirement_names_parse(requirement: str, expected: str):
    assert _load_verify()._req_name(requirement) == expected


def test_installed_extras_are_named_from_pyproject():
    """The audit's verdict depends on which extras are installed, so it reports them.

    ``[synth]`` brings the no-published-fix advisory; ``[dev]`` alone does not, and CI
    installs only ``[dev]``. Two honest runs on different boxes disagree unless each
    says what it measured -- the same trap as reading one ruff family under ``--select``
    as though it were the gate.
    """
    declared = set(
        tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
        .get("optional-dependencies", {})
    )
    assert set(_load_verify()._installed_extras()) <= declared


def test_the_audit_is_opt_in_and_reachable():
    """Off by default keeps the gate hermetic and a function of the tree; and a leg
    nothing calls cannot fail."""
    source = VERIFY.read_text(encoding="utf-8")
    assert '"--audit"' in source and 'action="store_true"' in source
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_audit" in called, "_audit is defined but nothing calls it"


def test_the_gate_checks_the_file_that_defines_the_gate():
    """verify.py was the one file its own static legs did not cover.

    lint ran ``src tests`` and typecheck ran ``src``, so the script that decides what
    "verified" means was exempt from the checks it runs on everything else. A
    pre-existing PLW1510 sat in ``_run`` unreported because of it. This is the same
    shape as ``[tool.ruff]`` with no ``select``, as a bare ``VERIFY OK``, and as mypy
    aborting on a numpy stub while still reading as a configured gate.
    """
    legs = _verify_legs()
    assert "verify.py" in legs["lint"], (
        "the lint leg does not lint verify.py -- the gate is exempting the file that "
        "defines the gate"
    )
    assert "verify.py" in legs["typecheck"], (
        "the typecheck leg does not check verify.py"
    )


# --- the wheel smoke: the one leg that runs against a non-editable install ---------------
#
# The ``build`` leg built a wheel into a scratch directory and then deleted that directory,
# artifact included, before ``VERIFY OK`` printed. Nothing installed it, imported from it, or
# ran the console script it declares -- while every other install path in this repo is
# ``pip install -e``, which resolves pcraft out of ``src/`` and never exercises
# ``[tool.hatch.build.targets.wheel]``. 18 tracked non-Python files that the runtime opens
# ride on that rule, and a rule that dropped one would still build, still install and still
# import cleanly.
#
# HONESTY NOTE, because these tests are cheap and the leg they pin is not: nothing below
# builds a wheel, creates a venv, or installs anything. They pin that the leg is WIRED --
# read from verify.py's call graph, the same reachability argument as everything above -- and
# that the smoke script's own decision functions behave. Whether the leg passes end to end is
# settled by running verify.py, not by this file.


def _load_wheel_smoke():
    """Import scripts/wheel_smoke.py by path, under a private name.

    Same reason as ``_load_verify``: the ``__main__`` guard must not fire. That the import is
    side-effect-free at all is part of what these tests hold -- the script does nothing at
    module scope, unlike the sibling in scripts/ that used to sweep the tree on import.
    """
    spec = importlib.util.spec_from_file_location("_wheel_smoke_under_test", WHEEL_SMOKE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _names_bound_to(func: str) -> set[str]:
    """Variable names assigned the result of ``func(...)`` in verify.py.

    The call-graph counterpart to ``_leg_env_var``: that one says WHICH mapping a leg is
    handed, this one says where that mapping came from. Neither is enough alone -- a leg
    handed a correctly-named variable that was never built by the right function would
    satisfy the first and mean nothing.
    """
    out: set[str] = set()
    for node in ast.walk(ast.parse(VERIFY.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target, value = node.targets[0], node.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Call)):
            continue
        if isinstance(value.func, ast.Name) and value.func.id == func:
            out.add(target.id)
    return out


def test_the_built_wheel_is_installed_and_exercised_somewhere():
    """A wheel nobody installs is a wheel nobody has checked."""
    labels = list(_verify_legs())
    assert "wheel smoke" in labels, (
        "verify.py has no 'wheel smoke' leg -- the build leg produces a wheel and deletes it "
        "unopened, so no gate in this repo installs the artifact it publishes, imports from "
        "it, or runs the console script it declares"
    )
    assert "build" in labels, "verify.py has no 'build' leg"
    assert labels.index("build") < labels.index("wheel smoke"), (
        "the wheel smoke runs before the build leg that produces the wheel it smokes"
    )


def test_the_wheel_smoke_legs_do_not_inherit_pythonpath():
    """The one line the whole leg rests on.

    Without ``--installed``, main() puts ``<root>/src`` on PYTHONPATH for every other leg,
    and PYTHONPATH is searched BEFORE a venv's own site-packages. Inherited here, the smoke
    would import pcraft from the source tree, pass every check, and prove nothing about the
    wheel it had just installed -- a leg reporting more scope than it has, inside the leg
    written to stop exactly that.
    """
    verify = _load_verify()
    stripped = verify._wheel_smoke_env({"PYTHONPATH": "src", "PATH": "/usr/bin", "CI": "1"})
    assert "PYTHONPATH" not in stripped, "the smoke env still carries PYTHONPATH"
    assert stripped == {"PATH": "/usr/bin", "CI": "1"}, (
        f"the smoke env dropped more than PYTHONPATH: {stripped}. The child still needs PATH "
        f"to find its own interpreter."
    )
    bound = _names_bound_to("_wheel_smoke_env")
    assert bound, "nothing in verify.py is assigned the result of _wheel_smoke_env(...)"
    for leg in ("wheel smoke venv", "wheel smoke install", "wheel smoke"):
        assert _leg_env_var(leg) in bound, (
            f"the {leg!r} leg is handed {_leg_env_var(leg)!r}, which is not the mapping "
            f"_wheel_smoke_env built -- so it can still resolve pcraft out of src/"
        )
    assert _leg_env_var("suite") not in bound, (
        "the suite leg is handed the PYTHONPATH-stripped mapping; it must keep PYTHONPATH or "
        "it stops testing a checkout at all"
    )


def test_the_venv_interpreter_is_looked_up_inside_the_venv():
    """Both layouts are real here: Scripts/ on the dev boxes, bin/ on both CI legs."""
    verify = _load_verify()
    got = verify._venv_python(Path("scratch") / "smoke-venv")
    assert got.parent.parent.name == "smoke-venv", f"{got} is not inside the venv"
    assert got.stem == "python"
    assert got.parent.name == ("Scripts" if os.name == "nt" else "bin"), (
        f"{got} is not where a stdlib venv puts its interpreter on this platform"
    )


def test_the_wheel_smoke_failures_send_the_fix_to_the_packaging_rule():
    """These legs fail in a different KIND of way, and the shared template would not say so.

    A dropped data file is not a code defect and not a test regression: it is one line of
    ``[tool.hatch.build.targets.wheel]``. And an install leg that runs ``--no-index`` cannot
    fail for network reasons, which is the first thing a reader assumes about a failing pip.
    """
    verify = _load_verify()
    smoke = _fail_leg(verify, "wheel smoke")
    assert "[tool.hatch.build.targets.wheel]" in smoke, (
        "the wheel-smoke refusal does not name the packaging rule its failure implicates"
    )
    install = _fail_leg(verify, "wheel smoke install")
    assert "--no-index" in install, (
        "the install refusal does not say the leg is offline, so the first guess a reader "
        "makes is a network failure it cannot be"
    )


def test_the_smoke_script_gates_with_refusals_not_bare_asserts():
    """``assert`` is stripped under -O, and nothing runs this script under -O to notice.

    verify.py devotes an entire leg to this shape inside the suite, and its refusal text
    sends the fix to src/. A gate script that checked with ``assert`` would be the same
    defect one directory over, with no leg watching it.
    """
    asserts = [
        node.lineno
        for node in ast.walk(ast.parse(WHEEL_SMOKE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assert)
    ]
    assert not asserts, (
        f"scripts/wheel_smoke.py refuses with a bare assert at line(s) {asserts} -- stripped "
        f"under -O, so the check disappears silently in an optimized interpreter"
    )


def test_only_tracked_non_python_files_are_expected_in_the_wheel():
    """The manifest comes from git, and it is package-relative.

    ``.py`` is the only extension dropped, deliberately: a ``.pyi`` or a ``.txt`` added inside
    the package is covered the day it lands rather than the day someone remembers to list it.
    """
    smoke = _load_wheel_smoke()
    listing = (
        "src/pcraft/__init__.py\n"
        "src/pcraft/py.typed\n"
        "src/pcraft/domains/image/rules/encoder_craft.md\n"
        "src/pcraft/domains/image/subdomains/sprite/poses/turnaround/back.openpose.png\n"
        "tests/test_verify_legs.py\n"
        "README.md\n"
    )
    assert smoke._tracked_data_files(listing) == [
        "domains/image/rules/encoder_craft.md",
        "domains/image/subdomains/sprite/poses/turnaround/back.openpose.png",
        "py.typed",
    ]


def test_this_tree_really_does_ship_data_the_manifest_check_would_notice():
    """A check that matched nothing would pass forever while proving nothing.

    Measured at 18 tracked non-Python files under src/pcraft when this was written; the floor
    is deliberately far below that, because the assertion is "this package ships data", not a
    file count nobody agreed to hold.
    """
    smoke = _load_wheel_smoke()
    listing = smoke._git_tracked(ROOT)
    if listing is None:
        pytest.skip("git cannot list this tree -- the leg reports that rather than failing")
    shipped = smoke._tracked_data_files(listing)
    assert len(shipped) >= 10, (
        f"only {len(shipped)} tracked non-Python files under src/pcraft: {shipped}. Either "
        f"the package stopped shipping data, or this check is reading the wrong prefix and "
        f"has been passing on an empty set."
    )


def test_a_data_file_missing_from_the_install_is_named(tmp_path):
    """The exact failure the leg exists for: the wheel imports, and one data file is gone."""
    smoke = _load_wheel_smoke()
    package_dir = tmp_path / "pcraft"
    (package_dir / "rules").mkdir(parents=True)
    (package_dir / "rules" / "encoder_craft.md").write_text("x", encoding="utf-8")
    expected = ["rules/encoder_craft.md", "thresholds/sprite.calibration.json"]
    assert smoke._missing_from_install(expected, package_dir) == [
        "thresholds/sprite.calibration.json"
    ]
    assert smoke._missing_from_install(["rules/encoder_craft.md"], package_dir) == []


def test_git_being_unable_to_answer_is_not_read_as_an_empty_manifest(monkeypatch, tmp_path):
    """None, not ``[]`` -- the same distinction mutate_predicates.py holds for a dirty tree.

    ``""`` is a real answer meaning "nothing is tracked there". A missing git, or a tree that
    is not a checkout (an unpacked sdist, a vendored copy), makes the question unanswerable,
    and a manifest of zero files would then be "could not check" wearing "checked clean" --
    with every shipped data file unexamined and the leg still green.
    """
    smoke = _load_wheel_smoke()

    def no_git(*_args, **_kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(smoke.subprocess, "run", no_git)
    assert smoke._git_tracked(tmp_path) is None

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not a git repository"
        ),
    )
    assert smoke._git_tracked(tmp_path) is None


# --- release.yml's refusals -------------------------------------------------------------
#
# HONESTY NOTE, because a test over a workflow file can read far stronger than it is.
# Everything below reads release.yml as TEXT. It does not parse the YAML (no parser ships
# in the [dev] extra), it does not execute the workflow, it does not reach GitHub, and it
# cannot show that the step runs, that the shell substitutes what these messages assume, or
# that any of this was ever printed on a real runner. Static validation only, and no run of
# release.yml was performed for this change.
#
# What it does pin is the thing that was actually wrong: two of the three refusals in the
# version-check step were bare value dumps. That step fires inside the one workflow holding
# live OIDC publish credentials, typically after a human approval has already been spent,
# so the message an operator reads at that moment is the whole remedy they get.
#
# THE SAME NOTE APPLIES, DOUBLY, TO THE DRY-RUN TESTS AT THE END OF THIS SECTION. They read
# the input's default, the two publish jobs' guards and the announcement step as text. No
# dispatch has been run: nothing here shows that GitHub honours the guard, that a skipped job
# really leaves the `release` environment un-entered, or that the step summary renders. The
# first real `workflow_dispatch` is what settles those, and release.yml's own header block is
# the recipe for firing it safely. What these tests do hold is that the safe default and the
# two guards cannot be quietly deleted -- which matters because the failure they prevent is
# invisible by construction: a run left `waiting` on an approval nobody is looking at, which
# is the state this workflow actually sat in for 302 hours.

_ERROR_LINE = re.compile(r'::error::(.+?)"')
_REMEDY_MIN = 40


def _release_refusals() -> list[str]:
    """Every ``::error::`` message in release.yml, as text."""
    return _ERROR_LINE.findall(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _remedy(msg: str) -> str:
    """The part of a refusal that says what to DO, split off the part that says what broke.

    Two conventions are live in this file and both are fine: a `` -- `` clause (the npm and
    tag checks) and a second sentence (the ref-type check). What is not fine is a bare
    mismatch with neither, which is what two of these three were.
    """
    _head, sep, tail = msg.partition(" -- ")
    if sep:
        return tail.strip()
    _first, dot, rest = msg.partition(". ")
    return rest.strip() if dot else ""


def test_every_release_refusal_spells_out_the_next_move():
    """A value dump is not guidance, and here it is the last guidance anyone gets."""
    refusals = _release_refusals()
    assert len(refusals) >= 3, (
        f"expected the version-check step's three refusals, found {len(refusals)} -- the "
        f"step's shape changed and this test is no longer reading it"
    )
    for msg in refusals:
        remedy = _remedy(msg)
        assert len(remedy) >= _REMEDY_MIN, (
            f"this refusal states a mismatch and stops there: {msg!r}. Its sibling three "
            f"lines away names the exact corrective action; say what to do next here too."
        )


def test_the_tag_mismatch_refusal_warns_against_moving_the_tag():
    """The sharpest of the three, because the obvious corrective action is the wrong one.

    A GitHub Release may already point at this tag, so retagging in place silently changes
    what that release refers to. This is the case the step's own 25-line comment block
    spends its length explaining is still reachable -- 'a tag cut before a version-bump
    commit, or a hotfix tag based on an older commit'.
    """
    tag_refusals = [m for m in _release_refusals() if m.startswith("tag ")]
    assert len(tag_refusals) == 1, f"expected one tag-mismatch refusal, found {tag_refusals}"
    lowered = tag_refusals[0].lower()
    assert "force-push" in lowered or "force push" in lowered, (
        "the refusal does not warn against the move an operator reaches for first"
    )
    assert "re-tag" in lowered or "cut a new" in lowered, (
        "the refusal warns against the wrong move without naming a right one"
    )


def test_the_manifest_mismatch_refusal_names_the_cheap_fix():
    """pyproject vs npm is the recoverable one, and saying so is most of the guidance."""
    npm_refusals = [m for m in _release_refusals() if m.startswith("pyproject ")]
    assert len(npm_refusals) == 1, f"expected one manifest refusal, found {npm_refusals}"
    lowered = npm_refusals[0].lower()
    assert "bump" in lowered, "the refusal does not name the fix (bump the lagging file)"
    assert "tag" in lowered, "the refusal does not say a new tag is needed after the bump"


def _job_block(name: str) -> str:
    """The text of one top-level job in release.yml.

    Sliced on the two-space-indented job keys rather than parsed, for the reason the note at
    the top of this section gives: no YAML parser ships in the [dev] extra. Job names are the
    only keys at that indent -- everything inside a job sits at four or more.
    """
    source = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    start = source.index(f"\n  {name}:\n")
    rest = source[start + 1:]
    following = re.search(r"\n  [a-z][a-z0-9_-]*:\n", rest)
    return rest[: following.start()] if following else rest


def test_a_dispatch_defaults_to_the_run_that_cannot_publish():
    """The harmless door is the one that opens by itself.

    `workflow_dispatch` exists so a release whose publish step failed can be re-run without
    cutting a new tag, and it is also the only way to exercise this workflow deliberately.
    Those two uses want opposite defaults, and the safe one wins: a dispatch fired by someone
    who did not read the header runs every gate and reaches no registry. Publishing from a
    dispatch is then a deliberate act -- unchecking a box -- rather than the default.
    """
    source = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "dry_run:" in source, (
        "release.yml has no dry_run input, so there is no way to prove the gate without "
        "arming the environment's approval and leaving a run waiting on a human"
    )
    block = source.split("dry_run:", 1)[1].split("\njobs:", 1)[0]
    assert "type: boolean" in block, "the dry_run input is not declared as a boolean"
    assert "default: true" in block, (
        "dry_run does not default to true -- an unread dispatch would then arm the release "
        "environment, which is the expensive direction to be wrong in"
    )


@pytest.mark.parametrize("job", ["pypi", "npm"])
def test_a_dry_run_never_enters_the_release_environment(job: str):
    """Skipping the job is what keeps a dry run from leaving an approval armed.

    Not merely "does not publish": entering the environment CREATES a pending deployment and
    asks a reviewer. That is the state a run sat in here for 302 hours, against a tag, built
    from a workflow revision no longer on main.
    """
    block = _job_block(job)
    assert "environment: release" in block, (
        f"the {job} job no longer declares `environment: release` -- the reviewer rule and "
        f"the `tag v*` branch policy hang off that declaration"
    )
    assert "inputs.dry_run" in block, (
        f"the {job} job has no dry-run guard, so a dispatch meant only to prove the gate "
        f"would arm the approval and leave a run waiting"
    )


@pytest.mark.parametrize("job", ["pypi", "npm"])
def test_the_publish_path_does_not_hinge_on_how_an_absent_input_coerces(job: str):
    """A `release: published` event carries no inputs at all.

    Written as "not a dry-run dispatch" rather than as a bare `!inputs.dry_run`, so the
    release path reads as unconditional instead of depending on a null evaluating falsy in a
    context that is empty for that event. A publish path is the wrong place to be clever.
    """
    assert "github.event_name != 'workflow_dispatch'" in _job_block(job), (
        f"the {job} job's guard tests only the input, so whether a real release publishes "
        f"depends on how an absent input coerces"
    )


def test_the_dry_run_says_so_where_a_human_will_actually_see_it():
    """A skipped job is quiet: GitHub greys it out and gives no reason.

    The value of a dry run is an operator knowing the gate was proven AND that no registry
    was reached. Silence there reads as "it published", which is the misreading that costs
    the most.
    """
    source = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "::notice::DRY RUN" in source, (
        "a dry run leaves no annotation on the run, so the skipped publish jobs are the only "
        "signal and they say nothing"
    )
    assert "GITHUB_STEP_SUMMARY" in source, (
        "the dry run writes nothing to the step summary -- the page a human opens -- so the "
        "outcome lives only in a log someone has to go find"
    )


# --- scripts/mutate_predicates.py, and consent ------------------------------------------
#
# This script rewrites tracked files under src/pcraft/core/ in place. That is its job and
# it stays -- a mutant has to be real for the suite to have any chance of catching it. What
# it lacked was consent: it read no argv at all, so `--help` was accepted, ignored, and
# followed by the full sweep. NOTHING BELOW EVER PASSES `--run`. The refusal paths and the
# dirty-tree parser are exercised directly; the sweep itself is never started from a test.


def _load_mutate():
    """Import scripts/mutate_predicates.py by path, under a private name.

    Same reason ``_load_verify`` does it, with higher stakes: letting the ``__main__``
    guard fire used to mean twenty in-place rewrites of tracked source files and twenty
    full suite runs, as a side effect of an import.
    """
    spec = importlib.util.spec_from_file_location("_mutate_under_test", MUTATE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _target_snapshot(mutate) -> dict[str, str]:
    """Current text of every file the sweep would rewrite."""
    return {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in mutate._target_paths()}


def test_a_bare_invocation_describes_instead_of_sweeping(capsys):
    """The defect exactly: running this with no arguments WAS the sweep.

    The files are compared before and after rather than trusting the return code, because
    the claim being made is 'this touched nothing', not 'this exited non-zero'.
    """
    mutate = _load_mutate()
    before = _target_snapshot(mutate)
    rc = mutate.main([])
    assert rc != 0, "a bare invocation reports success without having done anything"
    assert _target_snapshot(mutate) == before, "the refusal path modified a tracked file"
    printed = capsys.readouterr()
    text = printed.out + printed.err
    assert "--run" in text, "the refusal does not name the flag that would have run it"
    assert "git checkout" in text, "the banner does not name the recovery command"


def test_listing_the_mutants_touches_nothing(capsys):
    """A way to read the table without the tree ever being wrong for a second."""
    mutate = _load_mutate()
    before = _target_snapshot(mutate)
    assert mutate.main(["--list"]) == 0
    assert _target_snapshot(mutate) == before, "--list modified a tracked file"
    assert "CQ58 drop first" in capsys.readouterr().out


def _detached_copy(tmp_path: Path) -> Path:
    """A copy of the script whose ``ROOT`` is a temp dir instead of this repo.

    The script derives ``ROOT`` from ``Path(__file__).resolve().parents[1]``, so a copy at
    ``<tmp>/scripts/mutate_predicates.py`` believes the repo is ``<tmp>`` -- which has no
    ``src/pcraft/`` in it.

    This is not fussiness. The two tests below drive the real command line as a
    subprocess, and the regression they exist to catch is 'the argv gate was removed'. Run
    against the repo, a test for that regression would DISCOVER it by launching the sweep:
    twenty in-place rewrites of tracked source files, from inside a test run, with a
    pytest timeout as the likeliest way it ends -- which is precisely the uncatchable
    interrupt the script's docstring warns about. Measured, not theorised: that is exactly
    what happened while this test was being written. Detached, the same regression makes
    these tests fail in a few seconds and touches nothing.
    """
    dest = tmp_path / "scripts"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / MUTATE.name
    target.write_text(MUTATE.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_help_prints_usage_instead_of_starting_a_sweep(tmp_path):
    """``--help`` used to be swallowed by a script that never read argv.

    Driven as a real subprocess because the claim is about the real command line -- what a
    contributor types, and what the docstring's own usage lines promise.
    """
    script = _detached_copy(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path, capture_output=True, text=True, check=False, timeout=120,
    )
    assert proc.returncode == 0, f"--help exited {proc.returncode}: {proc.stderr[:400]}"
    for expected in ("usage:", "--run", "--list", "--allow-dirty", "git checkout -- src/pcraft/core"):
        assert expected in proc.stdout, f"--help never mentions {expected!r}"


def test_an_unknown_flag_is_refused_rather_than_ignored(tmp_path):
    """Proof that argv is read at all: the old script ignored every argument equally."""
    script = _detached_copy(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(script), "--sweep-everything-now"],
        cwd=tmp_path, capture_output=True, text=True, check=False, timeout=120,
    )
    assert proc.returncode == 2
    assert "unrecognized arguments" in proc.stderr


def test_a_dirty_target_is_seen_before_the_sweep_starts():
    """Porcelain parsing, isolated from git so the refusal can be exercised at all."""
    mutate = _load_mutate()
    targets = set(mutate._target_paths())
    victim = min(targets)
    porcelain = f" M {victim}\n?? scratch/notes.txt\n M some/other/file.py\n"
    assert mutate._dirty_from_porcelain(porcelain, targets) == [victim]


def test_a_clean_tree_reports_no_dirty_targets():
    mutate = _load_mutate()
    assert mutate._dirty_from_porcelain("", set(mutate._target_paths())) == []


def test_git_being_unable_to_answer_is_not_read_as_a_clean_tree(monkeypatch):
    """None, not [] -- the distinction this whole codebase is built around.

    A missing git or a non-repo checkout makes the question unanswerable. Returning an
    empty list there would hand the caller 'could not check' wearing 'checked clean'.
    """
    mutate = _load_mutate()
    monkeypatch.setattr(mutate, "_git_porcelain", lambda _paths: None)
    assert mutate._dirty_targets() is None


def test_the_sweep_refuses_to_start_on_a_dirty_target(capsys, monkeypatch):
    """The restore writes back the text read at start, so a dirty target loses its edits."""
    mutate = _load_mutate()
    victim = min(mutate._target_paths())
    monkeypatch.setattr(mutate, "_git_porcelain", lambda _paths: f" M {victim}\n")
    assert mutate._preflight(allow_dirty=False) == 2
    err = capsys.readouterr().err
    assert victim in err, "the refusal does not name which file is dirty"
    assert "git checkout" in err, "the refusal does not name the recovery command"
    assert mutate._preflight(allow_dirty=True) == 0, "--allow-dirty does not override"
