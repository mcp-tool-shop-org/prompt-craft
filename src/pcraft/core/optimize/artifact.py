"""The pinned compiled-synthesizer artifact (PIN_PER_STEP).

A ``CompiledProgram`` is the frozen output of an OFFLINE optimize run (GEPA): the instruction text
plus the selected few-shot demos plus a version. It is checked in as a PINNED file and **never
hand-edited** -- to change it, re-run ``optimize/compile.py`` and pin a new version. The artifact id
goes into every asset receipt, so a run is replayable bit-for-bit."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...errors import PromptCraftError

_DO_NOT_EDIT = (
    "PINNED COMPILED ARTIFACT - DO NOT HAND-EDIT. "
    "Regenerate via pcraft compile (core/optimize/compile.py) and pin a new version."
)


class CompiledProgram(BaseModel):
    model_config = ConfigDict(extra="ignore")
    warning: str = Field(default=_DO_NOT_EDIT, alias="_warning")
    program_id: str
    version: str
    instruction: str
    demos: list[dict] = Field(default_factory=list)
    generated_by: str = "scaffold-seed"  # "gepa" once a real offline compile produces it
    source_hash: str = ""  # hash of the trainset/metric that produced it

    @property
    def artifact_id(self) -> str:
        return f"{self.program_id}@{self.version}"


def load_pinned(path: str | Path) -> CompiledProgram:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise PromptCraftError("IO_ARTIFACT_READ", f"could not read compiled artifact {p}", cause=err) from err
    try:
        return CompiledProgram.model_validate(data)
    except ValidationError as err:
        # Same gap as the contract loader's (F-45c39f7d): the read and the JSON parse were
        # already structured, the schema validation was not, so a hand-edited or truncated
        # artifact -- the exact thing the DO-NOT-EDIT banner exists to catch -- escaped as a
        # raw pydantic ValidationError. IO_*_INVALID is this codebase's existing name for
        # "parsed as JSON, did not match the model" on a machine-written file; see
        # IO_RECORD_INVALID in errors.py, which says it for the receipt.
        raise PromptCraftError(
            "IO_ARTIFACT_INVALID",
            f"compiled artifact {p} is JSON but does not match the CompiledProgram schema",
            hint=(
                "This file is generated. Do not hand-edit it -- re-run the offline compile "
                "(core/optimize/compile.py) and pin a fresh artifact. Pass --debug to see "
                "which field failed."
            ),
            cause=err,
        ) from err


def pin(program: CompiledProgram, path: str | Path) -> Path:
    """Write the artifact with its DO-NOT-EDIT warning. Used only by the offline compile."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = program.model_dump(by_alias=True)
    payload["_warning"] = _DO_NOT_EDIT
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p
