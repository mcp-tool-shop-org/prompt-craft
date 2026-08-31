"""Fixtures that kill surviving mutants of the compound predicates.

Each test names the mutant it would have let through, and what the
wrong code does. If the fixture cannot fail, it does not belong here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcraft.core.contract.compile_questions import (
    Polarity,
    Question,
    QuestionDAG,
    compile_questions,
)
from pcraft.core.contract.loader import resolve
from pcraft.core.contract.schema import Atom, CheckType, Contract, MustNot, Severity
from pcraft.core.gate import harness
from pcraft.core.gate.thresholds import Zone
from pcraft.core.loop.retry_policy import RepairAction, RetryBudget, choose_repair
from pcraft.core.synth.visual_inventory import (
    InventoryRow,
    assert_tokens_trace,
    build_inventory,
)
from pcraft.errors import PromptCraftError
from pcraft.testing import ScriptedVerifier, passing_verifiers


def test_a_depends_on_missing_id_does_not_crash_topo_sort():
    """CQ58 drop-second: `if q.depends_on:` then index[q.depends_on] KeyErrors.

    What this looks like if wrong: a typo'd depends_on raises ValueError/KeyError
    instead of treating the atom as a root.
    """
    dag = QuestionDAG(
        contract_id="c",
        questions=[
            Question(atom_id="leaf", text="x", check_type=CheckType.vqa,
                     polarity=Polarity.affirm, severity=Severity.required, depends_on="ghost"),
        ],
    )
    order = dag.topological()
    assert [q.atom_id for q in order] == ["leaf"]


def test_an_atom_id_may_not_be_the_empty_string():
    """CQ58 drop-first: `if q.depends_on in index:` -- judged EQUIVALENT, and this fixture is
    what makes that judgement airtight rather than an assumption.

    The mutant diverges from the original on exactly one input class: some atom carries
    `depends_on=""` while another atom's `id` is also `""`. The original short-circuits on
    the falsy depends_on and never looks the parent up; the mutant finds `"" in index` and
    visits it, reordering the DAG walk. That input class was REACHABLE -- `Atom(id="", ...)`
    constructed without complaint, because no id field carried a length floor.

    What this looks like if wrong: the "equivalent, leave it" classification for
    compile_questions.py:58 rests on a schema guarantee the schema does not make.
    """
    with pytest.raises(ValidationError):
        Atom(id="", claim="a ghost", check_type=CheckType.vqa)


def test_a_must_not_id_may_not_be_the_empty_string():
    """Same input class via the other list -- compile_questions indexes both by atom_id."""
    with pytest.raises(ValidationError):
        MustNot(id="", claim="a ghost")


def test_a_contract_id_may_not_be_the_empty_string():
    with pytest.raises(ValidationError):
        Contract(id="", level="faction")


# ---------------------------------------------------------------------------
# F-7409e175 -- the length floor above counts raw characters, so it closed the empty
# string and nothing else. MEASURED before the fix: Atom(id='   ') satisfied min_length=1
# with a length of 3 and constructed untouched, as did MustNot(id=' ') and Atom(id='\t\n').
# An id nobody would call anything but blank still reached the DAG, the receipt, and the
# refusal messages that quote it back to the author.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["   ", " ", "\t\n", "\n", "\t"], ids=repr)
def test_an_atom_id_may_not_be_whitespace_only(blank):
    with pytest.raises(ValidationError):
        Atom(id=blank, claim="a ghost", check_type=CheckType.vqa)


@pytest.mark.parametrize("blank", ["   ", " ", "\t\n"], ids=repr)
def test_a_must_not_id_may_not_be_whitespace_only(blank):
    with pytest.raises(ValidationError):
        MustNot(id=blank, claim="a ghost")


@pytest.mark.parametrize("blank", ["   ", " ", "\t\n"], ids=repr)
def test_a_contract_id_may_not_be_whitespace_only(blank):
    with pytest.raises(ValidationError):
        Contract(id=blank, level="faction")


def test_an_id_with_incidental_whitespace_is_kept_exactly_as_authored():
    """The deliberate scope limit, pinned so nobody "completes" the fix by normalizing.

    Only BLANK is refused. Stripping a stored id would silently merge ids that the DAG index,
    the duplicate guard, and every dict key in this domain treat as distinct -- ' tabard' and
    'tabard' are consistently two nodes today, and that consistency is what made this finding
    narrow rather than a live defect.
    """
    atom = Atom(id=" tabard ", claim="a tabard", check_type=CheckType.vqa)
    assert atom.id == " tabard "
    contract = Contract(
        id="faction:x",
        level="faction",
        must_have=[
            Atom(id="tabard", claim="a tabard", check_type=CheckType.vqa),
            atom,
        ],
    )
    assert [a.id for a in contract.must_have] == ["tabard", " tabard "]


def test_the_dag_index_can_never_contain_an_empty_key(sprite_example):
    """The property the three constraints above buy, stated once at the DAG level: because
    no id can be empty, `"" in index` is False for every constructible contract, so the
    CQ58 drop-first mutant cannot diverge from the original."""
    _s, resolved, _t, _c = sprite_example
    dag = compile_questions(resolved)
    assert all(q.atom_id for q in dag.questions)


def test_a_character_with_no_extends_resolves_as_itself():
    """L64 drop-extends: level==character and extends is None must not lookup(None)."""
    child = Contract(id="c:orphan", level="character", extends=None, must_have=[])
    r = resolve(child, lambda _i: None)
    assert r.lineage == ["c:orphan"]
    assert r.must_have == []


def test_a_faction_with_an_extends_still_resolves_as_a_faction():
    """L64 drop-faction: an accidental extends on a faction must not merge."""
    faction = Contract(
        id="f:oops", level="faction", extends="f:other",
        must_not=[MustNot(id="no_x", claim="an x")],
    )
    r = resolve(faction, lambda _i: None)
    assert r.level == "faction"
    assert r.lineage == ["f:oops"]


def test_optional_unconfirmed_atoms_do_not_enter_uncertain_required(sprite_example):
    """H65 drop _counts: an optional SKIPPED atom is not a required-unconfirmed.

    What this looks like if wrong: optional noise shows up in the human-band list.
    """
    _s, resolved, thresholds, _c = sprite_example
    for mn in resolved.must_not:
        mn.severity = Severity.optional
    dag = compile_questions(resolved)

    def scorer(q):
        if q.polarity.value == "negate":
            return None
        return 0.95

    t = harness.evaluate(dag, "x.png", passing_verifiers(scores=scorer), thresholds, generator_family="stable-diffusion")
    assert t.overall is Zone.PASS
    assert not [v for v in t.uncertain_required() if v.polarity.value == "negate"]


def test_an_optional_score_does_not_mean_the_gate_ran(sprite_example):
    """H69 drop _counts: optional scores must not fill scored_required.

    What this looks like if wrong: every required atom SKIPPED, one optional
    scored, could_not_run is False and UNAVAILABLE becomes UNCERTAIN.
    """
    _s, resolved, thresholds, _c = sprite_example
    for atom in resolved.must_have:
        atom.severity = Severity.optional
    for mn in resolved.must_not:
        mn.severity = Severity.optional
    # one leftover required so the census is not empty
    resolved.must_have[0].severity = Severity.required
    dag = compile_questions(resolved)

    def scorer(q):
        if q.atom_id == resolved.must_have[0].id:
            return None
        return 0.95

    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier(scorer)}, thresholds, generator_family="stable-diffusion")
    assert t.could_not_run() is True
    assert t.overall is Zone.UNAVAILABLE


def test_parent_gate_does_not_keyerror_on_an_unknown_depends_on(sprite_example):
    """H110 drop-second: depends_on set but not in verdicts must not KeyError."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    dag.questions[0].depends_on = "ghost"
    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier()}, thresholds, generator_family="stable-diffusion")
    assert t.verdicts  # completed; did not raise


def test_tier0_does_not_escalate_to_tier2(sprite_example):
    """H134 drop-tier: T0 UNCERTAIN must not call T2.

    What this looks like if wrong: a cheap screen miss is re-scored by DSG.
    """
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    called = []

    class T0:
        verifier_id = "t0"
        version = "v0"
        family = "siglip"
        tier = 0

        def score(self, _p, q):
            return 0.60 if q.check_type.value in ("siglip2", "palette") else 0.95

    class T2:
        verifier_id = "t2"
        version = "v0"
        family = "dsg-qg"
        tier = 2

        def score(self, _p, q):
            called.append(q.atom_id)
            return 0.99

    t = harness.evaluate(dag, "x.png", {0: T0(), 1: ScriptedVerifier(), 2: T2()}, thresholds, generator_family="stable-diffusion")
    assert called == []
    assert t.overall in (Zone.PASS, Zone.UNCERTAIN)


def test_exhausted_is_false_while_rerolls_remain():
    """R53 drop-rerolls: inpaints=0, reprompts=0, rerolls=3 is not exhausted."""
    b = RetryBudget(inpaints=0, reprompts=0, rerolls=3)
    assert b.exhausted() is False


def test_a_single_fail_does_not_take_the_multi_fail_resynth(sprite_example):
    """R90 invert >1: one failed leaf with budget is INPAINT, not RESYNTH."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(dag, "x.png", {1: ScriptedVerifier({"skin": 0.05})}, thresholds, generator_family="stable-diffusion")
    action = choose_repair(t, RetryBudget(reprompts=2, inpaints=1), dag)
    assert action is RepairAction.INPAINT_REGION


def test_resynth_is_not_chosen_when_the_reprompt_budget_is_gone(sprite_example):
    """R90 drop budget: two fails + reprompts=0 must not RESYNTH."""
    _s, resolved, thresholds, _c = sprite_example
    dag = compile_questions(resolved)
    t = harness.evaluate(
        dag, "x.png", {1: ScriptedVerifier({"skin": 0.05, "weapon": 0.05})}, thresholds, generator_family="stable-diffusion"
    )
    action = choose_repair(t, RetryBudget(reprompts=0, inpaints=0, rerolls=1), dag)
    assert action is not RepairAction.RESYNTH_REWEIGHT


def test_a_one_character_atom_does_not_license_every_segment():
    """V75 tok-in-norm without a length floor: token 'a' is in 'artstation'.

    What this looks like if wrong: assert_tokens_trace admits the prose dump.
    """
    tiny = [InventoryRow(atom_id="x", depictable=True, front_load_rank=0, token="a")]
    with pytest.raises(PromptCraftError) as exc:
        assert_tokens_trace("epic cinematic masterpiece, trending on artstation", tiny)
    assert exc.value.code == "SYNTH_PROSE_DUMP"


def test_a_superstring_of_a_long_claim_still_traces(sprite_example):
    """The intended tok-in-norm arm, with a phrase long enough to be a phrase."""
    _s, resolved, _t, _c = sprite_example
    inventory = build_inventory(resolved)
    assert_tokens_trace("really a grey-ash tabard worn over the torso today", inventory)
