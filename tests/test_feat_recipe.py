"""F-IMG-FEAT-006 — Kontext stitch + in-graph left crop + fist-only Fill.

GPU-free: graph build, region boxes, CLI write. No Cloud submit, no 5090.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pcraft.cli import app
from pcraft.domains.image.generator import conditioning as cond
from pcraft.domains.image.generator import kontext_fill
from pcraft.domains.image.generator.flux_generator import FluxGenerator
from pcraft.domains.image.generator.sdxl_generator import SDXLGenerator
from pcraft.errors import PromptCraftError
from pcraft.testing import write_solid_png

runner = CliRunner()


def _lock_conditioning(tmp_path: Path) -> dict:
    identity = write_solid_png(tmp_path / "face.png")
    pose = write_solid_png(tmp_path / "two-hand.openpose.png")
    return {
        "pose_refs": [str(pose)],
        "identity_refs": [{"plate": str(identity), "method": "reference", "scope": "face"}],
    }


def _nodes_by_type(graph: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for node in graph.values():
        out.setdefault(node["class_type"], []).append(node)
    return out


def test_fist_box_is_smaller_than_hands_and_misses_the_bracer_band():
    fist = cond.region_box(1000, 1000, "fist")
    hands = cond.region_box(1000, 1000, "hands")
    fist_area = (fist[2] - fist[0]) * (fist[3] - fist[1])
    hands_area = (hands[2] - hands[0]) * (hands[3] - hands[1])
    assert fist_area < hands_area * 0.3
    # Bracer sits above the fist on the keeper crop (~y 0.38-0.48).
    assert fist[1] >= 450


def test_pipeline_kind_names_reference():
    assert (
        cond.pipeline_kind({"identity_refs": [{"plate": "p.png", "method": "reference"}]})
        == "reference"
    )


def test_sdxl_refuses_method_reference(tmp_path):
    plate = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        SDXLGenerator().generate(
            "p",
            "n",
            {"identity_refs": [{"plate": str(plate), "method": "reference"}]},
            seed=1,
        )
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "reference" in exc.value.message
    assert "pcraft recipe" in (exc.value.hint or "")


def test_flux_reference_without_pose_still_needs_the_map(tmp_path):
    plate = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator(out_dir=tmp_path / "out").generate(
            "p",
            "n",
            {"identity_refs": [{"plate": str(plate), "method": "reference", "scope": "face"}]},
            seed=1,
        )
    assert exc.value.code == "GATE_CONDITIONING_REF_MISSING"


def test_graph_stitches_then_crops_left_then_fills_the_fist(tmp_path):
    graph, report = kontext_fill.from_conditioning(_lock_conditioning(tmp_path))
    by_type = _nodes_by_type(graph)
    assert "ImageStitch" in by_type
    assert by_type["ImageStitch"][0]["inputs"]["direction"] == "right"
    assert "ImageCropV2" in by_type
    assert "InpaintModelConditioning" in by_type
    unets = {n["inputs"]["unet_name"] for n in by_type["UNETLoader"]}
    assert kontext_fill.KONTEXT_UNET in unets
    assert kontext_fill.FILL_UNET in unets
    assert report.crop == "left-half"
    assert report.fill_region == "fist"
    assert report.do_not_mask_bracer is True
    assert report.stages == list(kontext_fill.STAGES)

    crop = by_type["ImageCropV2"][0]
    box_id = str(crop["inputs"]["crop_region"][0])
    box = graph[box_id]["inputs"]
    assert box["x"] == 0
    assert box["y"] == 0
    # width is half the diptych, linked from ComfyMathExpression "a / 2"
    math_id = str(box["width"][0])
    assert graph[math_id]["inputs"]["expression"] == "a / 2"
    # Cloud wants dotted autogrow keys. Nested values: {a: ...} 400s live.
    assert "values.a" in graph[math_id]["inputs"]
    assert "values" not in graph[math_id]["inputs"]


def test_bind_cloud_names_rewrites_loadimage_only(tmp_path):
    graph, _report = kontext_fill.from_conditioning(_lock_conditioning(tmp_path))
    loads = [n for n in graph.values() if n["class_type"] == "LoadImage"]
    original = loads[0]["inputs"]["image"]
    mapped = kontext_fill.bind_cloud_names(graph, {original: "cloud-hash.png"})
    new_loads = [n for n in mapped.values() if n["class_type"] == "LoadImage"]
    assert "cloud-hash.png" in {n["inputs"]["image"] for n in new_loads}
    assert original in {n["inputs"]["image"] for n in loads}


def test_hands_fill_region_is_refused_because_it_eats_the_bracer(tmp_path):
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(_lock_conditioning(tmp_path), fill_region="hands")
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "bracer" in exc.value.message


def test_missing_pose_refuses(tmp_path):
    identity = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(
            {"identity_refs": [{"plate": str(identity), "method": "reference", "scope": "face"}]}
        )
    assert exc.value.code == "GATE_CONDITIONING_REF_MISSING"


def test_cli_recipe_writes_the_api_graph(tmp_path):
    out = tmp_path / "recipe.json"
    result = runner.invoke(app, ["recipe", "--out", str(out)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    text = (result.stdout or "") + (result.stderr or "")
    assert kontext_fill.RECIPE_ID in text
    assert "crop_left" in text
    assert out.is_file()
    graph = json.loads(out.read_text(encoding="utf-8"))
    types = {n["class_type"] for n in graph.values()}
    assert "ImageStitch" in types
    assert "ImageCropV2" in types
    assert "InpaintModelConditioning" in types


def test_cli_recipe_json_is_a_document(tmp_path):
    out = tmp_path / "recipe.json"
    result = runner.invoke(app, ["recipe", "--json", "--out", str(out)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["recipe_id"] == kontext_fill.RECIPE_ID
    assert data["fill_region"] == "fist"
    assert data["do_not_mask_bracer"] is True
    assert data["graph_path"]
    assert "recipe " not in result.stdout.split("{", 1)[0]


def test_cli_recipe_image_name_rewrites_the_graph(tmp_path):
    out = tmp_path / "recipe.json"
    result = runner.invoke(
        app,
        [
            "recipe",
            "--out",
            str(out),
            "--image-name",
            "ashen-reaver-front.png=cloud-face.png",
        ],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    graph = json.loads(out.read_text(encoding="utf-8"))
    loads = {n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"}
    assert "cloud-face.png" in loads


def test_cli_recipe_hands_is_a_refuse(tmp_path):
    result = runner.invoke(
        app, ["recipe", "--fill-region", "hands", "--out", str(tmp_path / "x.json")]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2
    assert "GATE_CONDITIONING_UNSUPPORTED" in text
    assert "bracer" in text


# ============================================== F-90667b30 (the receipt may not assert what nothing checked)
# RecipeReport.do_not_mask_bracer was declared `= True` and never assigned anywhere; report_for()
# did not accept or consider fill_mask at all. Meanwhile build_graph's bracer guard is bypassed
# whenever fill_mask is not None -- both refusals are gated on `fill_mask is None`. MEASURED:
# from_conditioning(fill_region='hands', fill_mask=<a plate>) was ACCEPTED and returned a report
# carrying fill_region='hands' AND do_not_mask_bracer=True. The module's single measured safety
# constraint (2026-08-18: a hands/weapon region ate the bone-spike bracer) was being handed to the
# operator as an unconditional success claim.


def test_a_supplied_mask_may_not_claim_the_bracer_was_spared(tmp_path):
    mask = write_solid_png(tmp_path / "painted-mask.png")
    _graph, report = kontext_fill.from_conditioning(
        _lock_conditioning(tmp_path), fill_region="hands", fill_mask=str(mask)
    )
    # A painted mask's coverage is not inspectable here, so the honest value is "unverified",
    # never True. True is the one answer the code has no evidence for.
    assert report.do_not_mask_bracer is not True
    assert report.mask_source == "supplied-mask"
    # the graph does not use the region string at all once a mask is supplied
    assert report.fill_region != "hands"
    assert report.requested_fill_region == "hands"


def test_the_builtin_fist_path_is_the_only_one_that_stamps_the_constraint(tmp_path):
    _graph, report = kontext_fill.from_conditioning(_lock_conditioning(tmp_path))
    assert report.do_not_mask_bracer is True
    assert report.mask_source == "builtin-fist"
    assert report.fill_region == "fist"
    assert report.requested_fill_region == "fist"


def test_the_field_tracks_the_graph_not_the_request(tmp_path):
    """The mask nodes the graph actually builds must agree with what the receipt says built them."""
    mask = write_solid_png(tmp_path / "painted-mask.png")
    supplied, supplied_report = kontext_fill.from_conditioning(
        _lock_conditioning(tmp_path), fill_mask=str(mask)
    )
    builtin, builtin_report = kontext_fill.from_conditioning(_lock_conditioning(tmp_path))
    supplied_types = {n["class_type"] for n in supplied.values()}
    builtin_types = {n["class_type"] for n in builtin.values()}
    # supplied mask -> ImageToMask off a LoadImage; builtin -> the SolidMask/MaskComposite fist blob
    assert "ImageToMask" in supplied_types and "MaskComposite" not in supplied_types
    assert "MaskComposite" in builtin_types and "ImageToMask" not in builtin_types
    assert supplied_report.mask_source == "supplied-mask"
    assert builtin_report.mask_source == "builtin-fist"
    assert builtin_report.do_not_mask_bracer is True
    assert supplied_report.do_not_mask_bracer is not True


def test_report_for_alone_cannot_claim_a_constraint_it_was_not_told_about(tmp_path):
    """report_for() is public. Called with the same mask the graph got, it must agree with it."""
    from pcraft.domains.image.generator.reference_lock import assemble

    mask = write_solid_png(tmp_path / "painted-mask.png")
    lock = assemble(_lock_conditioning(tmp_path))
    assert kontext_fill.report_for(lock).do_not_mask_bracer is True
    assert kontext_fill.report_for(lock, fill_mask=str(mask)).do_not_mask_bracer is not True


def test_shipped_example_builds_a_graph():
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_sprite_example

    _s, resolved, _t, _c = load_sprite_example()
    graph, report = kontext_fill.from_conditioning(_assemble_conditioning(resolved))
    assert Path(report.identity).is_file()
    assert Path(report.pose).is_file()
    assert "ashen-reaver-front.png" in report.identity
    assert "two-hand-weapon.openpose.png" in report.pose
    assert any(n["class_type"] == "ImageCropV2" for n in graph.values())


# Coordinator fold-edit (wave 2): the terminal line at cli/__init__.py used to print the literal
# "bracer: not masked" unconditionally -- an honest receipt under a dishonest banner. The line now
# reads report.do_not_mask_bracer; these pin both directions so the banner cannot drift from the
# receipt again.
def test_cli_recipe_terminal_line_tracks_the_receipt_for_a_painted_mask(tmp_path):
    mask = write_solid_png(tmp_path / "painted-mask.png")
    result = runner.invoke(
        app,
        ["recipe", "--fill-mask", str(mask), "--out", str(tmp_path / "r.json")],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "bracer: unverified (caller-painted mask)" in result.stdout
    assert "bracer: not masked" not in result.stdout


def test_cli_recipe_terminal_line_still_claims_the_builtin_fist_constraint(tmp_path):
    result = runner.invoke(app, ["recipe", "--out", str(tmp_path / "r.json")])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "bracer: not masked" in result.stdout
