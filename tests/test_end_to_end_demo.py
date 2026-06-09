from __future__ import annotations

from pcraft.sample import run_mock_loop


def test_demo_binds_and_writes_a_viewable_image_and_a_pinned_receipt(tmp_path):
    res = run_mock_loop(records_dir=str(tmp_path))
    assert res.decision == "bound"

    # a real PNG was produced (rough output is fine — the loop is what's proven)
    images = list((tmp_path / "_stub_images").glob("*.png"))
    assert images, "no image produced"
    assert images[0].read_bytes().startswith(b"\x89PNG")

    # the receipt pins provenance (PIN_PER_STEP)
    rec = res.record
    assert rec.contract_hash.startswith("sha256:")
    assert rec.thresholds_version == "sprite.cal.v1"
    assert rec.generator_family == "stable-diffusion"
    assert rec.compiled_synth_id  # the synth backend/program is recorded
    assert rec.gate_transcript.overall.value == "PASS"
    assert rec.question_dag.questions  # the DAG is stored for replay
