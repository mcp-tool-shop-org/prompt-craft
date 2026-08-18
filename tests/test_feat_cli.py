"""F-CLI-FEAT-001 / 003 / 004 — the CLI can load a store that is not the shipped demo."""

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
    import pcraft.sample as sample

    monkeypatch.setattr(sample, "image_extra_present", lambda: False)
    result = runner.invoke(app, ["bind", "--no-mock", "--records-dir", str(tmp_path)])
    text = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 2
    assert "DEP_IMAGE_MISSING" in text
    assert "BOUND" not in text


def test_bind_no_mock_uses_the_plugin_generator(monkeypatch, tmp_path):
    """--no-mock is the live door. Stub generate so the suite stays GPU-free."""
    from pcraft.core.loop.generator_iface import GenerationResult
    from pcraft.domains.image import ImagePlugin
    from pcraft.domains.image.generator.sdxl_generator import SDXLGenerator
    from pcraft.testing import passing_verifiers, write_solid_png

    import pcraft.sample as sample

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
