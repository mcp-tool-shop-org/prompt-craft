"""The sprite identity sub-gate: measure, do not promote, do not delete.

Injectable similarity, no GPU. The Director ruled identity gates nothing.
This module computes CLIP-I cosine and routes failures to reference-anchored
inpaint. These tests record what it does; they do not decide whether it should.
"""

from __future__ import annotations

import pytest

from pcraft.core.gate.family_guard import assert_distinct_families, normalize_family
from pcraft.domains.image.subdomains.sprite import SpriteSubdomain
from pcraft.domains.image.subdomains.sprite.identity_subgate import IdentitySubGate
from pcraft.errors import PromptCraftError


def test_the_subdomain_factory_returns_the_same_object():
    """SpriteSubdomain.identity_subgate() was a factory nothing called."""
    g = SpriteSubdomain().identity_subgate(similarity=lambda _a, _b: 1.0)
    assert isinstance(g, IdentitySubGate)
    assert g.floor == 0.55


def test_defaults_are_hardcoded_and_unattributed():
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    assert g.floor == 0.55
    assert g.max_variance == 0.05


def test_a_constant_embedder_just_above_the_floor_passes():
    """The arm that does nothing: every view scores the same number.

    0.56 / variance 0 is inside the pass rectangle. A dead embedder that
    returns a constant above the floor looks identical to a perfect arm
    at these thresholds.
    """
    g = IdentitySubGate(similarity=lambda _a, _b: 0.56)
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png", "left": "l.png"})
    assert r is not None
    assert r.passed is True
    assert r.min_similarity == 0.56
    assert r.variance == 0.0


def test_a_perfect_match_also_passes():
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png"})
    assert r is not None and r.passed is True
    assert r.min_similarity == 1.0


def test_just_under_the_floor_fails():
    """What this looks like if the floor is ignored: 0.549 would pass."""
    g = IdentitySubGate(similarity=lambda _a, _b: 0.549)
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png"})
    assert r is not None
    assert r.passed is False
    assert "floor" in r.reason


def test_one_drifted_view_fails_on_the_floor_not_the_variance():
    g = IdentitySubGate(
        similarity=lambda _a, b: {"f.png": 0.95, "b.png": 0.95, "l.png": 0.40}[b]
    )
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png", "left": "l.png"})
    assert r is not None
    assert r.passed is False
    assert r.min_similarity == 0.40


def test_variance_arm_does_not_fire_inside_the_floor_rectangle():
    """0.99 and 0.55 both clear the floor; variance is 0.0484, still under 0.05.

    The variance arm barely moves inside the pass rectangle. A palette
    shift that StyleID would call identity-drift can sit in this band.
    """
    g = IdentitySubGate(similarity=lambda _a, b: {"f.png": 0.99, "b.png": 0.55}[b])
    r = g.evaluate("plate.png", {"front": "f.png", "back": "b.png"})
    assert r is not None
    assert r.min_similarity == 0.55
    assert r.passed is True
    assert r.variance <= 0.05


def test_unavailable_similarity_is_none_not_a_number():
    def missing(_a, _b):
        return None

    g = IdentitySubGate(similarity=missing)
    assert g.evaluate("plate.png", {"front": "f.png"}) is None


def test_family_is_siglip2_and_would_pass_a_diffusion_generator():
    """If this were wired through family_guard against SDXL it would pass.

    It is not wired. orchestrate only guards plugin.verifiers(). This
    sub-gate never enters that list. The family field is a label.
    """
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    assert normalize_family(g.family) == "siglip"
    assert_distinct_families("stable-diffusion", [g.family])


def test_family_would_refuse_a_siglip_generator_if_anyone_checked():
    g = IdentitySubGate(similarity=lambda _a, _b: 1.0)
    with pytest.raises(PromptCraftError) as exc:
        assert_distinct_families("siglip2", [g.family])
    assert exc.value.code == "GATE_SAME_FAMILY"


# ================ F-0f9a1f90 (the product told the operator to recalibrate and shipped no way to)
# sprite.calibration.json says of ITSELF, in `calibrated_on`: 'GENERIC SEED - not a real
# human-labelled holdout. Recalibrate against ~50-100 labelled sprites per check_type before any
# canon bind', and its `notes` add 'vqa/palette bands are placeholders'. thresholds.py repeats it.
# MEASURED: a grep for 'calibrat' across src/ scripts/ tests/ returned only READERS -- five
# `--thresholds` options, the loader, the fingerprint, the replay assertion -- and 'holdout'
# returned exactly one hit, that sentence. So the only path from the instruction to a calibrated
# table was hand-editing three float pairs.
#
# THIS IS THE HOLDOUT WORKFLOW ONLY. It does not wire the sub-gate into the loop and must not: the
# standing ruling that identity_subgate stays UNWIRED is correct precisely because nothing has
# measured what 0.55 / 0.05 should be. This produces that measurement and stops there.

import json  # noqa: E402
from pathlib import Path  # noqa: E402

from pcraft.core.contract.loader import ContractStore  # noqa: E402
from pcraft.core.contract.schema import CheckType  # noqa: E402
from pcraft.core.gate.thresholds import Zone, load_thresholds  # noqa: E402
from pcraft.domains.image.subdomains import sprite as sprite_pkg  # noqa: E402
from pcraft.domains.image.subdomains.sprite import calibrate as cal  # noqa: E402


class _TableVerifier:
    """A fake whose scores are looked up per (image, atom). No model, no GPU, no network."""

    version = "v0"
    tier = 1

    def __init__(self, scores, *, verifier_id="scripted.vqa.v0", family="clip-flant5"):
        self._scores = scores
        self.verifier_id = verifier_id
        self.family = family

    def score(self, image_path, question):
        return self._scores.get((image_path, question.atom_id))


def _rows(*triples):
    """Rows in the seam's shape: {image, contract, atom, label}."""
    return [
        {"image": image, "contract": "char:ashen-reaver", "atom": atom, "label": label}
        for image, atom, label in triples
    ]


def _store():
    return ContractStore([sprite_pkg.CONTRACTS_DIR])


def _base_table():
    return load_thresholds(sprite_pkg.THRESHOLDS_PATH)


def _calibrate(rows, scores, **kwargs):
    return cal.calibrate(
        rows,
        store=_store(),
        verifiers=[_TableVerifier(scores, **kwargs)],
        base_table=_base_table(),
        manifest="holdout.jsonl",
    )


def _fit(result, band_key):
    return next(f for f in result.bands if f.band_key == band_key)


def test_a_clean_split_puts_the_measured_gap_in_the_uncertain_zone():
    """The fitted band IS the separation: high = min(present), low = max(absent), so the
    human-checkpoint zone is exactly the interval where the labelled data gives no evidence."""
    rows = _rows(
        ("a.png", "skin", "present"),
        ("b.png", "skin", "present"),
        ("c.png", "skin", "absent"),
        ("d.png", "skin", "absent"),
    )
    result = _calibrate(
        rows,
        {
            ("a.png", "skin"): 0.90,
            ("b.png", "skin"): 0.95,
            ("c.png", "skin"): 0.10,
            ("d.png", "skin"): 0.20,
        },
    )
    fit = _fit(result, "vqa")
    assert fit.fitted is True
    assert fit.clean is True
    assert (fit.high, fit.low) == (0.9, 0.2)
    assert fit.separation == pytest.approx(0.7)
    assert (fit.counts.present, fit.counts.absent) == (2, 2)
    band = result.table.bands["vqa"]
    assert (band.high, band.low) == (0.9, 0.2)
    # every labelled row grades the way its label says under the table this fit produced
    assert result.table.zone("vqa", 0.90) is Zone.PASS
    assert result.table.zone("vqa", 0.20) is Zone.FAIL
    assert result.table.zone("vqa", 0.55) is Zone.UNCERTAIN


def test_a_band_with_no_absent_samples_is_unmeasured_and_stays_out_of_the_table():
    """MUST NOT BREAK (5): a band with no measurements is reported unmeasured, never defaulted."""
    rows = _rows(("a.png", "skin", "present"), ("b.png", "skin", "present"))
    result = _calibrate(rows, {("a.png", "skin"): 0.9, ("b.png", "skin"): 0.95})
    fit = _fit(result, "vqa")
    assert fit.fitted is False
    assert "absent" in fit.reason
    assert fit.high is None and fit.low is None
    assert "vqa" not in result.table.bands, "an unmeasured band must not be emitted"


def test_a_band_whose_verifier_could_not_answer_is_unmeasured_not_a_pass():
    """Degrades to SKIPPED per band exactly as the verifiers do when an extra is absent."""
    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(rows, {})  # the fake returns None for everything
    fit = _fit(result, "vqa")
    assert fit.fitted is False
    assert fit.counts.skipped == 2
    assert "vqa" not in result.table.bands
    assert result.scored and all(r.score is None for r in result.scored)


def test_overlapping_classes_cannot_produce_an_invalid_band():
    """Band(high >= low) is a model invariant. Overlap must degrade honestly, not raise."""
    rows = _rows(
        ("a.png", "skin", "present"),
        ("b.png", "skin", "present"),
        ("c.png", "skin", "absent"),
        ("d.png", "skin", "absent"),
    )
    result = _calibrate(
        rows,
        {
            ("a.png", "skin"): 0.40,
            ("b.png", "skin"): 0.80,
            ("c.png", "skin"): 0.30,
            ("d.png", "skin"): 0.60,
        },
    )
    fit = _fit(result, "vqa")
    assert fit.fitted is True
    assert fit.clean is False, "the classes overlap; the table must say so"
    assert fit.high >= fit.low
    assert fit.separation < 0
    assert fit.misfits >= 1, "an overlapping fit must count what it grades wrongly"


def test_borderline_rows_are_counted_and_never_fitted():
    rows = _rows(
        ("a.png", "skin", "present"),
        ("c.png", "skin", "absent"),
        ("e.png", "skin", "borderline"),
    )
    result = _calibrate(
        rows,
        {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2, ("e.png", "skin"): 0.5},
    )
    fit = _fit(result, "vqa")
    assert fit.counts.borderline == 1
    assert (fit.high, fit.low) == (0.9, 0.2), "a borderline row must not move a boundary"
    assert fit.borderline_in_band == 1, "and it lands where a borderline row should: UNCERTAIN"


def test_the_emitted_table_is_v2_under_the_unchanged_reader_contract():
    """MUST NOT BREAK (1) + (2): a NEW calibration version, the SAME $schema. The two strings are
    different kinds of thing and conflating them is the F-3637b97f defect."""
    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(rows, {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2})
    shipped = _base_table()
    assert result.table.version == "sprite.cal.v2"
    assert result.table.version != shipped.version
    assert result.table.schema_id == shipped.schema_id == "prompt-craft/thresholds.v1"
    assert result.table.fingerprint() != shipped.fingerprint()
    assert result.table.default == shipped.default, "an unmeasured default is carried, not invented"


def test_calibrated_on_replaces_the_generic_seed_sentence_with_counts():
    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(rows, {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2})
    assert "GENERIC SEED" not in result.table.calibrated_on
    assert "GENERIC SEED" in _base_table().calibrated_on, "the v1 file is untouched"
    for token in ("holdout.jsonl", "present=1", "absent=1", "vqa"):
        assert token in result.table.calibrated_on


def test_writing_the_table_refuses_the_packaged_v1_path(tmp_path):
    """MUST NOT BREAK (1): never overwrite sprite.cal.v1 in place. `fingerprint()` hashes band
    VALUES and `asset_record` asserts both the version string and the fingerprint on replay, so an
    in-place retune under the old name is the unrecoverable STATE_REPLAY_DRIFT arm."""
    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(rows, {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2})
    with pytest.raises(PromptCraftError) as exc:
        cal.write_table(result.table, sprite_pkg.THRESHOLDS_PATH)
    assert exc.value.code.startswith(("INPUT_", "STATE_"))
    assert exc.value.hint
    out = tmp_path / "sprite.cal.v2.json"
    cal.write_table(result.table, out)
    assert load_thresholds(out).version == "sprite.cal.v2"
    assert load_thresholds(sprite_pkg.THRESHOLDS_PATH).version == "sprite.cal.v1"


def test_emitting_a_table_never_auto_adopts_it():
    """MUST NOT BREAK (3): the shipped default stays v1 until a Director ratifies the swap, and
    existing receipts must keep replaying under the table that decided them."""
    from pcraft.sample import load_sprite_example

    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    _calibrate(rows, {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2})
    _s, _r, table, _c = load_sprite_example()
    assert table.version == "sprite.cal.v1"


def test_the_scored_companion_names_the_instrument_behind_every_number():
    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(rows, {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2})
    assert [r.verifier_id for r in result.scored] == ["scripted.vqa.v0"] * 2
    assert [r.band_key for r in result.scored] == ["vqa"] * 2
    assert _fit(result, "vqa").verifier_ids == ["scripted.vqa.v0"]


def test_the_band_key_is_the_one_the_gate_would_have_used():
    """A calibration fitted under a band key the gate never calls `zone()` with is a confidently
    wrong table. The key comes from the harness's own rule, not a second copy of it."""
    from pcraft.core.gate.harness import _band_key

    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(
        rows,
        {("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2},
        verifier_id="siglip2.screen.v1",
        family="siglip2",
    )
    expected = _band_key(CheckType.vqa, "siglip2.screen.v1", _base_table())
    assert expected == "siglip2", "the harness redirects to the instrument's own band"
    assert [r.band_key for r in result.scored] == ["siglip2", "siglip2"]


def test_a_row_naming_an_atom_the_contract_does_not_carry_is_refused():
    with pytest.raises(PromptCraftError) as exc:
        _calibrate(_rows(("a.png", "no-such-atom", "present")), {})
    assert exc.value.code.startswith("INPUT_")
    assert "no-such-atom" in exc.value.message
    assert exc.value.hint


def test_a_row_carrying_an_unknown_label_is_refused():
    rows = [{"image": "a.png", "contract": "char:ashen-reaver", "atom": "skin", "label": "maybe"}]
    with pytest.raises(PromptCraftError) as exc:
        _calibrate(rows, {})
    assert exc.value.code.startswith("INPUT_")
    assert "maybe" in exc.value.message


def test_the_scored_companion_omits_absent_keys_rather_than_writing_null(tmp_path):
    rows = _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
    result = _calibrate(rows, {("a.png", "skin"): 0.9})  # one scored, one unavailable
    out = tmp_path / "scored.jsonl"
    cal.write_scored(result.scored, out)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    scored = next(row for row in lines if row["image"] == "a.png")
    skipped = next(row for row in lines if row["image"] == "c.png")
    assert scored["score"] == 0.9
    assert "skipped_reason" not in scored
    assert "score" not in skipped, "a missing score is an absent key, never null"
    assert skipped["skipped_reason"]


def test_no_holdout_corpus_is_packaged_into_the_wheel():
    """MUST NOT BREAK (4): the manifest and its images are DATA, not fixtures. The harness takes a
    path; it does not ship 50-100 labelled sprites inside the package."""
    assert list(Path(sprite_pkg.__file__).parent.rglob("*.jsonl")) == []
    assert "path" in (cal.calibrate_from_manifest.__doc__ or "").lower()


def test_the_subgate_measurement_reports_and_does_not_wire():
    """The finding's explicit boundary: report floor/max_variance as a MEASUREMENT ONLY. This does
    not wire identity_subgate into orchestrate, and it does not import it -- STABILITY.md says of
    that module, verbatim, 'Do not build on this module, do not import it'."""
    measurement = cal.measure_subgate(
        [
            {"label": "present", "similarities": {"front": 0.81, "back": 0.77, "left": 0.79}},
            {"label": "present", "similarities": {"front": 0.72, "back": 0.70, "left": 0.74}},
            {"label": "absent", "similarities": {"front": 0.31, "back": 0.28, "left": 0.35}},
        ]
    )
    assert measurement.measured is True
    assert measurement.measured_floor == pytest.approx(0.70)
    assert measurement.measured_max_variance >= 0
    assert measurement.shipped_floor == 0.55
    assert measurement.shipped_max_variance == 0.05
    assert measurement.wired is False
    assert "IdentitySubGate" not in Path(cal.__file__).read_text(encoding="utf-8"), (
        "measure the numbers; do not reach for the gate"
    )


def test_a_subgate_measurement_with_no_present_groups_is_unmeasured():
    measurement = cal.measure_subgate(
        [{"label": "absent", "similarities": {"front": 0.3, "back": 0.2}}]
    )
    assert measurement.measured is False
    assert measurement.measured_floor is None


def test_the_manifest_is_read_through_the_loader_core_owns(tmp_path):
    # Was expected-red-until-fold; pcraft.core.gate.holdout folded in and this went green.
    manifest = tmp_path / "holdout.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps(row)
            for row in _rows(("a.png", "skin", "present"), ("c.png", "skin", "absent"))
        ),
        encoding="utf-8",
    )
    result = cal.calibrate_from_manifest(
        manifest,
        contracts_dirs=[sprite_pkg.CONTRACTS_DIR],
        verifiers=[_TableVerifier({("a.png", "skin"): 0.9, ("c.png", "skin"): 0.2})],
    )
    assert result.table.version == "sprite.cal.v2"


def test_the_missing_loader_refuses_by_name_rather_than_crashing(tmp_path):
    """Until that module lands, the path form must refuse in this package's own shape -- naming
    the seam it needs -- rather than raising a bare ImportError through the CLI backstop."""
    manifest = tmp_path / "holdout.jsonl"
    manifest.write_text("{}\n", encoding="utf-8")
    try:
        cal.load_manifest(manifest)
    except PromptCraftError as err:
        if err.code == "DEP_HOLDOUT_LOADER_MISSING":
            # Pre-fold form: the refusal names the seam it needs.
            assert cal.HOLDOUT_LOADER_MODULE in err.message
            assert err.hint
        else:
            # Post-fold (coordinator reconciliation): the real loader read the file and
            # refused the malformed row in the format's own named shape -- also not a
            # crash, which is this test's whole assertion.
            assert err.code == "INPUT_HOLDOUT_ROW"
    else:
        raise AssertionError("an empty-object row must refuse, not load")
