"""F-CLI-FEAT-001 / 003 / 004 — the CLI can load a store that is not the shipped demo."""

from __future__ import annotations

import json

from typer.testing import CliRunner

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
