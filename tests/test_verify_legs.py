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
