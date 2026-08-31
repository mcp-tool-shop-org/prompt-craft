"""F-GATE-FEAT-001 / F-LOOP-FEAT-003 — contrastive human checkpoint.

UNCERTAINTY_GATED_HUMANS is a zone plus this artifact: you probably thought X;
the gate chose Y. GPU-free.
"""

from __future__ import annotations

import json

import pytest

from pcraft.core.contract.compile_questions import Polarity, compile_questions
from pcraft.core.contract.schema import Severity
from pcraft.core.gate.checkpoint import build_checkpoint
from pcraft.core.gate.harness import AtomVerdict, GateTranscript, TierCensus
from pcraft.core.gate.thresholds import Zone
from pcraft.core.receipt.asset_record import load as load_record
from pcraft.core.receipt.asset_record import receipt_paths
from pcraft.core.receipt.disposition import (
    DISPOSITIONS_DIRNAME,
    dispositions_for,
    load_disposition,
    record_disposition,
)
from pcraft.errors import PromptCraftError
from pcraft.sample import load_sprite_example, run_mock_loop


def test_uncertain_score_is_contrastive_not_a_zone_name_only():
    _s, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    transcript = GateTranscript(
        contract_id=resolved.id,
        overall=Zone.UNCERTAIN,
        verdicts=[
            AtomVerdict(
                atom_id="face",
                polarity=Polarity.affirm,
                severity=Severity.required,
                score=0.55,
                zone=Zone.UNCERTAIN,
                tier_used=1,
                verifier_id="v",
                reason="near miss",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )
    ck = build_checkpoint(transcript, dag)
    text = ck.text.lower()
    assert "you probably thought" in text
    assert "i chose" in text or "i left" in text
    assert "face" in text
    assert "0.55" in ck.text
    assert ck.lines[0].atom_id == "face"
    assert ck.thought
    assert ck.chose


def test_escalated_loop_carries_the_checkpoint(tmp_path):
    from pcraft.core.loop import orchestrate
    from pcraft.core.loop.orchestrate import LoopConfig
    from pcraft.core.synth.signature import TemplateSynthesizer
    from pcraft.testing import StubGenerator, passing_verifiers

    _s, resolved, thresholds, compiled = load_sprite_example()
    result = orchestrate.run(
        resolved,
        TemplateSynthesizer(compiled),
        StubGenerator(out_dir=tmp_path / "_stub_images"),
        passing_verifiers(scores={"face": 0.55}),
        thresholds,
        config=LoopConfig(thresholds_version=thresholds.version, records_dir=str(tmp_path)),
    )
    assert result.decision == "escalated"
    assert result.checkpoint is not None
    assert "face" in result.checkpoint.text
    assert "you probably thought" in result.checkpoint.text.lower()
    assert result.reason == result.checkpoint.text


def test_bound_run_has_no_checkpoint(tmp_path):
    result = run_mock_loop(records_dir=str(tmp_path))
    assert result.decision == "bound"
    assert result.checkpoint is None


# --------------------------------------------------------------------------- F-2c7b997a
# build_checkpoint derived its entire content from Zone facts and never read tier_census, so an
# escalation whose cause is not a Zone produced an artifact structurally incapable of naming the
# cause -- and that artifact becomes OrchestrationResult.reason, which the CLI prints verbatim.


def _required_pass(atom_id: str) -> AtomVerdict:
    return AtomVerdict(
        atom_id=atom_id,
        polarity=Polarity.affirm,
        severity=Severity.required,
        score=0.95,
        zone=Zone.PASS,
        tier_used=1,
        tiers_consulted=[1],
        verifier_id="v",
        reason="score 0.9500 -> PASS",
    )


def test_the_checkpoint_names_a_short_tier_census():
    """A transcript that rolls up PASS on a 1-of-2 census escalates, and the human artifact used
    to read 'You probably thought nothing needed a human. I escalated (PASS).' with zero lines --
    while error_from_transcript beside it named the census, the required tiers and the executed
    ones."""
    transcript = GateTranscript(
        contract_id="faction:ashen-pact",
        overall=Zone.PASS,
        verdicts=[_required_pass("tabard")],
        tier_census=TierCensus(required=[0, 1], executed=[1]),
    )
    ck = build_checkpoint(transcript)
    text = ck.text.lower()
    assert "1 of 2" in text or "tiers" in text, "the artifact must be able to state a non-Zone cause"
    # ⚑ REWRITTEN IN PLACE (F-6acc1597). This asserted the Python list repr -- '[0, 1]' and
    # '[1]' -- which was one of the four spellings of the tier census this product shipped, and
    # the two that printed raw container repr into a human artifact. The census now renders in
    # the SAME notation as the verdict rows a reader sees three lines away in the transcript.
    assert "required T0 T1" in ck.text and "executed T1" in ck.text
    assert ck.lines, "a checkpoint with no lines at all is not a checkpoint"
    ck.text.encode("cp437")  # the CLI prints this verbatim on a legacy console


def test_the_checkpoint_does_not_call_a_fully_scored_run_a_missing_score():
    """The reachable door to the same empty artifact: every atom optional, every atom scored,
    every atom passed -- and the text said 'You probably thought a missing score was nothing to
    look at.' That sentence is not merely uninformative, it is false."""
    verdicts = [
        AtomVerdict(
            atom_id="tabard",
            polarity=Polarity.affirm,
            severity=Severity.optional,
            score=0.95,
            zone=Zone.PASS,
            tier_used=1,
            tiers_consulted=[1],
            verifier_id="v",
            reason="score 0.9500 -> PASS",
        )
    ]
    transcript = GateTranscript(
        contract_id="faction:ashen-pact",
        overall=Zone.UNAVAILABLE,
        verdicts=verdicts,
        tier_census=TierCensus(required=[], executed=[]),
    )
    ck = build_checkpoint(transcript)
    assert "missing score" not in ck.text.lower(), "every verifier scored on this run"
    assert "required" in ck.text.lower()
    assert ck.lines, "the artifact has to say something a human can act on"
    ck.text.encode("cp437")


def test_a_normal_uncertain_run_still_reads_the_way_it_did():
    """The common path is not allowed to regress into census prose."""
    _s, resolved, _t, _c = load_sprite_example()
    dag = compile_questions(resolved)
    transcript = GateTranscript(
        contract_id=resolved.id,
        overall=Zone.UNCERTAIN,
        verdicts=[
            AtomVerdict(
                atom_id="tabard",
                polarity=Polarity.affirm,
                severity=Severity.required,
                score=0.55,
                zone=Zone.UNCERTAIN,
                tier_used=1,
                tiers_consulted=[1],
                verifier_id="v",
                reason="near miss",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )
    ck = build_checkpoint(transcript, dag)
    assert "tiers" not in ck.text.lower(), "a complete census must add no line"
    assert len(ck.lines) == 1


# --------------------------------------------------------------------------- F-a6078c7f
# build_checkpoint already had the content as STRUCTURE (one ContrastiveLine per flagged atom)
# and then flattened all of it with ' '.join into ``text`` -- which becomes
# OrchestrationResult.reason. MEASURED: 974 characters, zero newlines, one unbroken parenthesis
# on the operator's screen, while the formatted transcript printed twenty lines below it was
# fully structured. The human decision point was the one artifact that was not.
#
# ⚑ COMMENT UPDATED (wave 10, coordinator note). This block described the render that WRAPPED
# the checkpoint at the time: ``cli._print_result`` printed ``decision: ESCALATED ({reason})``,
# so a multi-line reason landed inside a parenthesis opened on line 1 -- which is why the
# "unbroken parenthesis" above is phrased the way it is. The cli-ux domain has since split
# that composition: the decision line now stands alone, and the checkpoint block prints
# indented beneath it. The defect this section pins is unchanged and lives entirely in
# build_checkpoint -- what changed is that the artifact is no longer being rendered into a
# parenthesis, so its structure survives to the screen. See F-6ddb888b below, which fixes the
# width of the per-atom lines this fix left at 188-230 characters.

_ALL_REQUIRED = ("tabard", "sigil", "palette", "skin", "weapon", "face")


def _escalating_run(tmp_path):
    return run_mock_loop(records_dir=str(tmp_path), verifier_scores=dict.fromkeys(_ALL_REQUIRED, 0.05))


def test_the_checkpoint_is_structured_text_not_one_unbroken_line(tmp_path):
    """MEASURED red: len(reason) == 974 and reason.count('\n') == 0."""
    result = _escalating_run(tmp_path)
    text = result.checkpoint.text
    assert result.reason == text, "the CLI prints this verbatim; they must stay the same object"
    assert "\n" in text, "the UNCERTAINTY_GATED_HUMANS artifact shipped as one 974-character line"
    body = text.splitlines()
    # ⚑ REWRITTEN IN PLACE (F-6ddb888b). This asserted `1 + len(lines)` -- one header line plus
    # one line per flagged atom -- which is the shape whose per-atom lines then measured 188-230
    # characters each, i.e. 3 visual lines apiece at 80 columns. The structure is now one line
    # per FIELD, so the count assertion becomes: every flagged atom is represented, and nothing
    # is flattened back into a run-on.
    assert len(body) > 1 + len(result.checkpoint.lines), (
        "each flagged atom renders its claim/thought/chose as separate lines -- the structure "
        "ContrastiveLine already carried as separate typed fields"
    )
    for line in result.checkpoint.lines:
        assert any(line.atom_id in row for row in body), f"{line.atom_id} is not in the artifact"


def test_the_summary_is_distinguishable_from_the_detail(tmp_path):
    """The header pair and the per-atom lines used to be joined identically, so nothing
    separated the summary from the detail.

    ⚑ REWRITTEN IN PLACE (F-6ddb888b). The pair itself was ONE line joined by a space, so the
    contrastive pair the standard is named for did not contrast visually either; it is now two
    lines, and the per-atom entries are set off by indent and a blank line rather than by a
    '  - ' bullet that governed only the first third of a 210-character run.
    """
    result = _escalating_run(tmp_path)
    thought, chose, *rows = result.checkpoint.text.splitlines()
    assert thought == result.checkpoint.thought
    assert chose == result.checkpoint.chose
    assert rows and all(r.startswith("  ") or not r.strip() for r in rows), (
        "a per-atom line has to be marked as one"
    )


def test_a_claim_that_is_already_a_question_does_not_get_a_full_stop(tmp_path):
    """MEASURED red: 'worn over the torso?.' appeared six times in one run."""
    result = _escalating_run(tmp_path)
    assert "?." not in result.checkpoint.text


def test_the_checkpoint_still_survives_a_legacy_console(tmp_path):
    """F-a6acaab1's guarantee is unchanged by the separator: a newline is ASCII."""
    result = _escalating_run(tmp_path)
    result.checkpoint.text.encode("cp437")
    result.reason.encode("ascii")


# --------------------------------------------------------------------------- F-b1b29cef
# The operator standing at the checkpoint is being asked to accept or repair, and the MARGIN is
# the input to that decision. MEASURED: skin at 0.79 and at 0.41 -- one hundredth from PASS and
# one hundredth from FAIL under vqa 0.80/0.40 -- produced sentences differing only in the number.


def _uncertain_transcript(score: float, *, polarity=Polarity.affirm, band_key="vqa"):
    return GateTranscript(
        contract_id="char:ashen-reaver",
        overall=Zone.UNCERTAIN,
        verdicts=[
            AtomVerdict(
                atom_id="skin",
                polarity=polarity,
                severity=Severity.required,
                score=score,
                zone=Zone.UNCERTAIN,
                tier_used=1,
                tiers_consulted=[1],
                verifier_id="scripted.vqa.v0",
                band_key=band_key,
                reason=f"score {score:.4f} -> UNCERTAIN (band {band_key})",
            )
        ],
        tier_census=TierCensus(required=[0, 1], executed=[0, 1]),
    )


def test_the_checkpoint_prints_the_band_that_graded_the_score():
    _s, _r, table, _c = load_sprite_example()
    ck = build_checkpoint(_uncertain_transcript(0.79), None, table)
    assert "0.79" in ck.text
    assert "0.80" in ck.text and "0.40" in ck.text, (
        "the margin is the input to accept-or-repair; without the band the operator has to open "
        "sprite.calibration.json to learn whether this was nearly a bind or nearly a failure"
    )


def test_a_near_pass_and_a_near_fail_no_longer_read_the_same():
    _s, _r, table, _c = load_sprite_example()
    near_pass = build_checkpoint(_uncertain_transcript(0.79), None, table).text
    near_fail = build_checkpoint(_uncertain_transcript(0.41), None, table).text
    assert near_pass != near_fail
    for text in (near_pass, near_fail):
        assert "0.80" in text and "0.40" in text


def test_a_negate_atoms_band_is_not_printed_backwards():
    """For a must_not probe the band inverts: a HIGH 'is it present?' score is the FAIL. Printing
    'passes at 0.10' for a negate atom would be a confident wrong statement, which is the class
    of defect the band was added to remove."""
    _s, _r, table, _c = load_sprite_example()
    ck = build_checkpoint(
        _uncertain_transcript(0.05, polarity=Polarity.negate, band_key="siglip2"), None, table
    )
    line = ck.text
    assert "0.10" in line and "0.01" in line
    assert "passes at 0.10" not in line, "that is the affirm reading of a negate band"


def test_no_table_renders_exactly_what_it_rendered_before():
    """The argument is optional and additive: a caller without a table is unchanged."""
    _s, _r, _table, _c = load_sprite_example()
    without = build_checkpoint(_uncertain_transcript(0.79))
    assert "0.79" in without.text
    assert "0.80" not in without.text and "0.40" not in without.text


# --------------------------------------------------------------------------------------------
# F-6ddb888b -- F-a6078c7f broke the 974-character single line into one line per flagged atom,
# and each of THOSE lines is 188-230 characters, so the structure it restored is destroyed again
# at the first real width. MEASURED on the shipped example with the five required atoms scripted
# to 0.60 and the real threshold table passed: the header pair is 80 chars and the five per-atom
# entries measure 209, 230, 188, 214 and 198 -- every one of them 3 visual lines at 80 columns
# and 2 at 120, wrapping to column 0. So the '  - ' bullet governed only the first third of each
# entry, and across five atoms the operator saw 16 visual lines carrying 5 bullets.
#
# ContrastiveCheckpoint ALREADY holds the content as structure -- ContrastiveLine carries claim,
# thought and chose as separate typed fields -- and the generator flattened all three back into
# one sentence. Three consequences per STANDARDS #5: the contrastive PAIR was joined by a
# mid-sentence '; ' at identical visual weight, the atom_id was repeated three times per entry
# and the score twice, and `text` becomes OrchestrationResult.reason, so the wrapped entries
# landed inside a parenthesis opened on line 1.
# --------------------------------------------------------------------------------------------

_CHECKPOINT_WIDTH = 80
_ENTRY_INDENT = 2
_FIELD_INDENT = 4


def test_no_checkpoint_line_overflows_a_standard_terminal(tmp_path):
    result = _escalating_run(tmp_path)
    for line in result.checkpoint.text.splitlines():
        assert len(line) <= _CHECKPOINT_WIDTH, (
            f"a {len(line)}-column line wraps to column 0 inside a parenthesis the CLI opened "
            f"on line 1: {line!r}"
        )


def test_the_contrastive_pair_contrasts_vertically(tmp_path):
    """The thing the standard is named for was joined by a mid-sentence '; ' at identical
    visual weight, so finding the decision meant parsing a semicolon 100 characters in."""
    result = _escalating_run(tmp_path)
    ck = result.checkpoint
    head = ck.text.splitlines()[:2]
    assert head == [ck.thought, ck.chose], (
        "the summary pair is two lines, so what-you-thought and what-I-chose are the same "
        f"kind of thing at the same indent: {head!r}"
    )


def test_each_flagged_atom_renders_its_fields_as_labelled_lines(tmp_path):
    result = _escalating_run(tmp_path)
    lines = result.checkpoint.text.splitlines()
    heads = [ln for ln in lines if ln.startswith("  ") and not ln.startswith("   ")]
    assert len(heads) == len(result.checkpoint.lines), (
        "one head line per flagged atom -- the structure build_checkpoint already had"
    )
    labels = [
        ln.strip().split()[0]
        for ln in lines
        if ln.startswith(" " * _FIELD_INDENT) and ln[_FIELD_INDENT:_FIELD_INDENT + 1].strip()
    ]
    assert set(labels) <= {"claim:", "thought:", "chose:"}, f"one label vocabulary, saw {labels}"
    for want in ("claim:", "thought:", "chose:"):
        assert labels.count(want) == len(result.checkpoint.lines), (
            f"every flagged atom renders its {want} on its own line"
        )


def test_the_labels_form_a_column_so_the_labels_do_the_contrasting(tmp_path):
    """The labels are padded to one width, so every VALUE starts in the same column and the
    eye can run down claim / thought / chose without re-finding the text each time. That is
    what replaced a mid-sentence '; ' carrying the contrast at identical visual weight."""
    result = _escalating_run(tmp_path)
    field_lines = [
        ln for ln in result.checkpoint.text.splitlines()
        if ln.startswith(" " * _FIELD_INDENT)
        and ln[_FIELD_INDENT:_FIELD_INDENT + 1].strip()
        and ln.strip().split()[0].endswith(":")
    ]
    assert field_lines
    value_columns = {len(ln) - len(ln[_FIELD_INDENT:].lstrip()) for ln in field_lines}
    assert value_columns == {_FIELD_INDENT}, "every label starts at the one field indent"
    starts = {
        len(ln) - len(ln.split(":", 1)[1].lstrip()) for ln in field_lines
    }
    assert len(starts) == 1, f"the values must line up in one column, saw {starts}"


def test_a_blank_line_separates_one_atom_entry_from_the_next(tmp_path):
    """The cheapest ASCII separator there is, and the one this artifact had none of."""
    result = _escalating_run(tmp_path)
    lines = result.checkpoint.text.splitlines()
    blanks = [i for i, ln in enumerate(lines) if not ln.strip()]
    assert len(blanks) == len(result.checkpoint.lines), (
        "one blank line ahead of each atom entry, including the first (which separates the "
        "entries from the summary pair)"
    )


def test_the_generated_sentences_stop_repeating_the_id_and_the_score(tmp_path):
    """'tabard UNCERTAIN 0.60: you probably thought tabard was close enough; I left tabard in
    the human band (0.60; ...)' -- the id three times, the score twice, competing with the
    margin numbers F-b1b29cef added for exactly this decision."""
    result = _escalating_run(tmp_path)
    for line in result.checkpoint.lines:
        if line.atom_id in ("tier_census", "contract"):
            continue
        assert line.atom_id not in line.thought, (
            f"the id already heads the entry: {line.thought!r}"
        )
        assert line.atom_id not in line.chose, f"the id already heads the entry: {line.chose!r}"
        if line.score is not None:
            assert f"{line.score:.2f}" not in line.chose, (
                f"the margin already heads the entry: {line.chose!r}"
            )


def test_the_head_line_still_carries_the_decision_inputs(tmp_path):
    """id, zone, score and band on ONE scannable line -- the accept-or-repair inputs."""
    result = _escalating_run(tmp_path)
    heads = [
        ln for ln in result.checkpoint.text.splitlines()
        if ln.startswith("  ") and not ln.startswith("   ")
    ]
    first = heads[0]
    assert result.checkpoint.lines[0].atom_id in first
    assert result.checkpoint.lines[0].zone in first


# --------------------------------------------------------------------------------------
# F-2b04f0b8 -- the other half of the checkpoint. The loop builds a genuine contrastive
# checkpoint, persists it in the receipt, prints it and returns decision='escalated'. Then
# the trail stops: there was no verb and no format for what the Director decided, so the
# Director's judgment was the one input to the pipeline that never became provenance.
#
# The product's own model named the gap: the `escalation-ticket` compensator declares owner
# "pipeline (Director resolves)" and post-rollback state "ticket closed with a resolution
# note" -- and there was no ticket, no note, and no place to put one.
#
# The design ruling: a SIBLING record beside the receipt, never a mutation of it.
# --------------------------------------------------------------------------------------

_AT = "2026-08-31T09:00:00Z"


def _escalated(tmp_path):
    result = _escalating_run(tmp_path)
    assert result.decision == "escalated" and result.record is not None
    return result


def test_a_disposition_never_touches_the_receipt_it_resolves(tmp_path):
    """persist()'s "a receipt already on disk is never replaced" rule (F-a99ec99e) and
    STABILITY.md's schema_version "1" promise both hold: the resolution is a NEW file
    referencing record_id, and STATE_REPLAY_DRIFT's own hint ends "Do not edit the receipt"."""
    result = _escalated(tmp_path)
    receipt = tmp_path / f"{result.record.record_id}.json"
    before = receipt.read_bytes()

    record_disposition(
        result.record, tmp_path, resolution="accepted", resolved_by="director",
        note="looked at the plate; the tabard reads", resolved_at=_AT,
    )

    assert receipt.read_bytes() == before, "the receipt is the record of a decision, not a draft"
    reloaded = load_record(receipt)
    assert reloaded.decision == "escalated"
    assert reloaded.schema_version == "1"


def test_a_disposition_is_invisible_to_every_reader_of_the_records_dir(tmp_path):
    """The sibling must not land where regrade_dir / the index would try to load it as a
    receipt, and must not be able to collide with persist()'s O_EXCL target."""
    from pcraft.core.gate.regrade import regrade_dir
    from pcraft.sample import load_sprite_example

    result = _escalated(tmp_path)
    before = [str(p) for p in receipt_paths(tmp_path)]
    written = record_disposition(
        result.record, tmp_path, resolution="accepted", resolved_by="director",
        resolved_at=_AT,
    )

    assert written.parent.name == DISPOSITIONS_DIRNAME
    assert written.parent.parent == tmp_path
    assert [str(p) for p in receipt_paths(tmp_path)] == before
    _s, _r, table, _c = load_sprite_example()
    assert len(regrade_dir(tmp_path, table)) == 1, "the sweep still sees exactly one receipt"


def test_a_second_decision_accumulates_rather_than_replacing_the_first(tmp_path):
    """The same rule _record_id was widened for: a human who looks twice leaves two entries,
    and neither write can destroy the other."""
    result = _escalated(tmp_path)
    first = record_disposition(
        result.record, tmp_path, resolution="deferred", resolved_by="director",
        resolved_at="2026-08-31T09:00:00Z",
    )
    second = record_disposition(
        result.record, tmp_path, resolution="accepted", resolved_by="director",
        resolved_at="2026-08-31T11:30:00Z",
    )
    assert first != second
    assert first.exists() and second.exists()

    entries = dispositions_for(tmp_path, result.record.record_id)
    assert [d.resolution for d in entries] == ["deferred", "accepted"]
    assert load_disposition(first).resolution == "deferred"


def test_the_same_decision_at_the_same_instant_is_a_refusal_not_an_overwrite(tmp_path):
    result = _escalated(tmp_path)
    record_disposition(result.record, tmp_path, resolution="accepted",
                       resolved_by="director", resolved_at=_AT)
    with pytest.raises(PromptCraftError) as exc:
        record_disposition(result.record, tmp_path, resolution="rejected",
                           resolved_by="director", resolved_at=_AT)
    assert exc.value.code == "IO_DISPOSITION_EXISTS"


def test_recording_a_disposition_requires_its_named_compensator(tmp_path):
    """NAMED_COMPENSATORS, no skip: an irreversible write is not performed unless a named undo
    with an owner is registered FIRST, exactly like records-write and bind-to-canon."""
    from pcraft.core.loop.compensators import CompensatorRegistry, default_registry

    result = _escalated(tmp_path)
    assert "disposition-write" in default_registry().actions()
    comp = default_registry().get("disposition-write")
    assert comp.owner and comp.post_state

    with pytest.raises(PromptCraftError) as exc:
        record_disposition(result.record, tmp_path, resolution="accepted",
                           resolved_by="director", resolved_at=_AT,
                           compensators=CompensatorRegistry())
    assert exc.value.code == "STATE_NO_COMPENSATOR"
    assert not (tmp_path / DISPOSITIONS_DIRNAME).exists(), "the check runs BEFORE the write"


def test_a_bound_receipt_has_nothing_for_a_human_to_resolve(tmp_path):
    """UNCERTAINTY_GATED_HUMANS: the resolution path is evidence a human decided at the
    checkpoint, not a general-purpose annotation channel."""
    from pcraft.sample import run_mock_loop

    bound = run_mock_loop(records_dir=str(tmp_path))
    assert bound.decision == "bound"
    with pytest.raises(PromptCraftError) as exc:
        record_disposition(bound.record, tmp_path, resolution="accepted",
                           resolved_by="director", resolved_at=_AT)
    assert exc.value.code == "INPUT_DISPOSITION_TARGET"


def test_a_decision_with_no_human_on_it_is_refused(tmp_path):
    """A resolution path must not become a way to auto-accept. An unattributed disposition is
    not evidence that a human decided anything."""
    result = _escalated(tmp_path)
    with pytest.raises(PromptCraftError) as exc:
        record_disposition(result.record, tmp_path, resolution="accepted",
                           resolved_by="   ", resolved_at=_AT)
    assert exc.value.code == "INPUT_DISPOSITION_ACTOR"


def test_an_unknown_resolution_is_refused(tmp_path):
    result = _escalated(tmp_path)
    with pytest.raises(PromptCraftError) as exc:
        record_disposition(result.record, tmp_path, resolution="approved-ish",
                           resolved_by="director", resolved_at=_AT)
    assert exc.value.code == "INPUT_DISPOSITION_RESOLUTION"


def test_the_timestamp_is_injectable_so_the_trail_is_deterministic(tmp_path):
    """PIN_PER_STEP's reason, applied here: a stamp drawn from a wall clock does not replay."""
    result = _escalated(tmp_path)
    path = record_disposition(result.record, tmp_path, resolution="accepted",
                              resolved_by="director", resolved_at=_AT)
    entry = load_disposition(path)
    assert entry.resolved_at == _AT
    assert entry.record_id == result.record.record_id
    assert entry.contract_hash == result.record.contract_hash
    assert entry.thresholds_fingerprint == result.record.thresholds_fingerprint
    assert entry.checkpoint_digest, "a disposition names the artifact the human was shown"


def test_the_disposition_pins_the_checkpoint_the_human_actually_read(tmp_path):
    """"I accepted this" is only provenance if it says what "this" was."""
    from pcraft.core.receipt.disposition import checkpoint_digest

    result = _escalated(tmp_path)
    path = record_disposition(result.record, tmp_path, resolution="accepted",
                              resolved_by="director", resolved_at=_AT)
    assert load_disposition(path).checkpoint_digest == checkpoint_digest(result.record)


def test_the_index_joins_a_disposition_to_the_receipt_it_resolves(tmp_path):
    from pcraft.core.receipt.index import RecordQuery, scan

    result = _escalated(tmp_path)
    record_disposition(result.record, tmp_path, resolution="accepted",
                       resolved_by="director", note="the tabard reads", resolved_at=_AT)

    index = scan(tmp_path)
    row = index.rows[0]
    assert row.record_id == result.record.record_id
    assert [d.resolution for d in row.dispositions] == ["accepted"]
    assert row.latest_resolution == "accepted"
    assert index.query(RecordQuery(resolution="accepted")) == [row]
    assert index.query(RecordQuery(resolution="rejected")) == []
    assert index.summary().by_resolution == {"accepted": 1}


def test_an_unattached_disposition_is_reported_rather_than_dropped(tmp_path):
    """The scan never aborts and never silently omits. A disposition naming a receipt this
    directory does not hold is a fact the operator has to be told."""
    from pcraft.core.receipt.index import scan

    result = _escalated(tmp_path)
    written = record_disposition(result.record, tmp_path, resolution="accepted",
                                 resolved_by="director", resolved_at=_AT)
    data = json.loads(written.read_text(encoding="utf-8"))
    data["record_id"] = "a-receipt-that-is-not-here"
    written.write_text(json.dumps(data), encoding="utf-8")

    index = scan(tmp_path)
    assert index.rows[0].dispositions == []
    assert len(index.stray_dispositions) == 1
    assert index.stray_dispositions[0].endswith(written.name)


def test_a_damaged_disposition_does_not_abort_the_scan(tmp_path):
    from pcraft.core.receipt.index import scan

    result = _escalated(tmp_path)
    d = tmp_path / DISPOSITIONS_DIRNAME
    d.mkdir(exist_ok=True)
    (d / "broken.json").write_text("{", encoding="utf-8")

    index = scan(tmp_path)
    assert index.rows[0].record_id == result.record.record_id
    assert len(index.stray_dispositions) == 1


def test_a_disposition_from_the_future_is_refused_by_its_own_code(tmp_path):
    """The same reader contract the receipt has: well formed and newer is not corrupt."""
    result = _escalated(tmp_path)
    path = record_disposition(result.record, tmp_path, resolution="accepted",
                              resolved_by="director", resolved_at=_AT)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = "99"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PromptCraftError) as exc:
        load_disposition(path)
    assert exc.value.code == "IO_DISPOSITION_SCHEMA_UNSUPPORTED"
    assert exc.value.exit_code == 1, "a file from the future is user input, exit 1"


def test_a_disposition_changes_neither_the_decision_literal_nor_the_exit_code(tmp_path):
    """OrchestrationResult.decision is a Literal narrowed on purpose (F-a250372c) and the
    covered exit-code contract must hold: "a human accepted this" must never become exit 0
    from `bind`, because that would make the gate's refusal retroactively invisible."""
    from pcraft.core.gate.exit_contract import error_from_transcript
    from pcraft.core.loop.orchestrate import OrchestrationResult

    result = _escalated(tmp_path)
    before = error_from_transcript(result.record.gate_transcript)
    record_disposition(result.record, tmp_path, resolution="accepted",
                       resolved_by="director", resolved_at=_AT)

    assert set(OrchestrationResult.model_fields["decision"].annotation.__args__) == {
        "bound", "escalated"
    }
    reloaded = load_record(tmp_path / f"{result.record.record_id}.json")
    assert reloaded.decision == "escalated"
    after = error_from_transcript(reloaded.gate_transcript)
    assert after.code == before.code and after.exit_code == before.exit_code != 0
