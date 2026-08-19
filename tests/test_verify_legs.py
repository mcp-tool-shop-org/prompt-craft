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
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "verify.py"
PYPROJECT = ROOT / "pyproject.toml"

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
        ("pillow>=10.0", "pillow"),
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
