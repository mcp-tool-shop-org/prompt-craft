"""F-CLI-FEAT-001 / 003 / 004 -- the CLI can load a store that is not the shipped demo."""

from __future__ import annotations

import json

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
