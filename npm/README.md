<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prompt-craft/main/docs/assets/logo.png" alt="prompt-craft" width="820">
</p>

# @mcptoolshop/prompt-crafter

**Say what the picture must contain. Check that it does. Refuse when it doesn't.**

A generative image pipeline will happily hand you a hero with the wrong face, the wrong palette
and none of the faction's markings — and report success, because nothing looked. prompt-craft
replaces the opaque prose prompt with a **typed contract of depictable claims**, uses that same
list twice — once to write the prompt, once to check the pixels — and **blocks the asset when a
required claim is not there**.

## This package is a launcher, not a port

The measured pieces are Python: the contract schema, the fail-closed loader, the gate's tiering
and its exit contract. Re-implementing any of them in JavaScript would create a second copy of a
threshold, and a threshold with two copies is a threshold that drifts — precisely the failure
this project exists to catch.

So this package installs a `pcraft` command and forwards it, verbatim, to the Python that holds
the truth. **It will not install Python for you, and it will not `pip install` anything behind
your back.** When the toolkit is missing it says so, prints the one command that fixes it, and
exits non-zero.

```bash
npm install -g @mcptoolshop/prompt-crafter
pip install prompt-crafter          # the toolkit itself
pcraft --help
```

Point it at a specific interpreter with `PCRAFT_PYTHON` if you keep several.

## The exit code is the point

The gate distinguishes four outcomes, and this launcher inherits the child's code unchanged so
the distinction survives the trip through Node:

| exit | meaning |
|---|---|
| `0` | the gate ran and every required atom passed |
| `1` | bad arguments or a malformed contract |
| `2` | it ran, and a required atom **failed** |
| `3` | it ran, and the result is **unconfirmed** — the human band |
| `4` | it **could not run** |

The `2` / `4` split is the whole design. **"I could not check" and "I checked and it is bad" are
different facts.** Merging them is why browsers soft-fail certificate revocation, and why
monitoring standards have carried a distinct *unknown* verdict since the 1990s. If you script
around this tool, branch on `4` separately.

## Honest limits

The Python toolkit's **local** GPU `generate()` **ran** on the 5090 this was developed
on (2026-08-18, seed `169405236028824`, OpenPose + identity plate). The frame is
orcish; grip, sigil, and bracer did not land. The core is GPU-free, deterministic,
and covered by **394 passing tests** (counted 2026-08-18). SDXL pose-lock, IP-Adapter,
LoRA, InstantID, and regional inpaint are wired in code and tested with fakes; Flux
still refuses those refs. A Cloud recipe (`pcraft recipe`) has been submitted live.
A live GEPA compile ran on local Ollama `hermes3:8b` (not 600B) and pinned
`sprite.synth.v1-gepa.json`. The identity sub-gate is not wired. The
project's own front door says so.

v1.0.0 covers interfaces, not pictures: the CLI surface, the exit-code contract, and
both on-disk formats are semver-covered (`STABILITY.md` in the repo names each one and
what is excluded). The capability gaps above stay disclosed and close in minor releases.

---

**[Documentation and handbook →](https://mcp-tool-shop-org.github.io/prompt-craft/)**
· [Source](https://github.com/mcp-tool-shop-org/prompt-craft)
· [PyPI](https://pypi.org/project/prompt-crafter/)

MIT
