"""F-CLI-FEAT-001 / 003 / 004 -- the CLI can load a store that is not the shipped demo."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pcraft import package_version
from pcraft.cli import app

runner = CliRunner()


def _write_pair(root):
    (root / "factions").mkdir()
    (root / "characters").mkdir()
    (root / "factions" / "x.contract.json").write_text(
        json.dumps(
            {
                "id": "faction:x",
                "level": "faction",
                "must_have": [
                    {"id": "tabard", "claim": "a tabard", "check_type": "vqa", "severity": "required"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "characters" / "y.contract.json").write_text(
        json.dumps(
            {
                "id": "char:y",
                "level": "character",
                "extends": "faction:x",
                "must_have": [
                    {"id": "face", "claim": "a face", "check_type": "vqa", "severity": "required"}
                ],
            }
        ),
        encoding="utf-8",
    )


def test_list_default_includes_the_shipped_example():
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "char:ashen-reaver" in result.stdout
    assert "faction:ashen-pact" in result.stdout


def test_list_custom_dir_does_not_require_ashen_reaver(tmp_path):
    _write_pair(tmp_path)
    result = runner.invoke(app, ["list", "--contracts-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "char:y" in result.stdout
    assert "faction:x" in result.stdout
    assert "ashen-reaver" not in result.stdout


def test_empty_contracts_dir_is_input_empty_store(tmp_path):
    result = runner.invoke(app, ["list", "--contracts-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1
    assert "INPUT_EMPTY_STORE" in text


def test_missing_contracts_dir_is_input(tmp_path):
    result = runner.invoke(app, ["list", "--contracts-dir", str(tmp_path / "nope")])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1
    assert "INPUT_CONTRACTS_DIR" in text


def test_validate_default_example_exits_0():
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0
    assert "ok  char:ashen-reaver" in result.stdout
    assert "questions:" in result.stdout


def test_validate_custom_contract(tmp_path):
    _write_pair(tmp_path)
    result = runner.invoke(
        app, ["validate", "--contract", "char:y", "--contracts-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "ok  char:y" in result.stdout
    assert "tabard" in result.stdout
    assert "face" in result.stdout


def test_synth_honours_contracts_dir(tmp_path):
    _write_pair(tmp_path)
    result = runner.invoke(
        app, ["synth", "--contract", "char:y", "--contracts-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "a tabard" in result.stdout
    assert "a face" in result.stdout


def test_synth_unknown_id_in_custom_store_is_not_ashen(tmp_path):
    _write_pair(tmp_path)
    result = runner.invoke(
        app, ["synth", "--contract", "char:ashen-reaver", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1
    assert "INPUT_UNKNOWN_CONTRACT" in text


# --------------------------------------------------------------------------- F-CLI-FEAT-002 --json
# Models already dump. Human banner (when there is one) goes to stderr so stdout is a document.


def test_list_json_is_a_document_and_names_the_shipped_example():
    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    ids = {c["id"] for c in data["contracts"]}
    assert "char:ashen-reaver" in ids
    assert "faction:ashen-pact" in ids
    assert "char:ashen-reaver" not in result.stdout.split("{", 1)[0]


def test_synth_json_dumps_the_synth_result():
    result = runner.invoke(app, ["synth", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "prompt" in data
    assert "atom_coverage" in data
    assert data["backend"] == "template"
    # human lines moved off stdout
    assert not result.stdout.lstrip().startswith("prompt:")


def test_validate_json_dumps_the_report():
    result = runner.invoke(app, ["validate", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["id"] == "char:ashen-reaver"
    assert data["questions"] > 0
    assert "face" in data["required"]


def test_demo_json_puts_the_mock_banner_on_stderr(tmp_path):
    result = runner.invoke(app, ["demo", "--json", "--records-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["decision"] == "bound"
    banner = result.stderr or ""
    assert "mock:" in banner
    assert "pixels were not read" in banner
    assert "mock:" not in result.stdout


def test_bind_json_dumps_the_orchestration_result(tmp_path):
    result = runner.invoke(app, ["bind", "--json", "--records-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["decision"] == "bound"
    assert data["record"]["thresholds_version"] == "sprite.cal.v1"


def test_replay_json_dumps_the_record(tmp_path):
    """EXPECTED RED IN THIS WORKTREE until the wave-6 fold (F-70ea9458).

    `pcraft replay` now hands the loaded threshold TABLE to `do_replay`, not just its
    version string, so band values retuned under an unchanged version stop replaying as
    clean. `do_replay`'s matching `thresholds=` parameter lands in the sibling
    core-gate-loop worktree; until both halves are folded, this success path raises
    TypeError, which the command's backstop reports as RUNTIME_UNEXPECTED / exit 2. The
    assertion is unchanged and correct -- do not relax it to force green locally. See the
    F-70ea9458 block in tests/test_amend_cli.py for the two tests that pin the new
    behaviour itself.
    """
    bind = runner.invoke(app, ["bind", "--records-dir", str(tmp_path)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")
    receipts = list(tmp_path.glob("*.json"))
    assert receipts
    result = runner.invoke(app, ["replay", str(receipts[0]), "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["contract_id"] == "char:ashen-reaver"
    assert (result.stderr or "").startswith("replay OK:")


def test_gate_json_dumps_the_transcript_even_when_models_are_missing(tmp_path):
    """Palette now scores without a GPU extra, so a stub PNG is PARTIAL (3),
    not GATE_UNAVAILABLE (4). The JSON document still has to come out."""
    from pcraft.testing import write_solid_png

    image = write_solid_png(tmp_path / "x.png")
    result = runner.invoke(app, ["gate", str(image), "--json"])
    # Palette ran (histogram). Other required atoms SKIP. Not 0, not 4.
    assert result.exit_code in {2, 3}
    data = json.loads(result.stdout)
    assert data["overall"] in {"UNCERTAIN", "FAIL"}
    assert data["thresholds_version"] == "sprite.cal.v1"
    palette = next(v for v in data["verdicts"] if v["atom_id"] == "palette")
    assert palette["score"] is not None


# --------------------------------------------------------------------------- F-CLI-FEAT-006 --version + doctor


def test_version_prints_the_installed_distribution_and_exits_0():
    """The CLI must SURFACE the installed version, never repeat a literal.

    These assertions were pinned to the 0.2.x literal and went stale at the 0.3.0 bump.
    They kept passing locally only because an editable install's dist-info is not
    regenerated when pyproject changes, so the dev venv still reported the previous
    release. A fresh `pip install -e ".[dev]"` -- exactly what CI does -- reported 0.3.0
    and failed all three. The version literal lives in pyproject and is pinned there by
    test_the_version_fallback_matches_pyproject; these check only that the CLI reports
    what is actually installed.
    """
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    text = (result.stdout or "") + (result.stderr or "")
    assert package_version() in text
    assert "pcraft" in text


def test_doctor_loads_the_shipped_store():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    text = (result.stdout or "") + (result.stderr or "")
    assert f"pcraft {package_version()}" in text
    assert "python" in text
    assert "[image]" in text
    assert "[synth]" in text
    assert "store ok" in text
    assert "sprite.cal.v1" in text


def test_doctor_json_is_a_document():
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    assert data["version"] == package_version()
    assert data["store_ok"] is True
    assert "char:ashen-reaver" in data["store_ids"]
    extra_names = {e["name"] for e in data["extras"]}
    assert extra_names == {"image", "synth"}


def test_doctor_reports_the_model_tier_census_beside_the_extras():
    """Phase 9 (F2): doctor said "[image] present" while the model-tier verifiers could not
    import, so a fully-[image]-installed gate skipped 5 of the example's 6 required atoms
    with doctor green and GATE_FAIL's hint pointing back at the extra the user already had.
    The census row gives the missing packages a NAME on the one screen an operator checks
    -- and is NOT rendered as a bracketed extra, because
    `pip install prompt-crafter[model-tier]` does not exist and must not be invited.
    """
    result = runner.invoke(app, ["doctor"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, text
    assert "model tier" in text, text
    assert "[model tier]" not in text and "[model-tier]" not in text, text


def test_doctor_json_carries_the_model_tier_census():
    """Additive, defaulted field -- existing readers of the document are unaffected."""
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    tier = data["model_tier"]
    assert tier is not None, "doctor stopped probing the model-tier imports"
    assert set(tier["modules"]) == {"t2v_metrics", "ai_eyes_mcp"}, tier
    assert "model tier" not in {e["name"] for e in data["extras"]}, (
        "the model-tier census is not a pip extra and must not join extras"
    )


def test_doctor_missing_contracts_dir_is_not_ok(tmp_path):
    result = runner.invoke(app, ["doctor", "--contracts-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
    text = (result.stdout or "") + (result.stderr or "")
    assert "INPUT_CONTRACTS_DIR" in text
    assert "store FAIL" in text


def test_schema_dumps_the_authoring_contract():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    data = json.loads(result.stdout)
    blob = json.dumps(data)
    assert "must_have" in blob
    assert "must_not" in blob
    assert "identity_ref" in blob
    assert "$schema" in blob or "schema_id" in blob


def test_bind_no_mock_without_image_extra_is_dep_image(monkeypatch, tmp_path):
    from pcraft import sample

    monkeypatch.setattr(sample, "image_extra_present", lambda: False)
    result = runner.invoke(app, ["bind", "--no-mock", "--records-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2
    assert "DEP_IMAGE_MISSING" in text
    assert "BOUND" not in text


def test_bind_no_mock_uses_the_plugin_generator(monkeypatch, tmp_path):
    """--no-mock is the live door. Stub generate so the suite stays GPU-free."""
    from pcraft import sample
    from pcraft.core.loop.generator_iface import GenerationResult
    from pcraft.domains.image import ImagePlugin
    from pcraft.domains.image.generator.sdxl_generator import SDXLGenerator
    from pcraft.testing import passing_verifiers, write_solid_png

    monkeypatch.setattr(sample, "image_extra_present", lambda: True)
    monkeypatch.setattr(ImagePlugin, "verifiers", lambda self: passing_verifiers())
    png = write_solid_png(tmp_path / "live.png")
    seen: dict = {}

    def fake_generate(self, prompt, negative_prompt, conditioning, seed):
        seen["plates"] = [
            r.get("plate") for r in (conditioning.get("identity_refs") or []) if isinstance(r, dict)
        ]
        seen["generator"] = self.generator_id
        return GenerationResult(
            image_path=str(png),
            seed=seed,
            sampler="test",
            generator_id=self.generator_id,
            generator_family=self.family,
            conditioning=conditioning,
        )

    monkeypatch.setattr(SDXLGenerator, "generate", fake_generate)
    result = runner.invoke(app, ["bind", "--no-mock", "--records-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert "DEP_IMAGE_MISSING" not in text
    assert seen.get("generator") == "sdxl.base-1.0.v1", text
    assert len(seen.get("plates") or []) == 2, seen
    assert result.exit_code == 0, text


def test_schema_writes_out(tmp_path):
    out = tmp_path / "contract.schema.json"
    result = runner.invoke(app, ["schema", "--out", str(out)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "must_have" in json.dumps(data)


def test_doctor_custom_store_does_not_require_ashen(tmp_path):
    _write_pair(tmp_path)
    result = runner.invoke(app, ["doctor", "--contracts-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    text = (result.stdout or "") + (result.stderr or "")
    assert "store ok" in text
    assert "2 contracts" in text


# =========================================================================== F-69661dda
# `--image-name local=cloud` is matched against the LoadImage nodes the emitted graph
# ACTUALLY carries, and an unmatched local side is refused before anything is written.
#
# MEASURED red on the shipped tree (containment IN WORKTREE: True, no GPU, no submit),
# against the method=reference tree `_reference_store` builds below:
#
#     pcraft recipe --image-name ashen-reaver-frnt.png=cloud-abc.png   (one letter dropped)
#     -> exit 0, graph written, LoadImage nodes still read
#        ['ashen-reaver-front.png', 'two-hand-weapon.openpose.png']
#
# The remap was not applied and nothing said so. `kontext_fill.bind_cloud_names`'s
# documented behaviour for an unrecognised key is "missing keys stay", and that is right
# for what it is -- a pure graph rewrite with no opinion about what the caller meant. The
# layer that CAN tell is this one, the only place holding the pairs and the graph at the
# same time. The receipt made it worse than silent: `cloud_names` recorded the pair as
# though it had been applied, so the artifact asserts a remap the graph does not carry,
# and the next step is a Comfy Cloud submit at real spend naming a file Comfy never
# issued. `_parse_image_names` already owns the SHAPE half of this refusal (a=b, empty
# sides); this is the half that needs a graph to answer.


def _reference_store(root):
    """A method=reference contract pair -- the identity method `pcraft recipe` can apply.

    Twinned on BOTH levels on purpose: `loader._merge_identity_refs` puts the inherited
    faction plate first and `reference_lock.assemble` refuses the whole merged list on a
    wrong-family method, so a character-only twin over an ip_adapter faction still refuses.
    The plate/pose refs resolve against the PACKAGED sprite tree, so this fixture needs no
    image bytes of its own -- only the two contract files.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "factions").mkdir()
    (root / "characters").mkdir()
    (root / "factions" / "f.contract.json").write_text(
        json.dumps(
            {
                "$schema": "prompt-craft/contract.v1",
                "id": "faction:ref-example",
                "level": "faction",
                "must_have": [
                    {"id": "tabard", "claim": "a tabard", "check_type": "vqa",
                     "severity": "required"}
                ],
                "identity_ref": {"plate": "plates/ashen-pact-costume.png",
                                 "method": "reference", "weight": 0.6, "scope": "costume"},
            }
        ),
        encoding="utf-8",
    )
    (root / "characters" / "c.contract.json").write_text(
        json.dumps(
            {
                "$schema": "prompt-craft/contract.v1",
                "id": "char:ref-example",
                "level": "character",
                "extends": "faction:ref-example",
                "must_have": [
                    {"id": "face", "claim": "a face", "check_type": "vqa",
                     "severity": "required"},
                    {"id": "weapon", "claim": "an axe", "check_type": "vqa",
                     "severity": "required",
                     "spatial": {"kind": "pose",
                                 "ref": "poses/two-hand-weapon.openpose.png"}},
                ],
                "identity_ref": {"plate": "plates/ashen-reaver-front.png",
                                 "method": "reference", "weight": 0.6, "scope": "face"},
            }
        ),
        encoding="utf-8",
    )
    return root


def _reference_recipe(tmp_path, *args):
    store = _reference_store(tmp_path / "store")
    return runner.invoke(
        app,
        ["recipe", "--contracts-dir", str(store), "--contract", "char:ref-example", *args],
    )


def _loadimage_names(path):
    graph = json.loads(path.read_text(encoding="utf-8"))
    return [n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"]


def test_recipe_refuses_an_image_name_whose_local_side_no_loadimage_node_carries(tmp_path):
    out = tmp_path / "typo.recipe.json"
    result = _reference_recipe(
        tmp_path, "--out", str(out), "--image-name", "ashen-reaver-frnt.png=cloud-abc.png"
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, f"INPUT_ is exit 1; got {result.exit_code}: {text!r}"
    assert "INPUT_IMAGE_NAME" in text, text
    assert "ashen-reaver-frnt.png" in text, "the refusal must name the key that missed"
    # The whole point: the operator is told what the graph DOES carry, so the typo is
    # fixable from the message alone without opening the graph JSON.
    assert "ashen-reaver-front.png" in text, text
    assert "two-hand-weapon.openpose.png" in text, text
    assert not out.exists(), "a refused --image-name must not leave a graph behind"


def test_recipe_names_every_unmatched_key_not_just_the_first(tmp_path):
    result = _reference_recipe(
        tmp_path,
        "--out", str(tmp_path / "x.json"),
        "--image-name", "ashen-reaver-front.png=cloud-ok.png",   # this one is real
        "--image-name", "nope-a.png=cloud-a.png",
        "--image-name", "nope-b.png=cloud-b.png",
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "nope-a.png" in text and "nope-b.png" in text, (
        f"a second bad pair would survive a first-wins refusal: {text!r}"
    )


def test_recipe_still_applies_an_image_name_that_matches_a_loadimage_node(tmp_path):
    """The flag keeps working exactly as today for the case it was built for.

    This is the regression guard on the refusal above: the check is additive pre-flight,
    not a change to `bind_cloud_names`, whose "missing keys stay" behaviour is untouched.
    """
    out = tmp_path / "ok.recipe.json"
    result = _reference_recipe(
        tmp_path,
        "--out", str(out),
        "--json",
        "--image-name", "ashen-reaver-front.png=cloud-upload-1.png",
        "--image-name", "two-hand-weapon.openpose.png=cloud-upload-2.png",
    )
    assert result.exit_code == 0, (result.stdout or "") + (result.stderr or "")
    assert sorted(_loadimage_names(out)) == ["cloud-upload-1.png", "cloud-upload-2.png"]
    data = json.loads(result.stdout)
    assert data["cloud_names"] == {
        "ashen-reaver-front.png": "cloud-upload-1.png",
        "two-hand-weapon.openpose.png": "cloud-upload-2.png",
    }


def test_recipe_echoes_the_whole_local_side_a_last_equals_split_produced(tmp_path):
    """`_parse_image_names` splits on the LAST `=` so a plate may contain one (F-b795e5ca).

    The new check must not undo that decision by reporting a prefix: here the local side
    is a name no node carries, and the refusal has to echo it whole.
    """
    result = _reference_recipe(
        tmp_path, "--out", str(tmp_path / "x.json"),
        "--image-name", "weird=name.png=cloud-upload.png",
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "weird=name.png" in text, (
        f"the refusal must echo the local side the LAST-= split produced: {text!r}"
    )


def test_recipe_without_image_name_is_untouched_by_the_new_check(tmp_path):
    out = tmp_path / "plain.recipe.json"
    result = _reference_recipe(tmp_path, "--out", str(out))
    assert result.exit_code == 0, (result.stdout or "") + (result.stderr or "")
    assert _loadimage_names(out) == ["ashen-reaver-front.png", "two-hand-weapon.openpose.png"]


# =========================================================================== F-763b6107
# `pcraft recipe`'s reason to exist is the Kontext reference-lock stitch, and
# `method=reference` is the only identity method that path can apply. MEASURED on the
# shipped tree: a zero-argument `pcraft recipe` exits 2 with GATE_CONDITIONING_UNSUPPORTED
# ("cannot apply method=ip_adapter. That is the SDXL encoder"), because the default
# contract is the SDXL example -- so the command's own quick-start demonstrates only that
# the command refuses, and neither `--contract`'s help nor the docstring said which
# contracts it CAN run.
#
# Two moves, tested separately because they land differently:
#   (a) the help/docstring name the identity method the command needs -- green here;
#   (b) the default `--contract` points at the method=reference example pair, which lands
#       in the SIBLING image-domain worktree (F-85852fb7: faction:ashen-pact-cloud +
#       char:ashen-reaver-cloud). EXPECTED RED IN THIS WORKTREE and green on the fold --
#       do not weaken, skip, or xfail it to force green locally.
#
# STABILITY.md covers `pcraft recipe`'s "flags and the emitted recipe graph". (b) renames
# no flag, but a bare invocation's OUTPUT changes for existing callers, so the refusal it
# used to produce is pinned below under an explicit `--contract` instead of being lost.


def _recipe_contract_option():
    import typer

    cmd = typer.main.get_command(app).commands["recipe"]
    return next(p for p in cmd.params if p.name == "contract")


def test_recipe_contract_help_names_the_identity_method_the_command_needs():
    help_text = (_recipe_contract_option().help or "").lower()
    assert "reference" in help_text, (
        "--contract's help must say which identity method this command can apply; "
        f"got: {help_text!r}"
    )


def test_recipe_default_contract_is_a_method_reference_example(tmp_path):
    """A zero-argument `pcraft recipe` must demonstrate the path the command exists for.

    EXPECTED RED UNTIL FOLD: the contract this default names ships in the sibling
    image-domain worktree. Pre-fold this exits on a store-resolution refusal naming
    char:ashen-reaver-cloud, which is the documented waiting state -- NOT a reason to
    weaken the assertion.
    """
    out = tmp_path / "default.recipe.json"
    result = runner.invoke(app, ["recipe", "--out", str(out), "--json"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, (
        f"bare `pcraft recipe` did not run: {text!r}. If this names "
        "char:ashen-reaver-cloud as unresolvable, that is the documented "
        "expected-red-until-fold state -- the sibling image-domain worktree has not "
        "landed the method=reference example pair yet."
    )
    data = json.loads(result.stdout)
    assert data["identity_method"] == "reference", data
    assert out.is_file()


def test_recipe_still_refuses_the_shipped_sdxl_contract_when_it_is_named(tmp_path):
    """The refusal a bare `recipe` used to produce, pinned where it now lives.

    Repointing the default must not soften the door: an ip_adapter contract handed to the
    Kontext recipe is still GATE_CONDITIONING_UNSUPPORTED, exit 2, with no graph written.
    """
    out = tmp_path / "sdxl.recipe.json"
    result = runner.invoke(
        app, ["recipe", "--contract", "char:ashen-reaver", "--out", str(out)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2, text
    assert "GATE_CONDITIONING_UNSUPPORTED" in text, text
    assert "ip_adapter" in text, text
    assert not out.exists(), "a refused recipe must not leave a graph behind"


# ====================================================== S1 CLI surface: regrade + calibrate
# Two thin verbs over libraries that land in SIBLING worktrees. Both are arg parsing, an
# emit and the existing error machinery -- no logic here, per the coordinator's shape.
#
# The tests split three ways on purpose:
#   * the argument contract this file OWNS (mutual exclusion, registration, help) -- green
#     now, because those refusals are decided before either library is reached;
#   * the SEAM (the entry points and keyword names the command bodies call) -- expected red
#     until fold, and the first thing to go green when the sibling lands;
#   * one real run-through for regrade, which is GPU-free because `pcraft bind` writes a
#     receipt with the deterministic stubs. Calibrate has no equivalent: scoring a holdout
#     runs the real verifiers, which is GPU work this suite does not do, so its fold proof
#     is the seam plus a coded-refusal check.
#
# EXPECTED RED IN THIS WORKTREE for the fold tests -- do not weaken, skip, or xfail them to
# force green locally.


def test_regrade_and_calibrate_are_registered():
    import typer as _typer

    commands = _typer.main.get_command(app).commands
    assert "regrade" in commands, sorted(commands)
    assert "calibrate" in commands, sorted(commands)


def test_regrade_refuses_when_neither_records_dir_nor_record_is_given(tmp_path):
    """Decided before the table is read, so the refusal names the operator's mistake."""
    result = runner.invoke(app, ["regrade", "--table", str(tmp_path / "nope.json")])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_REGRADE_TARGET" in text, text
    assert "--records-dir" in text and "--record" in text, text


def test_regrade_refuses_when_both_records_dir_and_record_are_given(tmp_path):
    result = runner.invoke(
        app,
        ["regrade", "--table", str(tmp_path / "nope.json"),
         "--records-dir", str(tmp_path), "--record", str(tmp_path / "r.json")],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_REGRADE_TARGET" in text, text


def test_regrade_help_says_it_reports_rather_than_gates():
    import typer as _typer

    body = (_typer.main.get_command(app).commands["regrade"].help or "").lower()
    assert "never gates" in body or "reports, never" in body, body
    assert "exit" in body, "a scripted verb must name its exit codes in --help"


def test_calibrate_help_says_it_emits_and_does_not_adopt():
    import typer as _typer

    body = (_typer.main.get_command(app).commands["calibrate"].help or "").lower()
    assert "adopt" in body, (
        "the whole discipline of this verb is emit-never-adopt; --help has to say so: "
        f"{body!r}"
    )
    assert "exit" in body, "a scripted verb must name its exit codes in --help"


def _retuned_candidate(tmp_path):
    """A table whose band values moved -- the input a re-grade exists to ask about."""
    from pcraft.domains.image.subdomains.sprite import THRESHOLDS_PATH

    data = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    data["version"] = "sprite.cal.candidate"
    for band in [*data["bands"].values(), data["default"]]:
        band["high"] = 0.96
    out = tmp_path / "candidate.calibration.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def test_regrade_reports_what_a_candidate_table_would_have_decided(tmp_path):
    """The corpus question, end to end and GPU-free: `bind` writes the receipt with stubs.

    EXPECTED RED UNTIL FOLD -- pcraft.core.gate.regrade lands in the sibling core-gate-loop
    worktree, and until it does the command body's import fails and the blanket backstop
    reports RUNTIME_UNEXPECTED. That is the documented waiting state; the assertions check
    the ERROR CODE STRING and the report line rather than the exit code alone, so the
    pre-fold ImportError cannot read as a pass.
    """
    records = tmp_path / "records"
    bind = runner.invoke(app, ["bind", "--records-dir", str(records)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")
    before = sorted(p.read_bytes() for p in records.glob("*.json"))
    assert before, "bind wrote no receipt"

    result = runner.invoke(
        app,
        ["regrade", "--table", str(_retuned_candidate(tmp_path)),
         "--records-dir", str(records)],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, (
        f"got the unclassified backstop instead of a re-grade: {text!r}. If this names "
        "pcraft.core.gate.regrade, that is the documented expected-red-until-fold state "
        "-- the sibling core-gate-loop worktree has not landed the module yet."
    )
    assert result.exit_code == 0, f"a re-grade reports and must not gate: {text!r}"
    assert "blocking flips total" in text, f"no corpus total line: {text!r}"
    assert sorted(p.read_bytes() for p in records.glob("*.json")) == before, (
        "a re-grade is a pure read; it re-stamped a receipt"
    )


def test_regrade_json_carries_the_corpus_totals_beside_the_reports(tmp_path):
    """EXPECTED RED UNTIL FOLD, same reason as above."""
    records = tmp_path / "records"
    bind = runner.invoke(app, ["bind", "--records-dir", str(records)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")

    result = runner.invoke(
        app,
        ["regrade", "--table", str(_retuned_candidate(tmp_path)),
         "--records-dir", str(records), "--json"],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, f"expected-red-until-fold: {text!r}"
    data = json.loads(result.stdout)
    assert data["receipts_total"] == len(data["receipts"])
    assert "blocking_flips_total" in data and "with_blocking_flips" in data
    assert data["table"] == "sprite.cal.candidate", data


def test_regrade_wraps_the_library_entry_points_the_command_calls():
    """The seam, restated here rather than imported, so a rename goes red in MY file.

    EXPECTED RED UNTIL FOLD (ModuleNotFoundError on the sibling module).
    """
    import inspect

    from pcraft.core.gate import regrade as lib

    assert callable(lib.regrade) and callable(lib.regrade_dir)
    assert list(inspect.signature(lib.regrade_dir).parameters) == ["records_dir", "candidate"]
    # The three the command body calls, split by what they ARE: `summary` is a method and
    # `flips`/`blocking_flips` are properties (so they live on the class), while `record_id`
    # is a model field (so it lives in model_fields). Asserting all four through `dir()`
    # measured green for the wrong reason on the properties and red on the field.
    for name in ("summary", "flips", "blocking_flips"):
        assert hasattr(lib.RegradeReport, name), f"RegradeReport lost {name!r}, the CLI prints it"
    assert "record_id" in lib.RegradeReport.model_fields, "the CLI labels each line with it"


def test_calibrate_wraps_the_harness_entry_points_the_command_calls():
    """EXPECTED RED UNTIL FOLD -- the harness lands in the sibling image-domain worktree.

    The seam and not a scoring run: `calibrate_from_manifest` runs the real verifiers over
    the holdout, which needs the [image] extra and GPU work this suite does not do. What
    the CLI actually depends on is the entry points and the KEYWORD NAMES it passes, so a
    rename on the sibling side goes red here instead of at an operator's first run.
    """
    import inspect

    from pcraft.domains.image.subdomains.sprite import calibrate as harness

    params = set(inspect.signature(harness.calibrate_from_manifest).parameters)
    assert {"contracts_dirs", "verifiers", "base_table"} <= params, sorted(params)
    assert callable(harness.write_table) and callable(harness.write_scored)
    for field in ("manifest", "rows", "scored", "bands", "table"):
        assert field in harness.CalibrationResult.model_fields, field


def test_calibrate_refuses_an_unreadable_manifest_without_a_traceback(tmp_path):
    """A missing holdout is a coded refusal, never a raw traceback.

    EXPECTED RED UNTIL FOLD: pre-fold the harness import fails and the backstop says
    RUNTIME_UNEXPECTED, which exits 2 exactly as the real IO_HOLDOUT_READ refusal does --
    so this checks the CODE STRING, not the exit code.
    """
    result = runner.invoke(
        app,
        ["calibrate", str(tmp_path / "absent.jsonl"), "--out", str(tmp_path / "v2.json")],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "Traceback" not in text, f"calibrate leaked a raw traceback: {text!r}"
    assert "RUNTIME_UNEXPECTED" not in text, (
        f"got the unclassified backstop: {text!r}. If this names "
        "pcraft.domains.image.subdomains.sprite.calibrate, that is the documented "
        "expected-red-until-fold state."
    )
    assert "IO_HOLDOUT_READ" in text, text
    assert not (tmp_path / "v2.json").exists(), "a refused calibrate must write no table"


def test_calibrate_reaches_the_shipped_store_with_no_contracts_dir(tmp_path, monkeypatch):
    """The promised default ("shipped sprite example") is a real store, not an empty one.

    Phase 9 (F1): `calibrate_from_manifest` turned `None` into an EMPTY root list instead
    of the shipped tree, so the first command the handbook publishes -- no --contracts-dir
    -- refused INPUT_UNKNOWN_CONTRACT from any directory, while `validate` on the very same
    default resolved the very same id. The store default is `load_store`'s now, which also
    restores the INPUT_EMPTY_STORE guard this path used to bypass. The invocation below is
    the published one: a manifest and --out, nothing else.
    """
    from pcraft.testing import write_solid_png

    monkeypatch.chdir(tmp_path)  # the default store must not depend on the caller's CWD
    image = write_solid_png(tmp_path / "hold.png")
    row = {"image": str(image), "contract": "char:ashen-reaver", "atom": "palette", "label": "present"}
    (tmp_path / "holdout.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = runner.invoke(
        app, ["calibrate", str(tmp_path / "holdout.jsonl"), "--out", str(tmp_path / "v2.json")]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "INPUT_UNKNOWN_CONTRACT" not in text, f"the default store is empty again: {text!r}"
    assert result.exit_code == 0, text
    assert (tmp_path / "v2.json").exists(), text


# ================================================== wave-13 S1 CLI surface: three new doors
# F-76b0940b (`gate` gets a multi-image door), F-62e7d1f0 (`pcraft new`, the contract
# scaffold verb) and F-2b04f0b8's CLI half (`pcraft resolve`, the disposition verb for an
# escalated receipt). Same three-way split the regrade/calibrate block above established:
#
#   * the argument contract this file OWNS -- green now, decided before any sibling
#     library is reached;
#   * the SEAM (entry points and keyword names the command bodies call) -- expected red
#     until fold, and the first thing to go green when the sibling lands;
#   * real GPU-free run-throughs where the machinery already exists. `gate --batch` is
#     entirely on this side of the seam -- the CLI builds the verifiers once and loops
#     `harness.evaluate`, which already takes a per-call image_path -- so its behaviour
#     tests are green here and stay green.
#
# EXPECTED RED IN THIS WORKTREE for the fold tests -- do not weaken, skip, or xfail them.


def _pngs(tmp_path, *names):
    from pcraft.testing import write_solid_png

    return [write_solid_png(tmp_path / name) for name in names]


# --------------------------------------------------------------------------- F-76b0940b
# One verifier construction, N images, one aggregate answer. The single-image invocation
# is byte-identical: its flags, its --json transcript shape and its 0/1/2/3/4 exit codes
# are covered by STABILITY.md and none of them move.


def test_gate_still_takes_one_image_and_emits_one_transcript_document(tmp_path):
    """The must-not-break. One IMAGE, no --batch: a single object, not an array."""
    [image] = _pngs(tmp_path, "one.png")
    result = runner.invoke(app, ["gate", str(image), "--json"])
    data = json.loads(result.stdout)
    assert isinstance(data, dict), f"the single-image document became an array: {data!r}"
    assert data["contract_id"] == "char:ashen-reaver"
    assert result.exit_code in {2, 3}, (result.stdout or "") + (result.stderr or "")


def test_gate_with_no_image_and_no_batch_still_explains_itself():
    """`gate` used to get this refusal from Click. It is ours now, and it must still
    exit 1 and still name the argument (tests/test_amend_cli.py pins both)."""
    result = runner.invoke(app, ["gate"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "IMAGE" in text, text
    assert "--batch" in text, text


def test_gate_accepts_several_images_and_names_each_one(tmp_path):
    images = _pngs(tmp_path, "a.png", "b.png")
    result = runner.invoke(app, ["gate", *[str(p) for p in images]])
    text = (result.stdout or "") + (result.stderr or "")
    for image in images:
        assert image.name in text, text
    assert "2 images" in text, f"no batch summary line: {text!r}"


def test_gate_batch_reads_a_directory(tmp_path):
    _pngs(tmp_path / "plates", "a.png", "b.png", "c.png")
    result = runner.invoke(app, ["gate", "--batch", str(tmp_path / "plates")])
    text = (result.stdout or "") + (result.stderr or "")
    assert "3 images" in text, text


def test_gate_batch_glob_selects_what_it_says_it_selects(tmp_path):
    _pngs(tmp_path / "plates", "a.png", "b.png")
    (tmp_path / "plates" / "notes.txt").write_text("not an image", encoding="utf-8")
    result = runner.invoke(
        app, ["gate", "--batch", str(tmp_path / "plates"), "--glob", "*.png"]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "2 images" in text, text


def test_gate_batch_summary_carries_the_skipped_census(tmp_path):
    """Phase 9 (N4): a half-installed gate skipped 15 of 18 required atom-checks and the
    batch summary -- the only line a batch user reads -- said only how many images failed.
    The single-image path already prints its census ("tiers executed: 1 of 2"); a batch
    must not say less than one image does. This suite runs with the model-tier packages
    absent (the same assumption every gate test here makes), so the census row is due.
    """
    images = _pngs(tmp_path, "a.png", "b.png")
    result = runner.invoke(app, ["gate", *[str(p) for p in images]])
    text = (result.stdout or "") + (result.stderr or "")
    assert "required atom-checks produced no score" in text, text
    assert "pcraft doctor" in text, text


def test_refused_paths_render_bare_not_repr(tmp_path):
    """Phase 9 (F5): `{path!r}` doubles every backslash in a Windows path, so two refusals
    printed `C:\\\\Users\\\\...` while sibling lines in the SAME handlers printed their
    paths bare. One path rendering, everywhere. On POSIX the doubled form cannot occur, so
    the regression assertions below only bite on Windows -- which is the only place the
    defect could ever render.
    """
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(b"not a real png")
    result = runner.invoke(
        app,
        ["new", "faction", "faction:p9", "--contracts-dir", str(tmp_path / "c"),
         "--reference-sheet", str(sheet)],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_SCAFFOLD_REFERENCE_SHEET" in text, text
    doubled = str(sheet).replace("\\", "\\\\")
    if doubled != str(sheet):
        assert doubled not in text, f"the refusal repr'd the path again: {text!r}"

    result = runner.invoke(app, ["gate", "--batch", str(tmp_path / "nodir")])
    text = (result.stdout or "") + (result.stderr or "")
    assert "INPUT_GATE_BATCH" in text, text
    doubled = str(tmp_path / "nodir").replace("\\", "\\\\")
    if doubled != str(tmp_path / "nodir"):
        assert doubled not in text, f"the refusal repr'd the path again: {text!r}"
    assert "notes.txt" not in text, text


def test_an_empty_batch_is_a_refusal_never_a_pass(tmp_path):
    """Gating nothing is not gating cleanly. Exit 0 here would tell a CI job that a
    directory of renders passed when the glob matched none of them."""
    (tmp_path / "plates").mkdir()
    result = runner.invoke(app, ["gate", "--batch", str(tmp_path / "plates")])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_GATE_BATCH" in text, text


def test_a_batch_dir_that_is_not_a_directory_is_refused_by_name(tmp_path):
    [image] = _pngs(tmp_path, "one.png")
    result = runner.invoke(app, ["gate", "--batch", str(image)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_GATE_BATCH" in text, text


def test_one_unreadable_image_does_not_void_the_other_results(tmp_path):
    """F-8cfaf7ec's must-not-break (3), on this side of the seam: preflight is per image.
    The worst SCORED outcome still decides, and the file nobody could read is named."""
    [good] = _pngs(tmp_path, "good.png")
    missing = tmp_path / "gone.png"
    result = runner.invoke(app, ["gate", str(good), str(missing)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code in {2, 3}, (
        f"one unreadable file collapsed the whole batch onto could-not-run: {text!r}"
    )
    assert "gone.png" in text, f"the unreadable image was not named: {text!r}"
    assert "good.png" in text, text


def test_a_batch_where_nothing_scored_is_could_not_run(tmp_path):
    """The other half of the ruling: exit 4 only when NOTHING scored."""
    result = runner.invoke(
        app, ["gate", str(tmp_path / "gone-a.png"), str(tmp_path / "gone-b.png")]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 4, text
    assert "GATE_UNAVAILABLE" in text or "IO_GATE_INPUT" in text, text


def test_a_batch_where_every_image_passes_exits_0(tmp_path, monkeypatch):
    from pcraft.domains.image import ImagePlugin
    from pcraft.testing import passing_verifiers

    monkeypatch.setattr(ImagePlugin, "verifiers", lambda self: passing_verifiers())
    images = _pngs(tmp_path, "a.png", "b.png")
    result = runner.invoke(app, ["gate", *[str(p) for p in images]])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, text
    assert "2 passed" in text, text


def test_a_batch_builds_its_verifiers_once_not_once_per_image(tmp_path, monkeypatch):
    """The whole reason the door exists (F-8cfaf7ec): each verifier caches its scorer on
    the INSTANCE, so N constructions is N model loads. MEASURED here by counting."""
    from pcraft.domains.image import ImagePlugin
    from pcraft.testing import passing_verifiers

    calls = {"n": 0}

    def counted(self):
        calls["n"] += 1
        return passing_verifiers()

    monkeypatch.setattr(ImagePlugin, "verifiers", counted)
    images = _pngs(tmp_path, "a.png", "b.png", "c.png")
    result = runner.invoke(app, ["gate", *[str(p) for p in images]])
    assert result.exit_code == 0, (result.stdout or "") + (result.stderr or "")
    assert calls["n"] == 1, f"built the verifier dict {calls['n']} times for 3 images"


def test_the_batch_json_is_an_array_keyed_by_image_path(tmp_path):
    """`--json` emits an array; every row says which pixels it graded.

    `image_path` on GateTranscript itself is F-8cfaf7ec's field and lands in the sibling
    core-gate-loop worktree. The CLI knows the path it passed to `evaluate` either way, so
    the key is present here before and after that fold -- this asserts the DOCUMENT, which
    is what a machine caller reads.
    """
    images = _pngs(tmp_path, "a.png", "b.png")
    result = runner.invoke(app, ["gate", *[str(p) for p in images], "--json"])
    rows = json.loads(result.stdout)
    assert isinstance(rows, list) and len(rows) == 2, rows
    assert {Path(r["image_path"]).name for r in rows} == {"a.png", "b.png"}
    assert all(r["contract_id"] == "char:ashen-reaver" for r in rows)


def test_an_unreadable_image_gets_a_row_in_the_json_array_too(tmp_path):
    """Silently dropping it would leave a caller counting rows and finding N-1."""
    [good] = _pngs(tmp_path, "good.png")
    result = runner.invoke(
        app, ["gate", str(good), str(tmp_path / "gone.png"), "--json"]
    )
    rows = json.loads(result.stdout)
    assert len(rows) == 2, rows
    bad = next(r for r in rows if Path(r["image_path"]).name == "gone.png")
    assert bad["error"]["code"] == "IO_GATE_INPUT", bad
    assert "verdicts" not in bad, "an image that was never read has no verdicts"


def test_gate_help_states_the_batch_aggregation_rule():
    """The ruling in the command's own words: a scripted caller must be able to learn the
    rule from --help, not from a swarm transcript."""
    import typer as _typer

    body = _typer.main.get_command(app).commands["gate"].help or ""
    assert "--batch" in body, body
    lowered = body.lower()
    assert "nothing scored" in lowered, f"the exit-4 condition is not stated: {body!r}"
    assert "worst" in lowered, f"the worst-scored-outcome rule is not stated: {body!r}"


# --------------------------------------------------------------------------- F-62e7d1f0
# `pcraft new` -- the CLI door onto core-contract-synth's scaffold primitive. A thin verb:
# it prompts nothing, writes where it is told, refuses to overwrite, and prints the
# LOADER's own verdict on what it just wrote.


def test_new_is_registered_and_names_both_levels():
    import typer as _typer

    commands = _typer.main.get_command(app).commands
    assert "new" in commands, sorted(commands)
    body = (commands["new"].help or "").lower()
    assert "character" in body and "faction" in body, body


def test_new_refuses_a_level_that_is_not_character_or_faction(tmp_path):
    result = runner.invoke(
        app, ["new", "monster", "mon:grendel", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_CONTRACT_LEVEL" in text, text
    assert not list(tmp_path.rglob("*.contract.json")), "a refused scaffold wrote a file"


def test_new_refuses_to_write_into_the_packaged_sprite_tree():
    """F-37f8764e's must-not-break (3): scaffold into the operator's tree, never over the
    shipped examples. Decided before the scaffold library is reached, so it is green now."""
    from pcraft.domains.image.subdomains.sprite import CONTRACTS_DIR

    result = runner.invoke(
        app, ["new", "character", "char:intruder", "--contracts-dir", str(CONTRACTS_DIR)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_SCAFFOLD_TARGET" in text, text
    assert not (CONTRACTS_DIR / "characters" / "intruder.contract.json").exists()


def test_new_refuses_to_overwrite_a_contract_that_already_exists(tmp_path):
    """The same O_EXCL discipline `asset_record.persist` uses, for the identical reason:
    a hand-authored contract is not something a scaffold gets to replace."""
    target = tmp_path / "characters" / "y.contract.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"id": "char:y", "level": "character"}', encoding="utf-8")
    before = target.read_bytes()

    result = runner.invoke(app, ["new", "character", "char:y", "--out", str(target)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2, text
    assert "IO_CONTRACT_EXISTS" in text, text
    assert target.read_bytes() == before, "the refused scaffold overwrote the file anyway"


def test_new_wraps_the_scaffold_entry_point_the_command_calls():
    """The seam, restated here rather than imported, so a rename goes red in MY file.

    Both names matter to the command body: `scaffold_contract` builds the Contract and
    `scaffold_json` is the CANONICAL on-disk text, so the CLI never spells the file format a
    second time. `store` is asserted because passing it is what turns `--extends` from a
    string into a checked reference.
    """
    import inspect

    from pcraft.core.contract import scaffold as lib

    assert callable(lib.scaffold_contract)
    assert callable(lib.scaffold_json)
    params = list(inspect.signature(lib.scaffold_contract).parameters)
    assert params[:2] == ["level", "contract_id"], params
    assert {"extends", "store"} <= set(params), params


def test_new_writes_a_contract_that_loads_back_through_the_store(tmp_path):
    """The whole promise of the verb: what it emits round-trips through the SAME loader a
    hand-written contract does, and the command prints the loader's own verdict."""
    result = runner.invoke(
        app, ["new", "faction", "faction:rooks", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, f"the unclassified backstop, not a scaffold: {text!r}"
    assert result.exit_code == 0, text
    written = list(tmp_path.rglob("*.contract.json"))
    assert len(written) == 1, written
    listed = runner.invoke(app, ["list", "--contracts-dir", str(tmp_path), "--json"])
    assert listed.exit_code == 0, (listed.stdout or "") + (listed.stderr or "")
    assert "faction:rooks" in {c["id"] for c in json.loads(listed.stdout)["contracts"]}


def test_new_extends_is_a_checked_reference_not_a_string(tmp_path):
    """Passing `store` to the primitive is what makes a bogus --extends a refusal here rather
    than a CONTRACT_MISSING_BASE surprise the next time anything resolves the tree."""
    seed = runner.invoke(app, ["new", "faction", "faction:rooks", "--contracts-dir", str(tmp_path)])
    assert seed.exit_code == 0, (seed.stdout or "") + (seed.stderr or "")

    result = runner.invoke(
        app,
        ["new", "character", "char:rook", "--extends", "faction:nope",
         "--contracts-dir", str(tmp_path)],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code != 0, text
    assert "faction:nope" in text, text
    assert not (tmp_path / "characters").exists(), "a refused scaffold wrote a file anyway"


def test_new_says_out_loud_that_what_it_wrote_is_a_stub(tmp_path):
    """F-37f8764e's must-not-break (1) as a CLI obligation: what a scaffold emits is visibly a
    STUB or it manufactures a gate nobody authored. Said on the command's own output, not
    buried in a `_note` inside the file.

    MEASURED against the real primitive: `scaffold_contract(level, id)` seeds NO atoms -- the
    skeleton is level/id/extends and the claims are the author's to write -- so the line has to
    cover the empty case, which is the ordinary one, and not only a seeded one.
    """
    result = runner.invoke(
        app, ["new", "faction", "faction:rooks", "--contracts-dir", str(tmp_path)]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, text
    assert "STUB" in text, f"the scaffold did not say what it wrote is a stub: {text!r}"
    written = list(tmp_path.rglob("*.contract.json"))
    assert str(written[0]) in text, "the STUB line must name the file to go and edit"
    assert "CONTRACT_NO_REQUIRED_ATOM" in text, (
        "the operator must be told that `pcraft gate` will refuse this contract until an atom "
        f"is raised to required, not left to discover it: {text!r}"
    )


def test_new_refuses_a_reference_sheet_and_names_where_that_capability_lives(tmp_path):
    """STATED JUDGMENT at the wave-13 fold. The sheet-driven scaffold
    (pcraft.domains.image.scaffold.scaffold_from_reference_sheet) derives both ids from the
    sheet, writes a faction+character PAIR and names both files itself, so driving it from this
    verb would mean silently ignoring LEVEL, ID and --out and reporting one file of two. It is
    refused by name instead, and the refusal says where the capability actually is.
    """
    sheet = tmp_path / "sheet.json"
    sheet.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        app,
        ["new", "faction", "faction:rooks", "--contracts-dir", str(tmp_path / "c"),
         "--reference-sheet", str(sheet)],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_SCAFFOLD_REFERENCE_SHEET" in text, text
    assert "scaffold_from_reference_sheet" in text, (
        f"the refusal must name the entry point that does have this capability: {text!r}"
    )
    assert not list(tmp_path.rglob("*.contract.json")), "a refused scaffold wrote a file"


def test_new_json_is_a_document_that_names_the_path_it_wrote(tmp_path):
    result = runner.invoke(
        app,
        ["new", "faction", "faction:rooks", "--contracts-dir", str(tmp_path), "--json"],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, text
    data = json.loads(result.stdout)
    assert data["id"] == "faction:rooks"
    assert data["level"] == "faction"
    assert Path(data["path"]).is_file()
    assert data["stub_atoms"] == [], data
    assert "extends" not in data, "an absent optional key is omitted, never emitted as null"


# --------------------------------------------------------------------------- F-2b04f0b8
# `pcraft resolve` -- the Director's decision against an ESCALATED receipt, recorded by
# `core.receipt.disposition.record_disposition` as an entry under the records dir's
# `dispositions/` SUBDIRECTORY. The receipt itself is never touched: persist()'s O_EXCL rule
# and STATE_REPLAY_DRIFT's own "Do not edit the receipt" both say so, and the subdirectory is
# what keeps every non-recursive *.json receipt scan seeing exactly what it saw before.

_ESCALATING = {"tabard": 0.05, "palette": 0.30, "face": 0.60}


def _escalated_receipt(tmp_path):
    from pcraft.sample import run_mock_loop

    result = run_mock_loop(records_dir=str(tmp_path), verifier_scores=_ESCALATING)
    assert result.decision == "escalated", result.decision
    [receipt] = list(Path(tmp_path).glob("*.json"))
    return receipt


def test_resolve_is_registered_and_says_it_does_not_make_the_asset_pass():
    """UNCERTAINTY_GATED_HUMANS: a resolution is evidence a human decided, never a way to
    auto-accept. --help has to say that, because exit 0 here means 'recorded'."""
    import typer as _typer

    commands = _typer.main.get_command(app).commands
    assert "resolve" in commands, sorted(commands)
    body = (commands["resolve"].help or "").lower()
    assert "escalated" in body, body
    assert "does not" in body and "pass" in body, (
        f"--help must say that recording a resolution does not make the asset pass: {body!r}"
    )
    assert "exit" in body, "a scripted verb names its exit codes in --help"
    assert "deferred" in body, (
        "the library knows a third resolution this flag does not offer; --help has to say so "
        f"rather than leave an operator to find it in the source: {body!r}"
    )
    assert "dispositions/" in body, "--help must name where the entry actually lands"


def test_resolve_refuses_a_verdict_that_is_neither_approve_nor_reject(tmp_path):
    receipt = _escalated_receipt(tmp_path)
    before = receipt.read_bytes()
    result = runner.invoke(
        app, ["resolve", str(receipt), "--verdict", "maybe", "--note", "hmm"]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_RESOLVE_VERDICT" in text, text
    assert receipt.read_bytes() == before


def test_resolve_requires_a_note(tmp_path):
    """A resolution with no reasoning is an auto-accept wearing a verdict. The note is
    required by the parser, so the refusal costs nothing to produce."""
    receipt = _escalated_receipt(tmp_path)
    result = runner.invoke(app, ["resolve", str(receipt), "--verdict", "approve"])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "note" in text.lower(), text


def test_resolve_refuses_a_receipt_that_is_not_escalated(tmp_path):
    """A bound receipt has nothing to resolve. Decided from the receipt's own `decision`
    field, before any write is attempted, so it is green ahead of the fold."""
    bind = runner.invoke(app, ["bind", "--records-dir", str(tmp_path)])
    assert bind.exit_code == 0, bind.stdout + (bind.stderr or "")
    [receipt] = list(tmp_path.glob("*.json"))
    before = receipt.read_bytes()

    result = runner.invoke(
        app, ["resolve", str(receipt), "--verdict", "approve", "--note", "looks fine"]
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 1, text
    assert "INPUT_RECEIPT_NOT_ESCALATED" in text, text
    assert "bound" in text, "the refusal must name the decision it actually found"
    assert receipt.read_bytes() == before


def test_resolve_never_edits_the_receipt_it_is_pointed_at(tmp_path):
    """The rule the whole feature hangs on, asserted at the only layer that can write:
    whatever else happens, the receipt's bytes do not move."""
    receipt = _escalated_receipt(tmp_path)
    before = receipt.read_bytes()
    result = runner.invoke(
        app, ["resolve", str(receipt), "--verdict", "approve", "--note", "ok in context"]
    )
    assert receipt.read_bytes() == before, "the receipt was rewritten in place"
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, f"the unclassified backstop: {text!r}"
    assert result.exit_code == 0, text


def test_resolve_wraps_the_decision_capture_entry_point_the_command_calls():
    """The seam, restated here rather than imported, so a rename goes red in MY file.

    `record_disposition` owns the entry, its subdirectory, the O_EXCL claim and the
    `disposition-write` compensator gate; the CLI passes exactly these keywords.
    """
    import inspect

    from pcraft.core.receipt import disposition as lib

    assert callable(lib.record_disposition)
    params = set(inspect.signature(lib.record_disposition).parameters)
    assert {"resolution", "resolved_by", "note"} <= params, sorted(params)
    # The CLI's two verdict words must map onto values the library will actually accept; a
    # mapping that drifted would be an INPUT_DISPOSITION_RESOLUTION at the operator's first run.
    from pcraft.cli import VERDICT_RESOLUTIONS

    assert set(VERDICT_RESOLUTIONS.values()) <= set(lib.RESOLUTIONS), VERDICT_RESOLUTIONS
    assert "deferred" not in VERDICT_RESOLUTIONS.values(), (
        "deferred is library-only for now; --help says so and this is what keeps it true"
    )


def test_resolve_records_the_decision_in_the_dispositions_subdir(tmp_path):
    """The entry lands in `<records-dir>/dispositions/`, and the records dir ITSELF is
    untouched -- which is the whole safety argument for the subdirectory: `regrade_dir`, the
    index and any caller globbing *.json non-recursively see exactly what they saw before, so
    a resolution can never be handed to `load()` as a malformed receipt.
    """
    receipt = _escalated_receipt(tmp_path)
    before = {p.name for p in tmp_path.glob("*.json")}

    result = runner.invoke(
        app,
        ["resolve", str(receipt), "--verdict", "approve", "--note", "hand-checked plate"],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert "RUNTIME_UNEXPECTED" not in text, text
    assert result.exit_code == 0, text
    assert {p.name for p in tmp_path.glob("*.json")} == before, (
        "the records dir gained a file; every receipt reader globs it non-recursively"
    )
    entries = list((tmp_path / "dispositions").glob("*.json"))
    assert len(entries) == 1, entries
    written = json.loads(entries[0].read_text(encoding="utf-8"))
    assert written["record_id"] == receipt.stem
    assert written["resolution"] == "accepted", "approve records the library's `accepted`"
    assert written["note"] == "hand-checked plate"
    assert str(entries[0]) in text, "the command must name the entry it wrote"


def test_resolve_json_names_both_the_typed_verdict_and_the_recorded_resolution(tmp_path):
    """Two vocabularies, and a caller must not have to guess the mapping: `verdict` is what
    was typed here, `resolution` is what a downstream reader will filter the entry on."""
    receipt = _escalated_receipt(tmp_path)
    result = runner.invoke(
        app,
        ["resolve", str(receipt), "--verdict", "reject", "--note", "wrong colours", "--json"],
    )
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, text
    data = json.loads(result.stdout)
    assert (data["verdict"], data["resolution"]) == ("reject", "rejected"), data
    assert data["decision"] == "escalated", "the receipt's own verdict is echoed unchanged"
    assert Path(data["resolution_path"]).parent.name == "dispositions", data
