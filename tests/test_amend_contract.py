"""Regression tests for the wave-2 core-contract amend (swarm-1787033129-beab).

Three CRITICAL findings, all with the same shape: a fail-closed contract system that was
actually fail-OPEN at a specific seam. Each test below reproduces the exact empirical repro
from the finding, watched RED against the pre-fix source, then GREEN after the fix.

    F-38573fb8  Contract(extra="ignore") silently drops a misspelled top-level key.
    F-a5fa3f8b  A same-severity (or higher) redeclaration can silently rewrite an inherited
                atom's claim/check_type -- the "quiet" attack the loud (severity-lowering)
                guard does not catch.
    F-fb7194d3  Duplicate atom ids within one contract are never rejected, so
                QuestionDAG.topological() silently drops the second declaration.

A later wave (swarm-1788165870-6880) added two more, same shape -- an exception escaping
the loader's own documented boundary:

    F-45c39f7d  A structurally-invalid contract file raises a raw pydantic ValidationError
                out of _read_contract, so the CLI exits 2/RUNTIME_UNEXPECTED where the
                covered exit-code contract promises 1 with a CONTRACT_ code.
    F-84788251  _SEVERITY_RANK is a hand-maintained literal subscripted with [], so a
                Severity member this build cannot rank escapes as a raw KeyError.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.core.contract.compile_questions import compile_questions
from pcraft.core.contract.loader import ContractStore, resolve
from pcraft.core.contract.schema import (
    Atom,
    CheckType,
    Contract,
    IdentityRef,
    MustNot,
    ResolvedContract,
    Severity,
    Spatial,
    SpatialKind,
)
from pcraft.errors import PromptCraftError

runner = CliRunner()


def _lookup(contracts):
    by_id = {c.id: c for c in contracts}
    return by_id.get


# ---------------------------------------------------------------------------
# F-38573fb8 -- Contract must reject unknown top-level keys (extra="forbid")
# ---------------------------------------------------------------------------


def test_contract_rejects_a_misspelled_top_level_key():
    """The exact empirical repro from the finding: 'must_have' spelled 'musthave'.

    Before the fix this parsed cleanly with must_have=[] -- a contract the author believed
    required a specific atom silently required nothing.
    """
    payload = {
        "id": "char:x",
        "level": "character",
        "extends": "faction:y",
        "musthave": [
            {"id": "sigil", "claim": "a sigil", "check_type": "vqa", "severity": "required"}
        ],
    }
    with pytest.raises(ValidationError):
        Contract.model_validate(payload)


@pytest.mark.parametrize("bad_key", ["mustnot", "extend", "levell"])
def test_contract_rejects_other_misspelled_top_level_keys(bad_key):
    payload = {"id": "char:x", "level": "character", bad_key: []}
    with pytest.raises(ValidationError):
        Contract.model_validate(payload)


def test_contract_still_matches_every_sibling_model_on_extra_forbid():
    """schema.py's own stated invariant: Contract is no longer the odd one out."""
    from pcraft.core.contract.schema import Atom as _Atom
    from pcraft.core.contract.schema import IdentityRef as _IdentityRef
    from pcraft.core.contract.schema import MustNot as _MustNot
    from pcraft.core.contract.schema import ResolvedContract as _ResolvedContract
    from pcraft.core.contract.schema import Spatial as _Spatial

    for model in (Contract, _Atom, _MustNot, _Spatial, _IdentityRef, _ResolvedContract):
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_contract_still_accepts_the_documented_note_field():
    """extra="forbid" must not re-break the '_note' field the shipped example contracts use.

    Blanket ignore -> blanket forbid is not itself the fix if it takes a legitimate,
    already-shipped authoring field down with the typos. '_note' must become a real,
    narrowly-declared field rather than tolerated extra.
    """
    contract = Contract.model_validate(
        {
            "id": "faction:x",
            "level": "faction",
            "_note": "GENERIC EXAMPLE -- not real canon.",
        }
    )
    assert contract.note == "GENERIC EXAMPLE -- not real canon."


def test_the_shipped_example_contracts_still_load():
    """Direct regression guard: both real *.contract.json fixtures use a top-level '_note'.

    This is the concrete thing that breaks if extra="forbid" ships without also declaring
    'note' -- not a hypothetical, both files under
    src/pcraft/domains/image/subdomains/sprite/contracts/ carry this key today.
    """
    from pcraft.sample import load_sprite_example

    store, resolved, _thresholds, _compiled = load_sprite_example()
    faction = store.resolve("faction:ashen-pact")
    assert faction.id == "faction:ashen-pact"
    assert resolved.id == "char:ashen-reaver"


# ---------------------------------------------------------------------------
# F-a5fa3f8b -- an inherited atom's claim/check_type are frozen; only severity may rise
# ---------------------------------------------------------------------------


def test_child_cannot_silently_rewrite_an_inherited_required_atoms_claim():
    """The finding's own repro, verbatim: 'sigil' the Iron Legion mark -> 'a plain hat',
    severity staying 'required' on both sides so the old severity-only guard never fired.
    """
    faction = Contract(
        id="faction:iron-legion",
        level="faction",
        must_have=[
            Atom(
                id="sigil",
                claim="wears the Iron Legion sigil on the chest",
                check_type=CheckType.vqa,
                severity=Severity.required,
            )
        ],
    )
    character = Contract(
        id="char:defector",
        level="character",
        extends="faction:iron-legion",
        must_have=[
            Atom(
                id="sigil",
                claim="wears a plain hat",
                check_type=CheckType.vqa,
                severity=Severity.required,
            )
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_child_cannot_rewrite_an_inherited_atoms_check_type():
    """check_type is frozen too, not just claim text -- moving an atom to a different
    verifier tier is exactly as silent a defeat as changing what it claims."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="palette", claim="ash-grey colours", check_type=CheckType.palette, severity=Severity.required)
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(id="palette", claim="ash-grey colours", check_type=CheckType.vqa, severity=Severity.required)
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_raising_severity_does_not_license_a_content_swap():
    """Director's wording: 'substituting the claim is not a raise.' A child cannot launder
    a content swap by pairing it with a severity raise -- the two are independent checks."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a felt hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[Atom(id="hat", claim="a straw hat", check_type=CheckType.vqa, severity=Severity.required)],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_raising_severity_with_identical_content_is_still_allowed():
    """Regression guard: the legitimate operation the fix must not collaterally block.

    Mirrors the pre-existing test_raising_severity_is_allowed in test_contract_loader.py --
    kept here too because this file is what future work will diff against for this rule.
    """
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.required)],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.atom_by_id("hat").severity is Severity.required
    assert out.atom_by_id("hat").claim == "a hat"


def test_child_cannot_silently_rewrite_an_inherited_must_not_claim():
    """The must_not counterpart of the finding's repro: 'a firearm of any kind' -> 'a rubber
    duck', severity=required on both sides."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[MustNot(id="no_gun", claim="a firearm of any kind", severity=Severity.required)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[MustNot(id="no_gun", claim="a rubber duck", severity=Severity.required)],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_must_not_raising_severity_with_identical_content_is_still_allowed():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[MustNot(id="no_gun", claim="a firearm", severity=Severity.optional)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[MustNot(id="no_gun", claim="a firearm", severity=Severity.required)],
    )
    out = resolve(character, _lookup([faction, character]))
    assert out.must_not[0].severity is Severity.required
    assert out.must_not[0].claim == "a firearm"


def test_child_cannot_silently_rewrite_an_inherited_spatial():
    """Stage A remainder: claim/check_type froze; spatial still swapped chest -> hat."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(
                id="sigil",
                claim="sigil on chest",
                check_type=CheckType.vqa,
                severity=Severity.required,
                spatial=Spatial(kind=SpatialKind.region, ref="chest"),
            )
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(
                id="sigil",
                claim="sigil on chest",
                check_type=CheckType.vqa,
                severity=Severity.required,
                spatial=Spatial(kind=SpatialKind.region, ref="hat"),
            )
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_child_cannot_silently_rewrite_an_inherited_enum():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(
                id="crest",
                claim="a gold crest",
                check_type=CheckType.palette,
                severity=Severity.required,
                enum=["gold", "red"],
            )
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(
                id="crest",
                claim="a gold crest",
                check_type=CheckType.palette,
                severity=Severity.required,
                enum=["plain"],
            )
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_child_cannot_silently_rewrite_an_inherited_depends_on():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="face", claim="a face", check_type=CheckType.siglip2, severity=Severity.required),
            Atom(
                id="scar",
                claim="a scar on the face",
                check_type=CheckType.vqa,
                severity=Severity.required,
                depends_on="face",
            ),
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(
                id="scar",
                claim="a scar on the face",
                check_type=CheckType.vqa,
                severity=Severity.required,
                depends_on="hat",
            )
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_raising_severity_without_restating_spatial_keeps_the_inherited_lock():
    """Omitting spatial is inherit, not a wipe. A raise must not drop the region."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(
                id="sigil",
                claim="sigil on chest",
                check_type=CheckType.vqa,
                severity=Severity.optional,
                spatial=Spatial(kind=SpatialKind.region, ref="chest"),
            )
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(
                id="sigil",
                claim="sigil on chest",
                check_type=CheckType.vqa,
                severity=Severity.required,
            )
        ],
    )
    out = resolve(character, _lookup([faction, character]))
    atom = out.atom_by_id("sigil")
    assert atom.severity is Severity.required
    assert atom.spatial is not None
    assert atom.spatial.ref == "chest"


def test_must_not_spatial_is_frozen_on_redeclaration():
    from pcraft.core.contract.schema import Spatial, SpatialKind

    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[
            MustNot(
                id="no_gun",
                claim="a firearm",
                spatial=Spatial(kind=SpatialKind.region, ref="hands"),
            )
        ],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[
            MustNot(
                id="no_gun",
                claim="a firearm",
                spatial=Spatial(kind=SpatialKind.region, ref="head"),
            )
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"
    assert "spatial" in exc.value.message


def test_must_not_enum_is_frozen_on_redeclaration():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[MustNot(id="no_gun", claim="a firearm", enum=["pistol", "rifle"])],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[MustNot(id="no_gun", claim="a firearm", enum=["rubber-duck"])],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_contract_relaxation_from_the_loader_never_recommends_overriding_the_atom():
    """The hint text used to say 'or override the atom' -- literally endorsing the bypass
    this fix closes. errors.py's DEFAULT_HINTS is out of this domain's owned paths, but
    every CONTRACT_RELAXATION raised from loader.py is in it, and each must carry its own
    precise hint that does not recommend the thing that is now forbidden.
    """
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.required)],
    )

    # (a) severity-lowering path
    lowered = Contract(
        id="char:a", level="character", extends="faction:x",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.optional)],
    )
    with pytest.raises(PromptCraftError) as exc_a:
        resolve(lowered, _lookup([faction, lowered]))

    # (b) content-substitution path
    swapped = Contract(
        id="char:b", level="character", extends="faction:x",
        must_have=[Atom(id="hat", claim="a cap", check_type=CheckType.vqa, severity=Severity.required)],
    )
    with pytest.raises(PromptCraftError) as exc_b:
        resolve(swapped, _lookup([faction, swapped]))

    for exc in (exc_a, exc_b):
        assert "override the atom" not in exc.value.hint.lower()


# ---------------------------------------------------------------------------
# F-fb7194d3 -- duplicate atom ids within one contract must be rejected
# ---------------------------------------------------------------------------


def test_contract_rejects_duplicate_must_have_ids():
    with pytest.raises(PromptCraftError) as exc:
        Contract(
            id="char:x",
            level="character",
            must_have=[
                Atom(id="face", claim="a scarred face", check_type=CheckType.vqa),
                Atom(id="face", claim="a clean-shaven face", check_type=CheckType.vqa),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_contract_rejects_duplicate_must_not_ids():
    with pytest.raises(PromptCraftError) as exc:
        Contract(
            id="char:x",
            level="character",
            must_not=[
                MustNot(id="no_gun", claim="a pistol"),
                MustNot(id="no_gun", claim="a rifle"),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_resolved_contract_rejects_duplicate_must_not_ids():
    """The finding's own repro, constructed directly against ResolvedContract (bypassing the
    loader entirely, exactly as the audit did) -- this is the object compile_questions()
    actually consumes, so the guard must hold here even if every Contract were already clean.
    """
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:x",
            level="character",
            lineage=["char:x"],
            must_have=[],
            identity_refs=[],
            must_not=[
                MustNot(id="no_gun", claim="a firearm", severity=Severity.optional),
                MustNot(id="no_gun", claim="a firearm", severity=Severity.required),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_resolved_contract_rejects_duplicate_must_have_ids():
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:x",
            level="character",
            lineage=["char:x"],
            must_not=[],
            identity_refs=[],
            must_have=[
                Atom(id="face", claim="a scarred face", check_type=CheckType.vqa),
                Atom(id="face", claim="a clean face", check_type=CheckType.vqa),
            ],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_a_clean_contract_with_no_duplicates_still_compiles(sprite_example):
    """Sanity: the new guard must not false-positive on ordinary, id-unique contracts."""
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    ids = [q.atom_id for q in dag.questions]
    assert len(ids) == len(set(ids))


def test_distinct_ids_across_must_have_and_must_not_are_unaffected():
    """An id used once in each list, with different names, is not a collision."""
    contract = Contract(
        id="char:x",
        level="character",
        must_have=[Atom(id="face", claim="a face", check_type=CheckType.vqa)],
        must_not=[MustNot(id="no_face_paint", claim="face paint")],
    )
    assert {a.id for a in contract.must_have} == {"face"}
    assert {m.id for m in contract.must_not} == {"no_face_paint"}


def test_same_id_in_must_have_and_must_not_is_rejected():
    """compile_questions keys the DAG by atom_id. A must_have and a must_not sharing
    an id last-write or first-match one polarity away."""
    with pytest.raises(PromptCraftError) as exc:
        Contract(
            id="char:x",
            level="character",
            must_have=[Atom(id="sigil", claim="the legion sigil", check_type=CheckType.vqa)],
            must_not=[MustNot(id="sigil", claim="the legion sigil")],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


def test_child_cannot_neutralize_an_inherited_identity_plate():
    """CONTRACT-W3-001: same plate, method=none / weight 0, no CONTRACT_RELAXATION."""
    faction = Contract(
        id="faction:x",
        level="faction",
        identity_ref=IdentityRef(plate="plates/legion.png", method="lora", weight=0.8, scope="costume"),
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        identity_ref=IdentityRef(plate="plates/legion.png", method="none", weight=0.0, scope="costume"),
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_RELAXATION"


def test_distinct_identity_plates_still_compose():
    faction = Contract(
        id="faction:x",
        level="faction",
        identity_ref=IdentityRef(plate="plates/costume.png", method="lora", weight=0.8, scope="costume"),
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        identity_ref=IdentityRef(plate="plates/face.png", method="ip_adapter", weight=0.6, scope="face"),
    )
    out = resolve(character, _lookup([faction, character]))
    assert [ir.scope for ir in out.identity_refs] == ["costume", "face"]


def test_resolved_contract_rejects_cross_list_id_collision():
    with pytest.raises(PromptCraftError) as exc:
        ResolvedContract(
            id="char:x",
            level="character",
            lineage=["char:x"],
            identity_refs=[],
            must_have=[Atom(id="sigil", claim="the legion sigil", check_type=CheckType.vqa)],
            must_not=[MustNot(id="sigil", claim="the legion sigil")],
        )
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


# ---------------------------------------------------------------------------
# F-45c39f7d -- a structurally-invalid contract is a STRUCTURED refusal, exit 1
# ---------------------------------------------------------------------------


def _write_contract(directory, name: str, payload: dict):
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bad_check_type_payload() -> dict:
    """The finding's own repro: a check_type outside the CheckType enum."""
    return {
        "$schema": "prompt-craft/contract.v1",
        "id": "faction:typo",
        "level": "faction",
        "must_have": [
            {"id": "tabard", "claim": "a tabard", "check_type": "not_a_real_check_type"}
        ],
    }


def test_a_structurally_invalid_contract_file_is_a_structured_refusal(tmp_path):
    """Before the fix `Contract.model_validate(data)` in _read_contract was unguarded, so a
    bad enum value left the loader as a raw pydantic_core.ValidationError -- an exception
    class from outside the PromptCraftError hierarchy crossing the loader's boundary."""
    _write_contract(tmp_path, "typo.contract.json", _bad_check_type_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert exc.value.code.startswith("CONTRACT_")
    assert exc.value.exit_code == 1


def test_a_structurally_invalid_contract_names_the_file_and_keeps_the_cause(tmp_path):
    """A diagnosis, not just a reclassification: the refusal must say WHICH file, and keep
    the pydantic error as `cause` so --debug can still show the field-level detail."""
    path = _write_contract(tmp_path, "typo.contract.json", _bad_check_type_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert str(path) in exc.value.message or path.name in exc.value.message
    assert exc.value.cause is not None
    assert "check_type" in exc.value.to_debug_text()


@pytest.mark.parametrize(
    "payload",
    [
        # extra/misspelled key under extra="forbid"
        {"id": "faction:x", "level": "faction", "must_hav": []},
        # wrong field type
        {"id": "faction:x", "level": "faction", "must_have": "tabard"},
        # the literal "$schema": null the finding calls out
        {"$schema": None, "id": "faction:x", "level": "faction"},
        # missing a required field
        {"level": "faction"},
    ],
    ids=["extra-key", "wrong-type", "null-schema", "missing-id"],
)
def test_every_structural_contract_defect_is_a_contract_error(tmp_path, payload):
    _write_contract(tmp_path, "bad.contract.json", payload)
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert exc.value.code.startswith("CONTRACT_")
    assert exc.value.exit_code == 1


def test_the_cli_exits_1_not_2_on_a_structurally_invalid_contract(tmp_path):
    """The end-to-end repro from the finding, via typer's CliRunner. STABILITY.md's covered
    exit-code contract says 1 = user error (INPUT_/CONFIG_/CONTRACT_); this path was landing
    on the RUNTIME_UNEXPECTED backstop at 2, which the code's own hint calls
    'the backstop, not a diagnosis'."""
    _write_contract(tmp_path, "typo.contract.json", _bad_check_type_payload())
    result = runner.invoke(app, ["synth", "--contracts-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "RUNTIME_UNEXPECTED" not in text
    assert "CONTRACT_" in text


def test_a_well_formed_contract_tree_still_loads(tmp_path):
    """The collateral guard: wrapping the third failure mode must not refuse valid input."""
    _write_contract(
        tmp_path,
        "ok.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:ok",
            "level": "faction",
            "must_have": [{"id": "tabard", "claim": "a tabard", "check_type": "vqa"}],
        },
    )
    store = ContractStore([tmp_path])
    assert store.ids() == ["faction:ok"]


def test_a_promptcrafterror_raised_inside_a_validator_still_passes_through(tmp_path):
    """The guard must re-raise, not re-wrap: schema.py's duplicate-id check raises a
    PromptCraftError from inside a @model_validator, and pydantic does NOT wrap those.
    Its code must survive the new try/except unchanged."""
    _write_contract(
        tmp_path,
        "dupe.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:dupe",
            "level": "faction",
            "must_have": [
                {"id": "face", "claim": "a face", "check_type": "vqa"},
                {"id": "face", "claim": "another face", "check_type": "vqa"},
            ],
        },
    )
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert exc.value.code == "CONTRACT_DUPLICATE_ATOM_ID"


# ---------------------------------------------------------------------------
# F-2b317b56 -- `pcraft validate` must REFUSE a depends_on cycle, not report ok
#
# The wave-2 fix (F-19f97de2) closed the DANGLING edge at load time. A CYCLE was the sibling
# case nobody refused. MEASURED before this fix, through this exact CLI path: a 2-cycle
# contract printed "ok  faction:cyc" and exited 0 -- because `validate` compiles the question
# DAG but never WALKS it -- and the defect surfaced only later, in bind/gate, as a bare
# ValueError out of QuestionDAG.topological(). "ok, exit 0" for a contract that cannot be
# gated is the loudest possible version of this system's one recurring failure shape: a
# fail-closed guarantee that is fail-OPEN at a specific seam.
# ---------------------------------------------------------------------------


def _cyclic_payload(contract_id: str = "faction:cyc") -> dict:
    return {
        "$schema": "prompt-craft/contract.v1",
        "id": contract_id,
        "level": "faction",
        "must_have": [
            {"id": "a", "claim": "an a", "check_type": "vqa", "depends_on": "b"},
            {"id": "b", "claim": "a b", "check_type": "vqa", "depends_on": "a"},
        ],
    }


def test_validate_refuses_a_cyclic_contract_instead_of_reporting_ok(tmp_path):
    _write_contract(tmp_path, "cyc.contract.json", _cyclic_payload())
    result = runner.invoke(
        app, ["validate", "--contract", "faction:cyc", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "CONTRACT_CYCLIC_DEPENDS_ON" in text
    assert "ok  faction:cyc" not in text
    assert "RUNTIME_UNEXPECTED" not in text  # a named refusal, not the backstop


def test_validate_refuses_a_self_depending_atom(tmp_path):
    _write_contract(
        tmp_path,
        "self.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:self",
            "level": "faction",
            "must_have": [
                {"id": "scar", "claim": "a scar", "check_type": "vqa", "depends_on": "scar"}
            ],
        },
    )
    result = runner.invoke(
        app, ["validate", "--contract", "faction:self", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "CONTRACT_CYCLIC_DEPENDS_ON" in text


def test_validate_still_reports_ok_for_an_intact_depends_on_chain(tmp_path):
    """The collateral guard: the shipped contracts use depends_on, and a chain is not a loop."""
    _write_contract(
        tmp_path,
        "chain.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:chain",
            "level": "faction",
            "must_have": [
                {"id": "face", "claim": "a face", "check_type": "vqa"},
                {"id": "scar", "claim": "a scar", "check_type": "vqa", "depends_on": "face"},
                {"id": "stitch", "claim": "a stitch", "check_type": "vqa", "depends_on": "scar"},
            ],
        },
    )
    result = runner.invoke(
        app, ["validate", "--contract", "faction:chain", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, text
    assert "ok  faction:chain" in text


def test_the_cycle_refusal_renders_on_a_cp437_console(tmp_path):
    """Same discipline as every other refusal in this domain: the new message and hint must
    survive the console that made F-fd21bd37 a crash rather than a diagnosis."""
    _write_contract(tmp_path, "cyc.contract.json", _cyclic_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path]).resolve("faction:cyc")
    exc.value.to_safe_text().encode("cp437", errors="strict")


# ---------------------------------------------------------------------------
# F-84788251 -- an unrankable severity fails loud-and-STRUCTURED, not raw KeyError
# ---------------------------------------------------------------------------


def test_the_severity_rank_table_covers_every_severity_member():
    """The exhaustiveness proof. This is the test that goes red the day a third member is
    added to the Severity enum without a rank -- which is the whole point of the finding."""
    from pcraft.core.contract.loader import _SEVERITY_RANK

    assert set(_SEVERITY_RANK) == set(Severity)


def test_an_unrankable_severity_is_a_structured_refusal():
    from pcraft.core.contract.loader import _severity_rank

    with pytest.raises(PromptCraftError) as exc:
        _severity_rank("advisory")
    assert exc.value.code == "CONTRACT_UNKNOWN_SEVERITY"


def test_severity_rank_still_orders_optional_below_required():
    """The rank must not be derived from enum declaration order -- Severity declares
    `required` first, so enumerate() would invert the comparison and turn the whole
    fail-closed relaxation guard into a pass-open one."""
    from pcraft.core.contract.loader import _severity_rank

    assert _severity_rank(Severity.optional) < _severity_rank(Severity.required)


def test_a_severity_this_build_cannot_rank_does_not_escape_the_loader_as_a_keyerror():
    """Through the real merge path. `_SEVERITY_RANK[atom.severity]` was a bare subscript,
    so an unranked member left `resolve()` as a raw KeyError -- the same boundary breach as
    F-45c39f7d, different mechanism."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa)],
    )
    # A member a future Severity could carry; this build has no rank for it.
    character.must_have[0].severity = "advisory"
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_UNKNOWN_SEVERITY"


def test_an_unrankable_must_not_severity_is_also_structured():
    faction = Contract(
        id="faction:x",
        level="faction",
        must_not=[MustNot(id="no_gun", claim="a firearm")],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_not=[MustNot(id="no_gun", claim="a firearm")],
    )
    character.must_not[0].severity = "advisory"
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    assert exc.value.code == "CONTRACT_UNKNOWN_SEVERITY"


# ---------------------------------------------------------------------------
# F-ca6f8509 -- `pcraft validate` must REFUSE an extends cycle, not crash at exit 2
#
# The sibling of the depends_on cycle above, on the mechanism that fix never touched.
# MEASURED before this fix, through this exact CLI path: a single character contract with
# "extends": "<its own id>" -- a one-line typo indistinguishable from copy-pasting a template
# contract and forgetting to retarget extends -- exited 2 with
# 'error[RUNTIME_UNEXPECTED]: maximum recursion depth exceeded', whose own hint calls that
# code "the backstop, not a diagnosis". A two-file mutual cycle produced the identical raw
# RecursionError. Exit 2 means "prompt-craft crashed"; this is exit-1 user input.
# ---------------------------------------------------------------------------


def _extends_payload(contract_id: str, extends: str, *, atom: str = "a") -> dict:
    return {
        "$schema": "prompt-craft/contract.v1",
        "id": contract_id,
        "level": "character",
        "extends": extends,
        "must_have": [{"id": atom, "claim": f"an {atom}", "check_type": "vqa"}],
    }


def test_validate_refuses_a_self_extending_contract_instead_of_crashing(tmp_path):
    _write_contract(
        tmp_path, "loop.contract.json", _extends_payload("char:self-loop", "char:self-loop")
    )
    result = runner.invoke(
        app, ["validate", "--contract", "char:self-loop", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "CONTRACT_CYCLIC_EXTENDS" in text
    assert "RUNTIME_UNEXPECTED" not in text
    assert "recursion" not in text.lower()


def test_validate_refuses_a_two_file_mutual_extends_cycle(tmp_path):
    _write_contract(tmp_path, "a.contract.json", _extends_payload("char:a", "char:b", atom="ax"))
    _write_contract(tmp_path, "b.contract.json", _extends_payload("char:b", "char:a", atom="bx"))
    result = runner.invoke(
        app, ["validate", "--contract", "char:a", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "CONTRACT_CYCLIC_EXTENDS" in text
    assert "RUNTIME_UNEXPECTED" not in text


def test_validate_still_reports_ok_for_a_legitimate_multi_level_extends_chain(tmp_path):
    """The collateral guard, and the reason the fix is a cycle check rather than a ban on
    character-extends-character: resolve()'s own comment calls multi-level chains supported,
    and the finding MEASURED a 3-level chain resolving cleanly. A loop is the defect; depth
    is not."""
    _write_contract(
        tmp_path,
        "root.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:root",
            "level": "faction",
            "must_have": [{"id": "tabard", "claim": "a tabard", "check_type": "vqa"}],
        },
    )
    _write_contract(tmp_path, "mid.contract.json", _extends_payload("char:mid", "faction:root", atom="mid"))
    _write_contract(tmp_path, "leaf.contract.json", _extends_payload("char:leaf", "char:mid", atom="leaf"))
    result = runner.invoke(
        app, ["validate", "--contract", "char:leaf", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, text
    assert "ok  char:leaf" in text
    assert "faction:root -> char:mid -> char:leaf" in text  # the lineage survives the walk


def test_the_extends_cycle_refusal_renders_on_a_cp437_console(tmp_path):
    _write_contract(
        tmp_path, "loop.contract.json", _extends_payload("char:self-loop", "char:self-loop")
    )
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path]).resolve("char:self-loop")
    exc.value.to_safe_text().encode("cp437", errors="strict")


# ---------------------------------------------------------------------------
# F-588763b4 -- a blank `claim` is refused at construction, exactly as a blank `id` is
#
# schema.py spends two long docstrings (_NON_EMPTY_ID_RATIONALE, _BLANK_ID_RATIONALE) arguing
# that an empty-or-whitespace id "is not a contract anyone means to write" and must be refused
# at construction rather than trusted to a downstream consumer -- then left `claim: str` bare
# on the same two classes. MEASURED: Atom(id='a1', claim='') and Atom(id='a2', claim='   ')
# both constructed cleanly, the template synthesizer emitted a prompt with a bare leading
# comma, and compile_questions emitted a REQUIRED probe reading "Does this image show ?".
#
# assert_coverage would catch it downstream -- but only for callers that remember to call it,
# which is the same "not the only way to obtain a ResolvedContract" gap F-877a8d9b named for
# depends_on before that check moved onto the type.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab-newline"])
def test_an_atom_claim_that_is_blank_once_stripped_is_refused(blank):
    with pytest.raises(ValidationError):
        Atom(id="a1", claim=blank, check_type=CheckType.vqa)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab-newline"])
def test_a_must_not_claim_that_is_blank_once_stripped_is_refused(blank):
    with pytest.raises(ValidationError):
        MustNot(id="m1", claim=blank)


def test_a_blank_claim_on_disk_is_a_structured_contract_refusal(tmp_path):
    """The authoring path, end to end: pydantic folds the field validator's ValueError into
    the same ValidationError _read_contract already turns into CONTRACT_INVALID -- so this is
    exit 1 with a CONTRACT_ code, never the RUNTIME_UNEXPECTED backstop."""
    _write_contract(
        tmp_path,
        "blank.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:blank",
            "level": "faction",
            "must_have": [{"id": "tabard", "claim": "   ", "check_type": "vqa"}],
        },
    )
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert exc.value.code == "CONTRACT_INVALID"
    assert exc.value.exit_code == 1


def test_a_blank_claim_never_reaches_the_question_dag():
    """The defect the guard exists to stop, stated as the finding measured it: a required
    probe with no content -- "Does this image show ?" -- sent to a live verifier tier."""
    with pytest.raises(ValidationError):
        compile_questions(
            ResolvedContract(
                id="char:blank",
                level="character",
                lineage=["char:blank"],
                identity_refs=[],
                must_not=[],
                must_have=[Atom(id="tabard", claim="", check_type=CheckType.vqa)],
            )
        )


def test_a_claim_carrying_incidental_whitespace_is_stored_as_authored():
    """Only BLANK is refused -- the same line the id rule draws. Normalizing would silently
    rewrite authored contract text, which is a far larger change than this gap justifies."""
    atom = Atom(id="tabard", claim="  a grey-ash tabard  ", check_type=CheckType.vqa)
    assert atom.claim == "  a grey-ash tabard  "


def test_the_shipped_example_contracts_still_construct_under_the_claim_guard(sprite_example):
    """The collateral guard: every shipped atom and negation carries a real claim."""
    _store, resolved, _t, _c = sprite_example
    for item in (*resolved.must_have, *resolved.must_not):
        assert item.claim.strip()


# ---------------------------------------------------------------------------
# F-40a4956f -- CONTRACT_INVALID must carry a diagnosis without --debug
#
# The one refusal in loader.py that said nothing: "contract <path> does not match the contract
# schema" -- no field name, no count, no location -- forcing --debug for ANY diagnostic
# content at all, even to learn how many things were wrong. Every sibling CONTRACT_ code in
# the same file (RELAXATION, MISSING_BASE, DUPLICATE_ATOM_ID, UNKNOWN_DEPENDS_ON,
# CYCLIC_DEPENDS_ON) embeds the specific id, field, and values in the message with no flag.
#
# MEASURED: pydantic itself was never the limit -- a contract with two independently-invalid
# fields returns BOTH from err.errors(). The default path was throwing that away.
# ---------------------------------------------------------------------------


def _two_error_payload() -> dict:
    """Two independently-invalid fields at once: a bad check_type enum on one atom, and an
    extra_forbidden key on a second."""
    return {
        "$schema": "prompt-craft/contract.v1",
        "id": "faction:two",
        "level": "faction",
        "must_have": [
            {"id": "tabard", "claim": "a tabard", "check_type": "not_a_real_check_type"},
            {"id": "sigil", "claim": "a sigil", "check_type": "vqa", "colour": "grey"},
        ],
    }


def test_the_schema_refusal_names_the_failing_field_without_debug(tmp_path):
    _write_contract(tmp_path, "typo.contract.json", _bad_check_type_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert exc.value.code == "CONTRACT_INVALID"
    assert "check_type" in exc.value.to_safe_text()


def test_the_schema_refusal_reports_every_error_not_just_the_first(tmp_path):
    """The Stage B lens the finding was written to answer. --debug already showed both (it
    prints pydantic's own '2 validation errors for Contract' block); the DEFAULT path showed
    neither."""
    _write_contract(tmp_path, "two.contract.json", _two_error_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    safe = exc.value.to_safe_text()
    assert "2 " in safe  # the count, so a reader knows how many things are wrong
    assert "check_type" in safe  # the first error's location
    assert "colour" in safe  # ...and the second's, which first-error-only would have dropped


def test_the_schema_refusal_still_names_the_file_and_keeps_the_cause(tmp_path):
    """The enrichment must not cost what the wave-2 fix bought: the path and the pydantic
    cause both survive, so --debug still reaches the full traceback."""
    path = _write_contract(tmp_path, "two.contract.json", _two_error_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    assert path.name in exc.value.message
    assert exc.value.cause is not None
    assert "2 validation errors for Contract" in exc.value.to_debug_text()


def test_the_enriched_schema_refusal_renders_on_a_cp437_console(tmp_path):
    _write_contract(tmp_path, "two.contract.json", _two_error_payload())
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    exc.value.to_safe_text().encode("cp437", errors="strict")


def test_the_schema_refusal_stays_bounded_on_a_contract_full_of_errors(tmp_path):
    """A diagnosis, not a dump. Twenty bad atoms must not paste twenty locations into a
    console line -- the count still tells the reader the scale, and --debug still has all of
    them."""
    _write_contract(
        tmp_path,
        "many.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:many",
            "level": "faction",
            "must_have": [
                {"id": f"a{i}", "claim": f"an a{i}", "check_type": "nope"} for i in range(20)
            ],
        },
    )
    with pytest.raises(PromptCraftError) as exc:
        ContractStore([tmp_path])
    safe = exc.value.to_safe_text()
    assert "20" in safe
    assert len(safe.splitlines()) <= 8


def test_a_valid_contract_is_still_not_refused_by_the_enriched_message(tmp_path):
    _write_contract(
        tmp_path,
        "ok.contract.json",
        {
            "$schema": "prompt-craft/contract.v1",
            "id": "faction:ok2",
            "level": "faction",
            "must_have": [{"id": "tabard", "claim": "a tabard", "check_type": "vqa"}],
        },
    )
    assert ContractStore([tmp_path]).ids() == ["faction:ok2"]


# ---------------------------------------------------------------------------
# F-d1d2833f -- register() must fail closed on a duplicate domain name
#
# `_REGISTRY[plugin.name] = plugin` let a second registration under an existing name SILENTLY
# overwrite the first -- no warning, no log, no error -- against strong precedent in this
# exact package: ContractStore raises INPUT_DUPLICATE_CONTRACT_ID and schema._reject_duplicate_ids
# raises CONTRACT_DUPLICATE_ATOM_ID, both fail-closed on "two things claiming the same
# identity". The registry is the higher-stakes of the three: cli/__init__.py's get(name) is
# what selects the Generator that gets bound (real GPU/Cloud spend), so a clobbered
# registration misroutes generation with no signal anywhere.
#
# Not reachable today (one register call ships, in domains/image/__init__.py), but plugin.py's
# own docstring names the intended near-future shape -- "Adding video or workflow is one
# register call" -- and _REGISTRY is unscoped module-global state with no reset hook.
# ---------------------------------------------------------------------------


class _StubPlugin:
    """A structurally valid DomainPlugin that touches no GPU and loads no model."""

    def __init__(self, name: str) -> None:
        self.name = name

    def generator(self):  # pragma: no cover - never called; registration is the subject
        raise AssertionError("the stub plugin is not runnable")

    def verifiers(self) -> dict:  # pragma: no cover - same
        raise AssertionError("the stub plugin is not runnable")

    def encoder_rules_path(self) -> Path:  # pragma: no cover - same
        raise AssertionError("the stub plugin is not runnable")


@pytest.fixture
def isolated_registry(monkeypatch):
    """A private copy of the module-global registry, reverted after the test.

    _REGISTRY has no reset hook, so a test that registered into the real one would leak into
    every later test in the session -- which is the same unscoped-global hazard this finding
    names."""
    from pcraft.core import plugin as plugin_mod

    monkeypatch.setattr(plugin_mod, "_REGISTRY", dict(plugin_mod._REGISTRY))
    return plugin_mod


def test_registering_a_second_plugin_under_an_existing_name_is_refused(isolated_registry):
    isolated_registry.register(_StubPlugin("video"))
    with pytest.raises(PromptCraftError) as exc:
        isolated_registry.register(_StubPlugin("video"))
    assert exc.value.code == "INPUT_DUPLICATE_DOMAIN"
    assert exc.value.exit_code == 1
    assert "video" in exc.value.message


def test_the_first_registration_survives_a_refused_duplicate(isolated_registry):
    """Fail CLOSED: the refusal must not be a warning that leaves the clobber in place."""
    first = _StubPlugin("video")
    isolated_registry.register(first)
    with pytest.raises(PromptCraftError):
        isolated_registry.register(_StubPlugin("video"))
    assert isolated_registry.get("video") is first


def test_registering_a_malformed_plugin_is_refused_at_registration(isolated_registry):
    """Before: a malformed plugin registered cleanly and failed later as a raw AttributeError
    at whatever call site first touched the missing method."""

    class Malformed:
        name = "workflow"

        def generator(self):  # pragma: no cover - never reached
            raise AssertionError

    with pytest.raises(PromptCraftError) as exc:
        isolated_registry.register(Malformed())
    assert exc.value.code == "INPUT_INVALID_DOMAIN_PLUGIN"
    assert "workflow" not in isolated_registry.registered()


def test_distinct_domain_names_still_register(isolated_registry):
    """The collateral guard -- and the shape plugin.py's docstring promises."""
    isolated_registry.register(_StubPlugin("video"))
    isolated_registry.register(_StubPlugin("workflow"))
    assert {"video", "workflow"} <= set(isolated_registry.registered())


def test_the_shipped_image_plugin_is_still_registered_exactly_once():
    """The live path, unmocked: importing the one shipped domain must not now refuse itself."""
    import pcraft.domains.image  # noqa: F401  - importing IS the registration
    from pcraft.core.plugin import get, registered

    assert registered().count("image") == 1
    assert get("image").name == "image"


# ---------------------------------------------------------------------------
# F-fd21bd37 -- user-facing text in this domain must survive a cp437 console
#
# Family-of-call-sites sibling of the em-dash crash the cli-ux and core-gate-loop
# agents closed in their own files. A structured refusal is worth nothing if PRINTING it
# raises: `_emit` writes the message and hint to stdout, and a classic cmd.exe console is
# cp437, which has no U+2014. The refusal then dies as a UnicodeEncodeError -- turning a
# clean exit-1 diagnosis into a traceback, at exactly the moment the user has a broken
# contract and needs to read the hint.
#
# Two live hint literals in this domain carried an em dash: loader.py's _RELAXATION_HINT
# (raised by every CONTRACT_RELAXATION) and schema.py's CONTRACT_DUPLICATE_ATOM_ID hint.
#
# `pcraft schema` is a near miss worth recording rather than a second bug. It dumps
# Contract.model_json_schema(), and pydantic DOES fold each model's docstring into that JSON
# as `description` (measured: Atom's docstring is in the output) -- so docstrings in
# schema.py are user-facing text. That path survives today only because the CLI calls
# json.dumps without ensure_ascii=False, and the default escapes every non-ASCII character
# to a \\uXXXX sequence. The protection is json's default, not the text being printable;
# one ensure_ascii=False would expose it.
#
# So the sweep below covers whole files rather than a hand-picked list of strings: which
# text is user-facing is not a stable property of where that text sits.
# ---------------------------------------------------------------------------

_CONSOLE_ENCODING = "cp437"

# [!] CORRECTED IN PLACE (F-de08ba2e). The three package globs read `core/contract/*.py`,
# `core/synth/*.py`, `core/optimize/*.py` -- a single `*`, which does not cross a `/`. This
# domain's actual ownership globs are the RECURSIVE `core/contract/**` etc., so the fixture's
# reach was pinned to today's incidentally-flat directory layout rather than to what the
# domain claims. MEASURED: with a file written to a new core/synth/<subdir>/, `core/synth/*.py`
# did not find it while `core/synth/**/*.py` did -- so the first subdirectory added under any
# of the three packages would make every string in every file under it permanently invisible
# to all three sweeps below, which stay GREEN while checking strictly less than they claim.
# Not hypothetical for this domain: the deferred F-f7bce385 names an Ollama-Cloud / local-8B
# backend as the intended integration point for core/synth's predictor seam, which is a named
# place for a new core/synth submodule to land. `**` still matches depth-zero files, so
# nothing that was covered stops being covered.
_OWNED_SOURCE_GLOBS = (
    "core/contract/**/*.py",
    "core/synth/**/*.py",
    "core/optimize/**/*.py",
    "core/plugin.py",
    "core/__init__.py",
)


def _sources_under(root: Path) -> list[Path]:
    """Every owned source file under one package root, by the globs above.

    Non-emptiness is asserted PER GLOB, not only on the combined list: a rename that orphans
    one of the three packages would otherwise be masked by the other two still matching, and
    the sweeps would go quietly narrow instead of red.
    """
    found: list[Path] = []
    for pattern in _OWNED_SOURCE_GLOBS:
        matched = sorted(root.glob(pattern))
        assert matched, f"owned-source glob {pattern!r} matched nothing under {root}"
        found.extend(matched)
    return found


def _owned_sources():
    import pcraft

    return _sources_under(Path(pcraft.__file__).parent)


def _non_ascii_offenders(path: Path, *, label: str | None = None) -> list[str]:
    """(file:line: codepoints) for every line carrying a character above U+007F."""
    offenders: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        bad = {c for c in line if ord(c) > 127}
        if bad:
            codepoints = ", ".join(sorted(f"U+{ord(c):04X}" for c in bad))
            offenders.append(f"{label or path.name}:{lineno}: {codepoints}")
    return offenders


def _string_constants_under(node) -> list[str]:
    """Every str literal beneath a node, f-string fragments included."""
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _user_facing_literals(path: Path) -> list[tuple[str, str]]:
    """(where, text) for every refusal message/hint literal in one owned source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        # every string inside a PromptCraftError(...) construction: code, message, hint
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "PromptCraftError":
                where = f"{path.name}:{node.lineno} PromptCraftError"
                out.extend((where, text) for text in _string_constants_under(node))
        # and every module-level hint constant those calls point at by name
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("_HINT"):
                    where = f"{path.name}:{node.lineno} {target.id}"
                    out.extend((where, text) for text in _string_constants_under(node.value))
    return out


def test_every_refusal_message_and_hint_encodes_on_a_cp437_console():
    offenders = []
    for path in _owned_sources():
        for where, text in _user_facing_literals(path):
            try:
                text.encode(_CONSOLE_ENCODING, errors="strict")
            except UnicodeEncodeError as err:
                offenders.append(f"{where}: {err.reason} at {text[err.start:err.end]!r}")
    assert not offenders, "user-facing text that a cp437 console cannot print:\n" + "\n".join(
        offenders
    )


def test_the_relaxation_hint_the_loader_raises_most_is_printable():
    """The specific literal that carried the em dash, named so a regression is unmissable."""
    from pcraft.core.contract.loader import _RELAXATION_HINT

    _RELAXATION_HINT.encode(_CONSOLE_ENCODING, errors="strict")


def test_a_raised_contract_refusal_renders_on_a_cp437_console():
    """End to end through the real object: to_safe_text is what `_emit` hands to the console."""
    faction = Contract(
        id="faction:x",
        level="faction",
        must_have=[Atom(id="hat", claim="a hat", check_type=CheckType.vqa)],
    )
    character = Contract(
        id="char:y",
        level="character",
        extends="faction:x",
        must_have=[
            Atom(id="hat", claim="a hat", check_type=CheckType.vqa, severity=Severity.optional)
        ],
    )
    with pytest.raises(PromptCraftError) as exc:
        resolve(character, _lookup([faction, character]))
    exc.value.to_safe_text().encode(_CONSOLE_ENCODING, errors="strict")


def test_the_dumped_contract_json_schema_is_printable():
    """`pcraft schema` writes this to stdout. Green before the sweep as well as after --
    kept because it pins the reason. Pydantic folds every model docstring into the schema as
    `description`, so schema.py's prose IS in this output; what keeps it printable is that
    the CLI leaves json.dumps' ensure_ascii default alone. This test is what goes red if
    someone "fixes" that call by passing ensure_ascii=False.
    """
    from pcraft.core.contract.schema import export_json_schema

    dumped = json.dumps(export_json_schema(), indent=2)  # exactly what cli/__init__.py does
    assert "description" in dumped  # the docstrings really are in the printed surface
    dumped.encode(_CONSOLE_ENCODING, errors="strict")


def test_no_owned_source_file_carries_a_non_ascii_character():
    """The sweep guard that keeps the three tests above true as this domain is edited.

    ASCII rather than cp437: cp437 would accept a handful of accented characters that then
    break on a UTF-8-only reader, and no message in this domain needs one. Holding the whole
    file to ASCII means nobody has to re-decide which literals are user-facing.
    """
    offenders = []
    for path in _owned_sources():
        offenders.extend(_non_ascii_offenders(path))
    assert not offenders, "non-ASCII in owned source:\n" + "\n".join(offenders)


def test_the_sweep_reaches_a_file_in_a_new_subpackage(tmp_path):
    """The fixture's own self-check, on a synthetic tree (F-de08ba2e).

    This is the finding's exact measured gap, both directions in one test: a genuine em dash
    written into a NEW subdirectory under core/synth/ must be found by the shipped globs, and
    must NOT be found by the non-recursive form they replaced. Asserting the miss as well as
    the hit is what makes this a proof rather than a restatement -- without it, the test would
    pass just as happily against the old patterns.
    """
    for pkg in ("contract", "synth", "optimize"):
        (tmp_path / "core" / pkg).mkdir(parents=True)
        (tmp_path / "core" / pkg / "flat.py").write_text("FLAT = 'ascii'\n", encoding="utf-8")
    (tmp_path / "core" / "plugin.py").write_text("PLUGIN = 1\n", encoding="utf-8")
    (tmp_path / "core" / "__init__.py").write_text("", encoding="utf-8")

    nested = tmp_path / "core" / "synth" / "backend" / "ollama.py"
    nested.parent.mkdir()
    # chr() keeps THIS file ASCII while the file it writes carries a real U+2014 -- the
    # em dash whose print on a cp437 console is the crash this whole section exists to stop.
    em_dash = chr(0x2014)
    nested.write_text(
        f'HINT = "install the backend {em_dash} then retry"\n', encoding="utf-8"
    )

    found = _sources_under(tmp_path)
    assert nested in found, "the shipped globs do not reach a new core/synth subpackage"

    old_patterns = ("core/contract/*.py", "core/synth/*.py", "core/optimize/*.py")
    missed = [p for pat in old_patterns for p in tmp_path.glob(pat)]
    assert nested not in missed, "fixture is not measuring the gap it claims to close"

    # and the reach is worth having: the sweep's own detector flags what lives down there.
    assert _non_ascii_offenders(nested, label="ollama.py") == ["ollama.py:1: U+2014"]
