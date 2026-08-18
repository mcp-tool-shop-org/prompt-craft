# prompt-craft

Follow **`grok.md`** in this directory. It is the operating file for a
solo Grok seat on this repo. Next session: read **`HANDOFF.md`**.

Load-bearing:

- You own README / handbook / landing in the same sitting as the code.
  Advisor-owns-README is multi-seat only.
- Tests ride the change-set. Quote counts only after a run.
- Version 0.2.1. `identity_subgate.py` stays unwired.
- Cloud Comfy default. Local 5090 only if asked.
- GEPA offline, never on the per-asset hot path.

```
cd E:\AI\prompt-craft
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest --basetemp=E:\AI\prompt-craft\.pytest-tmp -q
```
