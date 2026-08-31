---
title: Binding real canon
description: From a character reference sheet to a faction+character contract pair the gate can enforce — which claims become atoms, and why.
---

The shipped example is a generic invention, and the honest-status table says so: binding
**real** canon is a deliberate, human decision. This page walks that decision once, end to
end, so the first real character you bind is a workflow and not an archaeology dig through
the example.

The input is whatever your studio already has: a reference sheet, a costume plate, a lore
paragraph with the character's non-negotiables. The output is a **faction + character
contract pair** the gate can enforce on pixels.

## 1. Split the sheet into claims

Read the reference material and write down every visual fact a reviewer would reject the
art for missing. One fact per line. Concrete nouns, no vibes:

- grey-ash tabard worn over the torso
- white triple-bar sigil on the tabard
- ash-grey / bone-white / blood-red palette
- no gold trim anywhere (house rule)
- bone-spike bracer on the right forearm

If a line cannot be checked by looking at one picture, it is not a claim — it is lore.
Lore stays in your canon docs; only **depictable** facts become atoms.

## 2. Decide what is faction and what is character

Anything true of *every* member goes in the faction contract; the character contract
`extends` it and adds the specifics. Inheritance is **fail-closed**: a character may
*raise* a faction requirement, never relax or silently drop one — so put the
non-negotiables at the faction level and let characters only tighten.

From the list above: the palette and the no-gold rule are faction facts. The tabard, the
sigil and the bracer belong to the character.

## 3. Give each claim its checker

Every atom carries a `check_type` — which gate tier verifies it:

| the claim is about | check_type | why |
|---|---|---|
| a colour scheme | `palette` | deterministic, no model, cheapest of all |
| a thing being present | `siglip2` | cheap presence screen, good first pass |
| composition, wearing, relations | `vqa` | the compositional tier; costs more, sees more |

One install note before you rely on the model tiers: `palette` works from a base install,
but `siglip2` and `vqa` need packages **no pip extra declares** — `t2v-metrics` for the VQA
family, `ai-eyes-mcp` for the screen. `pcraft doctor` reports both under "model tier", and
a gate missing them says SKIPPED rather than silently passing — so wire the atoms now and
trust the census to tell you when they can actually score.

Severity is the andon cord: `required` atoms block the bind, `optional` atoms warn. Give
`depends_on` edges where a claim is meaningless without its parent — the sigil depends on
the tabard, because there is no point scoring a sigil on a garment the gate just decided
is absent. (A dangling or cyclic edge is refused at `pcraft validate` with a named code,
so wire them freely and let the loader check your work.)

`must_not` entries are checked as **absence on the pixels** — the no-gold rule goes here,
not into a negative prompt.

## 4. Scaffold, then edit

`pcraft new` emits a loadable skeleton for each half of the pair, so authoring starts from
a valid file instead of a copied example. Scaffold the faction, then the character that
extends it, then replace the starter atoms with your claims from steps 1–3.

The shipped reference pair (`faction:ashen-pact-cloud` + `char:ashen-reaver-cloud`) is the
worked answer sheet: keep it open beside your own pair. Note it really is a *pair* — an
identity plate's `method` is inherited like everything else, so the faction half carries
the choices every member shares.

## 5. Validate, gate, bind

```bash
pcraft validate                       # resolve + compile the DAG; refusals name the line
pcraft gate render-01.png             # score one candidate against the contract
pcraft bind                           # run the loop; a bound receipt is your provenance
```

Read the exit code, not the prose: `2` means a required atom failed, `3` means the human
band, `4` means the gate could not run — and could-not-check is never checked-clean.

## 6. Calibrate before you trust the bands

The shipped threshold table says of itself that it is a generic seed. Before real canon
binds at volume, label a holdout (~50–100 sprites per check type: `present` / `absent` /
`borderline` per atom) and run the calibration workflow:

```bash
pcraft calibrate holdout.jsonl --out sprite.cal.v2.json
pcraft regrade --table sprite.cal.v2.json --records-dir records/
```

`calibrate` fits bands from your labels and emits a **new** table — it never silently
adopts one. `regrade` answers the question that matters before adopting it: *what would
this table have decided about everything already bound?* Receipts stamp both the table
version and a hash of its values, so a retune can never silently rewrite history.

## What this page deliberately does not cover

Wiring the identity sub-gate (it stays unwired until a holdout justifies its thresholds),
prompt-engineering the synthesizer (the contract is the prompt's source of truth), and
generating the pictures themselves — this page is about making the *checking* real,
because that is the half a pipeline forgets.
