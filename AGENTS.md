# prompt-craft

Follow **`grok.md`**, then **`ADVISOR.md`**, then **`HANDOFF.md`**.

This tree is **multi-seat** (2026-08-18): Advisor = **Claude**, Executor =
a separate seat. Advisor-owns-README is **on**.

Load-bearing:

- Executor: code + tests + CHANGELOG Unreleased.
- Advisor: README / handbook / landing / PyPI / npm / translations.
- Tests ride the change-set. Quote counts only after a run.
- Version **0.3.0** (shipped 2026-08-18). `identity_subgate.py` stays unwired.
- The lint rule set is **declared** in `[tool.ruff.lint]`, not inherited. Every
  `ignore` names its reason. Do not re-open those rejections.
- Cloud Comfy default. Local 5090 only if asked. The greened live generate
  already ran.
- GEPA offline, never on the per-asset hot path.

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
```

Do not share a fixed `--basetemp` across seats. `python verify.py` is the blessed
full gate (fresh mkdtemp) — but it does **not** run the dependency audit, so a
green `verify.py` is not yet a green CI. Verify in a CI-equivalent venv on both
legs (3.11 and 3.13) before pushing anything a release gate will judge; this box
disagrees with CI on ruff and mypy versions. See `grok.md`.
