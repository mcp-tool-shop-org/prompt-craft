# prompt-craft

Follow **`grok.md`**, then **`ADVISOR.md`**, then **`HANDOFF.md`**.

This tree is **multi-seat** (2026-08-18): Advisor = Grok, Executor =
Claude. Advisor-owns-README is **on**.

Load-bearing:

- Executor: code + tests + CHANGELOG Unreleased.
- Advisor: README / handbook / landing / PyPI / npm / translations.
- Tests ride the change-set. Quote counts only after a run.
- Version 0.2.1. `identity_subgate.py` stays unwired.
- Cloud Comfy default. Local 5090 only if asked. The greened live
  generate already ran.
- GEPA offline, never on the per-asset hot path.

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest --basetemp=E:\AI\prompt-craft\.pytest-tmp -q
```
