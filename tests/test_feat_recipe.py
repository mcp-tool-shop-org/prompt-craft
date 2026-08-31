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


def _reference_contracts_dir(tmp_path: Path) -> Path:
    """A contract tree whose identity_ref declares method=reference -- the recipe path's own method.

    The SHIPPED example is an SDXL contract (both its plates declare method=ip_adapter), so since
    F-0e41e735 it is refused at the recipe door rather than silently stitched. CLI tests that want a
    graph have to bring a contract the Kontext recipe can actually apply.
    """
    root = tmp_path / "contracts"
    root.mkdir(parents=True, exist_ok=True)
    (root / "ref.character.contract.json").write_text(
        json.dumps(
            {
                "$schema": "prompt-craft/contract.v1",
                "id": "char:reference-example",
                "level": "character",
                "must_have": [
                    {
                        "id": "weapon",
                        "claim": "a two-handed battle-axe held in both hands",
                        "check_type": "vqa",
                        "severity": "required",
                        "spatial": {"kind": "pose", "ref": "poses/two-hand-weapon.openpose.png"},
                    }
                ],
                "identity_ref": {
                    "plate": "plates/ashen-reaver-front.png",
                    "method": "reference",
                    "weight": 0.6,
                    "scope": "face",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return root


def _recipe_cli(tmp_path: Path, *args: str):
    """Invoke `pcraft recipe` against a method=reference contract tree."""
    return runner.invoke(
        app,
        [
            "recipe",
            "--contracts-dir",
            str(_reference_contracts_dir(tmp_path)),
            "--contract",
            "char:reference-example",
            *args,
        ],
    )


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
    result = _recipe_cli(tmp_path, "--out", str(out))
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
    result = _recipe_cli(tmp_path, "--json", "--out", str(out))
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["recipe_id"] == kontext_fill.RECIPE_ID
    assert data["fill_region"] == "fist"
    assert data["do_not_mask_bracer"] is True
    assert data["graph_path"]
    assert "recipe " not in result.stdout.split("{", 1)[0]


def test_cli_recipe_image_name_rewrites_the_graph(tmp_path):
    out = tmp_path / "recipe.json"
    result = _recipe_cli(
        tmp_path, "--out", str(out), "--image-name", "ashen-reaver-front.png=cloud-face.png"
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    graph = json.loads(out.read_text(encoding="utf-8"))
    loads = {n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"}
    assert "cloud-face.png" in loads


def test_cli_recipe_hands_is_a_refuse(tmp_path):
    # On a contract the recipe CAN apply, so the refusal measured here is the bracer guard and not
    # F-0e41e735's wrong-family refusal arriving first.
    result = _recipe_cli(tmp_path, "--fill-region", "hands", "--out", str(tmp_path / "x.json"))
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


def test_a_reference_contract_resolves_real_packaged_plates_into_the_graph(tmp_path):
    """Replaces test_shipped_example_builds_a_graph, which fed the recipe door the SHIPPED contract
    -- an SDXL one (see test_the_shipped_example_is_an_sdxl_contract_and_the_recipe_door_says_so).
    The property it was really pinning is that contract refs resolve to real packaged files and
    reach the graph; that is measured here on a contract whose method this recipe can apply."""
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_workspace

    _s, resolved, _t, _c = load_workspace(
        contracts_dirs=[_reference_contracts_dir(tmp_path)], contract_id="char:reference-example"
    )
    graph, report = kontext_fill.from_conditioning(_assemble_conditioning(resolved))
    assert Path(report.identity).is_file()
    assert Path(report.pose).is_file()
    assert "ashen-reaver-front.png" in report.identity
    assert "two-hand-weapon.openpose.png" in report.pose
    assert any(n["class_type"] == "ImageCropV2" for n in graph.values())


# ================================ F-b8ee4b0a (a typo switched off the module's one safety guard)
# BOTH bracer refusals are gated on `fill_mask is None`, and nothing ever checked that the value
# named a readable file. conditioning.resolve_ref -- this domain's existence-check mechanism, whose
# stated promise is to refuse "before any pipeline load if a ref cannot be opened" -- was never
# applied to fill_mask. MEASURED: fill_region='hands' with no mask is correctly REFUSED, while the
# same call with a path that does not exist was ACCEPTED, emitted LoadImage 'no-such-mask.png', and
# reported do_not_mask_bracer=None. A directory passed identically; so did Path(''), what typer
# produces from `--fill-mask ""`. End-to-end the shipped CLI printed the receipt, wrote the graph,
# and EXITED 0. Wave 2 made this strictly worse: supplying a mask is now the thing that turns
# "bracer: not masked" into "bracer: unverified", so a typo is the operator's route to the unsafe
# state. Worst case: a graph uploaded to Comfy Cloud at real spend whose mask does not resolve, on a
# Fill pass whose documented failure mode is destroying the bone-spike bracer.


def test_a_nonexistent_fill_mask_is_refused_rather_than_disabling_the_bracer_guard(tmp_path):
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(
            _lock_conditioning(tmp_path), fill_mask=str(tmp_path / "no-such-mask.png")
        )
    assert exc.value.code.startswith("INPUT_")
    assert "no-such-mask.png" in exc.value.message


def test_a_directory_is_not_a_painted_mask(tmp_path):
    folder = tmp_path / "masks"
    folder.mkdir()
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(_lock_conditioning(tmp_path), fill_mask=str(folder))
    assert exc.value.code.startswith("INPUT_")


def test_an_empty_fill_mask_path_is_refused(tmp_path):
    """`--fill-mask ""` reaches this layer as Path(''), which is not None -- so it took the supplied
    -mask branch and emitted `LoadImage image=''`."""
    with pytest.raises(PromptCraftError) as exc:
        # The suppression below is the point: Path("") is exactly what typer hands this layer, so
        # the empty path must be refused here rather than normalised away by the test.
        kontext_fill.from_conditioning(
            _lock_conditioning(tmp_path),
            fill_mask=Path(""),  # noqa: PTH201
        )
    assert exc.value.code.startswith("INPUT_")


def test_the_refusal_lands_before_any_graph_node_is_built(tmp_path):
    """"Before any graph is written" is the property that matters -- a refused recipe must not leave
    a half-built graph, and must not have consumed the bracer decision on the way."""
    from pcraft.domains.image.generator.reference_lock import assemble

    lock = assemble(_lock_conditioning(tmp_path))
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.build_graph(lock, fill_mask=str(tmp_path / "typo.png"))
    assert exc.value.code.startswith("INPUT_")


def test_report_for_refuses_the_same_mask_the_graph_refuses(tmp_path):
    """report_for() is public and answers the bracer question on its own; it may not answer it for
    a mask build_graph would have rejected."""
    from pcraft.domains.image.generator.reference_lock import assemble

    lock = assemble(_lock_conditioning(tmp_path))
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.report_for(lock, fill_mask=str(tmp_path / "typo.png"))
    assert exc.value.code.startswith("INPUT_")


def test_a_real_mask_is_still_accepted_and_still_reads_unverified(tmp_path):
    """The guard must not break the supported case: a real painted mask is the documented way to
    fill something other than the built-in fist box."""
    mask = write_solid_png(tmp_path / "painted-mask.png")
    graph, report = kontext_fill.from_conditioning(
        _lock_conditioning(tmp_path), fill_region="hands", fill_mask=str(mask)
    )
    assert report.mask_source == "supplied-mask"
    assert report.do_not_mask_bracer is None
    assert any(n["class_type"] == "ImageToMask" for n in graph.values())


def test_cli_recipe_refuses_a_mistyped_fill_mask_and_writes_no_graph(tmp_path):
    """MEASURED before the fix: this printed 'bracer: unverified (caller-painted mask)', wrote the
    graph, and exited 0. A typo must not be the route to the unsafe state."""
    out = tmp_path / "r.json"
    result = _recipe_cli(tmp_path, "--fill-mask", str(tmp_path / "typo.png"), "--out", str(out))
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text  # INPUT_ is exit 1: fix your input, not a runtime fault
    assert "typo.png" in text
    assert not out.exists(), "a refused recipe must not leave a graph behind"
    # The refusal's HINT names the bracer on purpose; what must not appear is the receipt LINE that
    # used to be printed for a mask that does not exist.
    assert "bracer: unverified" not in text
    assert "bracer: not masked" not in text
    assert kontext_fill.MEASURED_GRAPH not in text, "no receipt for a recipe that was refused"


# ============================================ F-0e41e735 (the two doors into one recipe disagreed)
# assemble() dropped method=none but bucketed every OTHER method into one flat `identity` list, and
# build_graph took refs[0] with no consideration of which entry declared method=reference. MEASURED:
# identity_refs=[{faction-face.png, ip_adapter, face}, {the-real-reference-plate.png, reference,
# face}] emitted LoadImage 'faction-face.png' and reported identity_method='ip_adapter' -- the
# declared reference plate NEVER reached the graph, and nothing in the report named the dropped
# plate. loader.py's _merge_identity_refs puts BASE refs first, so an inherited faction plate always
# precedes the character's own; faction+character composition is the documented pattern.
# Compounding it, on IDENTICAL conditioning FluxGenerator.generate REFUSED
# GATE_CONDITIONING_UNSUPPORTED 'cannot apply method=ip_adapter' and wrote no recipe, while
# from_conditioning -- what `pcraft recipe` calls -- accepted it and emitted the graph.
#
# The law now: the recipe door refuses exactly what the generate door refuses. method=none still
# drops; method=reference is still this path's whole purpose.


def _identity_refs(tmp_path: Path, *refs: dict) -> dict:
    pose = write_solid_png(tmp_path / "two-hand.openpose.png")
    return {"pose_refs": [str(pose)], "identity_refs": list(refs)}


def _plate(tmp_path: Path, name: str, method: str, scope: str = "face") -> dict:
    return {
        "plate": str(write_solid_png(tmp_path / name)),
        "method": method,
        "scope": scope,
    }


@pytest.mark.parametrize("method", ["ip_adapter", "lora", "instantid"])
def test_the_recipe_door_refuses_every_method_the_generate_door_refuses(tmp_path, method):
    """A recipe may never stamp an identity the declared method could not have applied."""
    conditioning = _identity_refs(tmp_path, _plate(tmp_path, "face.png", method))
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(conditioning)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert method in exc.value.message


@pytest.mark.parametrize("method", ["ip_adapter", "lora", "instantid"])
def test_both_doors_refuse_the_identical_conditioning_the_identical_way(tmp_path, method):
    """The defect was a DISAGREEMENT between two doors into the same Cloud recipe, so the fix is
    tested as an agreement, not merely as a new refusal."""
    conditioning = _identity_refs(tmp_path, _plate(tmp_path, "face.png", method))
    with pytest.raises(PromptCraftError) as recipe_exc:
        kontext_fill.from_conditioning(conditioning)
    with pytest.raises(PromptCraftError) as generate_exc:
        FluxGenerator(out_dir=tmp_path / "out").generate("p", "n", conditioning, seed=1)
    assert recipe_exc.value.code == generate_exc.value.code
    assert method in generate_exc.value.message
    # and the generate door's settled promise holds: it wrote no recipe file
    assert not (tmp_path / "out").exists()


def test_the_recipe_door_still_accepts_method_reference(tmp_path):
    """The settled behaviour: method=reference IS this path. It must survive the new refusal."""
    graph, report = kontext_fill.from_conditioning(
        _identity_refs(tmp_path, _plate(tmp_path, "face.png", "reference"))
    )
    assert report.identity_method == "reference"
    assert "face.png" in report.identity
    assert any(n["class_type"] == "ImageStitch" for n in graph.values())


def test_the_recipe_door_still_drops_method_none(tmp_path):
    """The other settled behaviour: method=none is a documented skip, never a lock -- and never a
    refusal either. It drops, and the reference plate beside it is the identity."""
    _graph, report = kontext_fill.from_conditioning(
        _identity_refs(
            tmp_path,
            _plate(tmp_path, "skipped.png", "none"),
            _plate(tmp_path, "real.png", "reference"),
        )
    )
    assert "real.png" in report.identity
    assert report.identity_method == "reference"


def test_the_recipe_door_still_refuses_an_unknown_method(tmp_path):
    """The F-916e73b6 allow-list, unchanged: a method nobody wired is refused by name."""
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(
            _identity_refs(tmp_path, _plate(tmp_path, "face.png", "pulid"))
        )
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "pulid" in exc.value.message


def test_an_inherited_ip_adapter_plate_can_no_longer_shadow_the_declared_reference_plate(tmp_path):
    """The finding's measured scenario, in list order: BASE (faction) ref first, character's own
    second. The wrong plate used to win silently and reach Comfy Cloud as the stitch identity."""
    conditioning = _identity_refs(
        tmp_path,
        _plate(tmp_path, "faction-face.png", "ip_adapter"),
        _plate(tmp_path, "the-real-reference-plate.png", "reference"),
    )
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(conditioning)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "ip_adapter" in exc.value.message


def test_a_second_reference_plate_is_named_on_the_receipt_rather_than_silently_dropped(tmp_path):
    """The residual first-wins: two plates the recipe CAN apply still land in one identity bucket
    and build_graph stitches one. That is allowed -- staying silent about the other is not."""
    graph, report = kontext_fill.from_conditioning(
        _identity_refs(
            tmp_path,
            _plate(tmp_path, "first.png", "reference"),
            _plate(tmp_path, "second.png", "reference"),
        )
    )
    assert "first.png" in report.identity
    loaded = {n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"}
    assert "second.png" not in loaded, "still stitched only one plate"
    assert any("second.png" in p for p in report.identity_unchosen), (
        "the receipt must name the plate the stitch did not use"
    )
    assert report.model_dump()["identity_unchosen"], "and it must survive serialisation"


def test_the_single_plate_case_leaves_the_receipt_clean(tmp_path):
    _graph, report = kontext_fill.from_conditioning(
        _identity_refs(tmp_path, _plate(tmp_path, "face.png", "reference"))
    )
    assert report.identity_unchosen == []


def test_the_shipped_example_is_an_sdxl_contract_and_the_recipe_door_says_so():
    """Replaces test_shipped_example_builds_a_graph. Both plates in the shipped example declare
    method=ip_adapter -- it is an SDXL contract, and `pcraft recipe` used to build it a graph anyway
    (exit 0), stamping an identity the Kontext recipe could not have applied."""
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_sprite_example

    _s, resolved, _t, _c = load_sprite_example()
    with pytest.raises(PromptCraftError) as exc:
        kontext_fill.from_conditioning(_assemble_conditioning(resolved))
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "ip_adapter" in exc.value.message
    assert "reference" in (exc.value.hint or "")


def test_cli_recipe_refuses_the_shipped_sdxl_contract_by_name(tmp_path):
    """`pcraft recipe` with NO arguments used to exit 0 having written the graph."""
    result = runner.invoke(app, ["recipe", "--out", str(tmp_path / "x.json")])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2, text
    assert "GATE_CONDITIONING_UNSUPPORTED" in text
    assert "ip_adapter" in text
    assert not (tmp_path / "x.json").exists(), "a refused recipe must not leave a graph behind"


# Coordinator fold-edit (wave 2): the terminal line at cli/__init__.py used to print the literal
# "bracer: not masked" unconditionally -- an honest receipt under a dishonest banner. The line now
# reads report.do_not_mask_bracer; these pin both directions so the banner cannot drift from the
# receipt again.
def test_cli_recipe_terminal_line_tracks_the_receipt_for_a_painted_mask(tmp_path):
    mask = write_solid_png(tmp_path / "painted-mask.png")
    result = _recipe_cli(tmp_path, "--fill-mask", str(mask), "--out", str(tmp_path / "r.json"))
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "bracer: unverified (caller-painted mask)" in result.stdout
    assert "bracer: not masked" not in result.stdout


def test_cli_recipe_terminal_line_still_claims_the_builtin_fist_constraint(tmp_path):
    result = _recipe_cli(tmp_path, "--out", str(tmp_path / "r.json"))
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "bracer: not masked" in result.stdout
