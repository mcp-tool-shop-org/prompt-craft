"""Structured error shape for prompt-craft.

Ported from the mcp-tool-shop shipcheck error contract (Tier-1 shape: code / message /
hint / cause? / retryable?) and renamed. Every user-facing error carries a machine-readable,
namespaced ``code``, a human ``message``, and an actionable ``hint``. ``to_safe_text`` is the
end-user / LLM / MCP surface (no traceback); ``to_debug_text`` is gated behind ``--debug``.

Error-code namespaces (prefix -> CLI exit code):
    INPUT_   bad user input / missing args / invalid contract      -> exit 1
    CONFIG_  misconfiguration (missing key, bad threshold table)    -> exit 1
    CONTRACT_ contract resolution / relaxation violations           -> exit 1
    SYNTH_   synthesizer output defect (coverage, prose dump)       -> exit 2
    GATE_    gate / verifier discipline violations                  -> exit 2
    DEP_     missing optional dependency ([image]/[synth] extra)    -> exit 2
    IO_      filesystem read/write failure                          -> exit 2
    RUNTIME_ unexpected runtime crash                               -> exit 2
    STATE_   illegal state transition in the loop                  -> exit 2
    PARTIAL_ ran, required atom unconfirmed (human band)            -> exit 3

Per-code overrides (win over the prefix). Practice, not a paper: Nagios
0 OK / 1 WARNING / 2 CRITICAL / 3 UNKNOWN never overloads CRITICAL with
"could not run." We already spent 3 on PARTIAL_ (the WARNING analog).
Could-not-run therefore sits at 4, not 2:

    GATE_UNAVAILABLE  no required atom produced a score              -> exit 4
    IO_GATE_INPUT     path missing / not a file / unreadable         -> exit 4

The third and fourth overrides go the other way. A file written by a NEWER
build is well formed, not a crash, so it is user input like its contract
sibling CONTRACT_SCHEMA_UNSUPPORTED -- not an IO_ runtime fault. The rule is
the format's, not the receipt's, so the resolution entry beside the receipt
(F-2b04f0b8) takes the same override for the same reason:

    IO_RECORD_SCHEMA_UNSUPPORTED  receipt schema_version is from the future -> exit 1
    IO_DISPOSITION_SCHEMA_UNSUPPORTED  a resolution entry from the future   -> exit 1

CORRECTED IN PLACE (F-a2de5ab2). Both tables above had drifted from the maps
they describe: SYNTH_ was missing from the namespace list, and the
IO_RECORD_SCHEMA_UNSUPPORTED override (F-4846c12e) was added to STABILITY.md
and to _EXIT_BY_CODE but not here -- so the front-door table in the file that
DEFINES the mapping still read "IO_ ... -> exit 2", with the correction living
only in a comment forty lines below. This block is the only override list a
reader of this file will find, so it is now parsed and compared against
_EXIT_BY_CODE / _EXIT_BY_PREFIX by tests/test_stability_surface.py: adding an
entry to either map without adding its row here goes red.
"""

from __future__ import annotations

import re
import textwrap
import traceback
from collections.abc import Iterable, Sequence
from typing import Final

# --------------------------------------------------------------------------------------
# The rendering convention (F-00cc16d9 / F-6ddb888b / F-6acc1597 / F-9bd8360e).
#
# ONE convention, four human-facing surfaces: the gate transcript (``pcraft.gate_report``),
# the contrastive checkpoint (``core.gate.checkpoint``), the exit-contract refusals
# (``core.gate.exit_contract``) and the rendered error below. Each of the four had grown its
# own width behaviour -- which is to say none of them had one. MEASURED at 80 columns: 30 of
# 30 transcript rows overflowed (min 121), the five checkpoint entries measured 188-230, and
# 38 of 43 rendered hints overflowed. Every one of those overflows resumes at COLUMN 0, which
# is the column each artifact reserves for its own structure, so a wrapped tail renders at
# the same visual weight as a section header and only its wording tells them apart.
#
# The rules:
#   * a FIXED width, never a terminal-detected one, so every rendering is deterministic and
#     the string assertions and cp437/ASCII sweeps stay meaningful;
#   * the headline -- a verdict row, an ``error[...]`` line -- is one line, and it is the
#     only thing that owns column 0;
#   * everything secondary (the WHY, the band, what the instrument saw, the claim, the
#     advice) hangs on its own labelled line, indented under its content column;
#   * a wrapped continuation hangs at that same content column, so nothing below a headline
#     ever reaches the margin again.
#
# This lives here because ``pcraft.errors`` is the bottom of the import graph -- it imports
# nothing from the package -- so all four surfaces share one convention without a cycle.
# ASCII only, per the F-a6acaab1 cp437 doctrine: indentation and blank lines carry the
# hierarchy; never box glyphs, never colour.
# --------------------------------------------------------------------------------------

LINE_WIDTH: Final[int] = 80
"""The one width every human-facing surface renders to. Fixed, not detected."""

_SENTENCE_BREAK: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def wrap_block(text: str, *, first: str = "", hang: str = "", width: int = LINE_WIDTH) -> list[str]:
    """Wrap ``text``, prefixing the first line with ``first`` and every other with ``hang``.

    ``break_long_words`` and ``break_on_hyphens`` are both off: a hint that names
    ``pip install 'prompt-crafter[image]'`` or an atom id with a hyphen must survive as one
    searchable token, which is the whole point of printing it.
    """
    wrapped = textwrap.wrap(
        text,
        width=width,
        initial_indent=first,
        subsequent_indent=hang,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [f"{first}{text}".rstrip()]


def wrap_field(
    label: str, text: str, *, indent: int, label_width: int, width: int = LINE_WIDTH
) -> list[str]:
    """One labelled block: ``<indent><label><text>``, continuations under the text column."""
    return wrap_block(
        text,
        first=" " * indent + label.ljust(label_width),
        hang=" " * (indent + label_width),
        width=width,
    )


def wrap_sentences(
    label: str, text: str, *, indent: int, label_width: int, width: int = LINE_WIDTH
) -> list[str]:
    """``wrap_field``, but each sentence starts a fresh line so advice reads as steps.

    37 of 43 shipped hints are multi-sentence and 15 carry three or more; run together at one
    indent they read as a paragraph of prose rather than as a sequence of things to do.
    """
    out: list[str] = []
    hang = " " * (indent + label_width)
    for sentence in _SENTENCE_BREAK.split(text.strip()):
        if not sentence:
            continue
        first = (" " * indent + label.ljust(label_width)) if not out else hang
        out.extend(wrap_block(sentence, first=first, hang=hang, width=width))
    return out or wrap_field(label, text, indent=indent, label_width=label_width, width=width)


def tier_list(tiers: Sequence[int]) -> str:
    """``[0, 1]`` -> ``'T0 T1'`` -- the notation the verdict rows already use.

    The product shipped FOUR spellings of the tier census and two of them printed raw Python
    container repr into a human artifact, three lines from rows that were already writing
    ``T0``/``T1``. This is the one form (F-6acc1597).
    """
    return " ".join(f"T{t}" for t in tiers) or "none"


def id_list(ids: Iterable[str]) -> str:
    """``['tabard', 'palette']`` -> ``'tabard, palette'`` -- one list rendering, everywhere.

    ``exit_contract`` rendered the same data type two ways in one file: a quoted list repr on
    the GATE_UNAVAILABLE branch (174 measured characters, on the could-not-run path a plain
    ``pip install prompt-craft`` user hits first) and ``', '.join`` twenty lines below it.
    """
    return ", ".join(ids) or "none"


# prefix -> CLI exit code (Tier-2). 0 success, 1 user error, 2 runtime error, 3 partial.
_EXIT_BY_PREFIX: Final[dict[str, int]] = {
    "INPUT_": 1,
    "CONFIG_": 1,
    "CONTRACT_": 1,
    "SYNTH_": 2,
    "GATE_": 2,
    "DEP_": 2,
    "IO_": 2,
    "RUNTIME_": 2,
    "STATE_": 2,
    "PARTIAL_": 3,
}

# Could-not-run is not GATE_FAIL. The codes already differ; only the number
# a CI branch reads was collapsing them onto 2.
_EXIT_BY_CODE: Final[dict[str, int]] = {
    "GATE_UNAVAILABLE": 4,
    "IO_GATE_INPUT": 4,
    # CORRECTED IN PLACE (F-4846c12e). STABILITY.md introduces this code and
    # CONTRACT_SCHEMA_UNSUPPORTED together, as the same idea applied to the two on-disk
    # formats -- and they did not get the same exit code. The IO_ prefix mapped a receipt
    # from the future to 2 ("prompt-craft crashed") while its contract sibling got 1 ("fix
    # your input"). A receipt that is perfectly well formed and merely written by a newer
    # build is user input, not a runtime fault, so it takes the same 1 the sibling takes.
    "IO_RECORD_SCHEMA_UNSUPPORTED": 1,
    # F-2b04f0b8: the disposition is a second on-disk format with the same reader contract as
    # the receipt (a version marker, a supported set, a distinct answer for present-and-newer),
    # so it gets the same override rather than a new opinion about what "from the future" means.
    "IO_DISPOSITION_SCHEMA_UNSUPPORTED": 1,
}

DEFAULT_HINTS: Final[dict[str, str]] = {
    # CORRECTED IN PLACE (coordinator addition, same family as the hint sweep below). These
    # named ONLY the editable form -- pip install -e '.[image]' -- which is a command that
    # requires a CHECKOUT. A user who ran `pip install prompt-crafter` has no '.' to point at, so
    # the one actionable sentence they were given could not be run at all, and DEP_IMAGE_MISSING
    # is precisely the code that user hits first. The installed form leads; the editable form is
    # kept in parentheses for the contributor case, which is the smaller of the two audiences.
    "DEP_IMAGE_MISSING": "Install the GPU extra: pip install 'prompt-crafter[image]' (or, from a "
    "checkout, pip install -e '.[image]') -- torch + diffusers.",
    "DEP_SYNTH_MISSING": "Install the synth extra: pip install 'prompt-crafter[synth]' (or, from "
    "a checkout, pip install -e '.[synth]') -- DSPy + an LM backend.",
    "STATE_COMPILE_NEEDS_GATE": "Call compile_synthesizer from Python with an EXTERNAL gate_metric. "
    "The CLI does not generate pixels. --seed pins the scaffold artifact.",
    "STATE_COMPILE_NOT_WIRED": "Use optimizer='gepa' or 'miprov2'. Unknown names refuse.",
    "STATE_COMPILE_EMPTY": "The optimizer returned nothing to pin. Check the runner.",
    "GATE_SAME_FAMILY": "The generator and the gate verifier are the same model family. "
    "Use a different-family verifier -- a model must never be its own gate.",
    "GATE_FAMILIES_NOT_A_LIST": "Pass a list of verifier family names. A bare string is iterated as characters and the guard cannot fire.",
    "GATE_CLIPSCORE_BANNED": "CLIPScore is banned as the gate metric (bag-of-concepts, blind to "
    "binding/counts). Use SigLIP2 (Tier-0), VQAScore (Tier-1), or DSG (Tier-2).",
    "GATE_CLOUD_SUBMIT": "Flux wrote the Cloud recipe graph. Submit it with pcraft recipe "
    "--image-name; it does not run Kontext locally.",
    "GATE_CONDITIONING_UNSUPPORTED": "SDXL applies ControlNet OpenPose, IP-Adapter, "
    "method=lora, and InstantID. method=reference is the Cloud Kontext stitch + left "
    "crop + fist-only Fill recipe (`pcraft recipe`). Flux refuses IP-Adapter, LoRA, "
    "and InstantID. InstantID and IP-Adapter cannot share one generate.",
    "GATE_CONDITIONING_REF_MISSING": "Pass a real image path for every pose_ref, identity plate, "
    "and inpaint_from. A missing plate is a refuse, not a plain text-to-image render.",
    "CONTRACT_RELAXATION": "A character contract may not drop or relax a faction-required atom, "
    "and may not rewrite inherited content (claim, check_type, spatial, enum, depends_on). "
    "Raise the severity, or add a new id -- never substitute an existing id's content.",
    "IO_GATE_INPUT": "Pass a readable image file. A missing path is not a failed atom.",
    "GATE_UNAVAILABLE": "Install the [image] extra (pip install 'prompt-crafter[image]', or "
    "pip install -e '.[image]' from a checkout) so a verifier can score. This is not a failed "
    "atom; it is a gate that could not run.",
    # CORRECTED IN PLACE (F-56203d3d). This read "A required contract atom failed. Identity still
    # gates nothing. Exit 2." on the code every content failure lands on: sentence one restates
    # the code, sentence two is project jargon (the identity_subgate fence) answering a question
    # the operator did not ask, and between them there was no next move -- not "the atoms are
    # listed above", not "repair, or lower the severity in the contract", nothing. The
    # identity_subgate fact is true and belongs in the docs, not in the one line an operator gets
    # when the gate refuses. The half-installed sentence is here because it is the plain
    # ``pip install prompt-craft`` experience: with no [image] extra, five of the example's six
    # required atoms are SKIPPED and the sixth's FAIL is the only thing this code reports.
    "GATE_FAIL": "Fix the atom named above or lower its severity in the contract; the transcript "
    "lists each atom, its score and the band that graded it. If most required atoms are SKIPPED "
    "the gate is half-installed -- install the [image] extra (pip install 'prompt-crafter[image]', "
    "or pip install -e '.[image]' from a checkout) and re-run before treating this as a content "
    "failure.",
    "PARTIAL_UNCONFIRMED": "At least one required atom was scored but the roll-up is UNCERTAIN. "
    "This is the human band, not a pass.",
    "IO_RECORD_INVALID": "The receipt is JSON but does not match the AssetRecord schema. Re-bind, or pass --debug.",
    "IO_RECORD_SCHEMA_UNSUPPORTED": "This receipt was written by a NEWER prompt-craft than the "
    "one reading it. Upgrade prompt-craft to read it. Do NOT re-bind: the file is well formed, "
    "not corrupt, and re-binding would destroy a good receipt.",
    "CONFIG_THRESHOLDS_INVALID": "Each band needs high >= low and both in [0, 1]. Recalibrate or fix the table.",
    # F-09f30018: the version-disagreement refusal in orchestrate.run() used to reuse
    # CONFIG_THRESHOLDS_INVALID, which load_thresholds already raises for a structurally
    # malformed table. One covered, machine-parseable code then carried two unrelated meanings
    # -- "your table is broken" and "your table is fine but it is not the one you named" --
    # while the hint above described only the first. STABILITY.md tells callers to parse the
    # code, not the prose, so the two failures get two codes.
    "CONFIG_THRESHOLDS_VERSION_MISMATCH": "The table you named is not the table you passed. Pass "
    "the version of the table you are actually running (table.version), or leave "
    "config.thresholds_version unset to assert nothing.",
    # F-1d76b4ba, the same ruling applied once more. CONFIG_THRESHOLDS_INVALID means "this file
    # is malformed" and its hint prescribes fixing a band. A table that PARSES and simply does
    # not declare a band the gate will look up is a third, unrelated failure: the file is fine,
    # the numbers are fine, and the gate will quietly grade against `default`. Widening either
    # existing code to cover it is what "parse the code, not the prose" forbids.
    # ---------------------------------------------------------------- F-6f6fc50e
    # The labelled-holdout files. Three codes because they have three recoveries that have
    # nothing in common -- the same split IO_RECORD_READ / IO_RECORD_INVALID and
    # INPUT_EMPTY_STORE already draw, applied to the format the calibration instruction needs.
    "IO_HOLDOUT_READ": "Pass a readable JSONL file. A holdout manifest is one JSON object per "
    "line with the fields image, contract, atom and label; the scored companion adds score and "
    "band_key.",
    "INPUT_HOLDOUT_ROW": "One row is malformed and the message names its line number. Fix that "
    "row. A label is exactly one of present, absent or borderline, and a manifest row carries no "
    "score -- scores live in the scored companion file, which is a different format.",
    "INPUT_HOLDOUT_EMPTY": "The file parsed and contains no rows, so there is nothing to "
    "calibrate against. A band fitted on an empty holdout would be the generic seed the shipped "
    "table already warns about.",
    "CONFIG_THRESHOLDS_UNUSABLE": "This table parses and its numbers are fine; it just does not "
    "declare a band the gate will look up, so those atoms would grade against `default` with "
    "nothing in the transcript saying so. Add the named band, or narrow the keys you asked to "
    "check. This is an authoring-time refusal: nothing about loading or grading has changed.",
    "CONTRACT_CYCLIC_DEPENDS_ON": "Two or more atoms depend_on each other (or an atom depends_on "
    "itself), so no parent-first order exists and the gate cannot evaluate parents before "
    "children. Break the cycle in the contract's depends_on edges.",
    "INPUT_EMPTY_STORE": "Pass --contracts-dir at a tree that contains *.contract.json, or omit it to use the shipped sprite example.",
    "INPUT_IMAGE_NAME": "Pass --image-name as local.png=cloud-hash.png (repeatable).",
    "INPUT_CONTRACTS_DIR": "The path must be an existing directory.",
    "RUNTIME_UNEXPECTED": "An unclassified error escaped the command. Re-run with --debug to see "
    "the underlying traceback; this code is the backstop, not a diagnosis.",
    "RUNTIME_GENERATE_EXHAUSTED": "Every best-of-N generate() attempt failed before an image "
    "existed, so nothing was gated. The message names the last failure -- fix THAT code, not the "
    "seed. A failure that repeats on every attempt is not transient: check the generator's model "
    "load and its dependencies. Re-run with --debug for the underlying traceback.",
    # ---------------------------------------------------------------- F-5592ffad
    # `pcraft replay` is a covered command ("flags and drift refusals") and 100 percent of its
    # refusal surface shipped with this field empty, because to_safe_text() omits the hint LINE
    # entirely when hint resolves to ''. The three below are that command's whole refusal set.
    # The rest close the CLASS rather than the instances: every PromptCraftError construction
    # site in src/ now resolves advice, pinned by
    # tests/test_stability_surface.py::test_every_error_construction_site_in_src_resolves_a_hint,
    # which is what makes the NEXT hintless code go red instead of shipping.
    "STATE_REPLAY_DRIFT": "The receipt is NOT corrupt -- it was decided under a different "
    "contract, question DAG or threshold table than this run loaded. Either re-run replay with "
    "--thresholds pointed at the table the receipt names, or accept the retune and re-bind the "
    "asset. Do not edit the receipt.",
    "IO_RECORD_READ": "The path does not exist, or the file is not valid JSON -- the message says "
    "which. Point at a receipt under your records dir (pcraft bind prints the path it wrote).",
    "IO_THRESHOLDS_READ": "Pass --thresholds at a readable calibration JSON, or omit it to use "
    "the shipped sprite table (pcraft.domains.image.subdomains.sprite THRESHOLDS_PATH).",
    "CONFIG_THRESHOLDS_SCHEMA_UNSUPPORTED": "This calibration table was written by a NEWER "
    "prompt-craft than the one reading it. Upgrade prompt-craft to read it. Do NOT recalibrate or "
    "hand-edit the bands: the table is well formed, not miscalibrated.",
    "IO_RECORD_EXISTS": "A receipt already exists at that path and prompt-craft will not "
    "overwrite one. The message names the file. Move or delete it deliberately, or pass a "
    "different --records-dir; a bound receipt is the audit trail for pixels already in canon.",
    "CONTRACT_NO_REQUIRED_ATOM": "This contract declares no required atom, so the gate has "
    "nothing it is allowed to block on and a bind would assert nothing. Raise at least one atom "
    "to severity=required. Nothing here is a missing verifier.",
    "IO_CONTRACT_READ": "The path does not exist, or the file is not valid JSON. Point "
    "--contracts-dir at a tree of *.contract.json files.",
    "IO_ARTIFACT_READ": "The pinned compiled artifact could not be read. Run pcraft compile "
    "(offline GEPA), or pass --seed to write the scaffold artifact.",
    "IO_SCRIPT_MISSING": "The script this command runs is not in the installed package. Re-install "
    "it (pip install --force-reinstall prompt-crafter, or pip install -e . from a checkout) rather "
    "than editing the CLI.",
    "CONTRACT_SCHEMA_UNSUPPORTED": "This contract declares a $schema this build does not read. "
    "Upgrade prompt-craft, or set $schema to prompt-craft/contract.v1. The file is well formed, "
    "not corrupt.",
    "CONTRACT_MISSING_BASE": "The contract extends a base id that is not in the store. Add the "
    "base contract to --contracts-dir, or fix the extends id.",
    "INPUT_DUPLICATE_CONTRACT_ID": "Two files in the contract store declare the same id. Ids are "
    "the key the resolver and every receipt use; rename one.",
    "INPUT_NO_DOMAIN": "No domain plugin is registered. Install the [image] extra, or register a "
    "domain before calling this.",
    "SYNTH_COVERAGE_UNKNOWN_ATOM": "The synthesizer claimed coverage of an atom id the contract "
    "does not declare. Fix the synthesizer's atom_coverage keys -- a claim about an atom that "
    "does not exist covers nothing.",
    "RUNTIME_GENERATE_FAILED": "generate() raised. This is classified TRANSIENT, so the loop "
    "retries within its existing budget and this code is normally absorbed into an Attempt note "
    "or quoted by RUNTIME_GENERATE_EXHAUSTED. If you are reading it directly, re-run with --debug "
    "for the generator's own traceback.",
    "RUNTIME_GENERATOR_LOAD_FAILED": "The generator's model could not be loaded (weights, VRAM, "
    "or a broken install). This is SEMANTIC, not transient: another seed will not fix it. Check "
    "the model path and the [image] extra.",
    "RUNTIME_VERIFIER_CALL_FAILED": "A verifier raised while scoring. That is a defect, not a "
    "missing score, so it is not recorded as SKIPPED. The message names the instrument and the "
    "input; re-run with --debug for its traceback.",
    # ---------------------------------------------------------------- F-8cfaf7ec
    "INPUT_GATE_BATCH_EMPTY": "The batch gate was handed no images, so it decided nothing. Zero "
    "images that all passed is not a pass. Name at least one image to gate.",
    # ---------------------------------------------------------------- F-b0e6dde7
    # A typo'd records dir must not read as 'you have no receipts'. Same split, and the same
    # wording, as INPUT_CONTRACTS_DIR above: the path is user input, so the refusal is too.
    "INPUT_RECORDS_DIR": "The path must be an existing directory. A directory that exists and "
    "holds no receipts is an empty listing, not a refusal; a path that does not exist is this. "
    "pcraft bind creates the records dir when it writes its first receipt.",
    # ---------------------------------------------------------------- F-2b04f0b8
    # The resolution entry beside a receipt: what the Director decided at the escalation
    # checkpoint. A sibling file, never an edit of the receipt, so its refusals are its own.
    "INPUT_DISPOSITION_TARGET": "Only an escalated receipt has something for a human to resolve. "
    "A bound receipt already recorded its decision, and a resolution entry is not a general "
    "annotation channel. Point at the receipt the checkpoint was printed for.",
    "INPUT_DISPOSITION_ACTOR": "Name the person who decided. An unattributed resolution is not "
    "evidence that a human looked at the checkpoint, which is the only thing this record is for.",
    "INPUT_DISPOSITION_RESOLUTION": "A resolution is exactly one of accepted, rejected or "
    "deferred. The message names the values this build writes; anything else would be a verdict "
    "nothing downstream can read.",
    "IO_DISPOSITION_EXISTS": "A resolution entry already exists at that path and prompt-craft "
    "will not overwrite one, for the same reason it will not overwrite a receipt. Record the new "
    "decision under its own timestamp; decisions accumulate rather than replacing each other.",
    "IO_DISPOSITION_WRITE": "Check that the records dir is writable and has space. The receipt "
    "itself is untouched either way: a resolution is always a new file beside it.",
    "IO_DISPOSITION_READ": "The path does not exist, or the file is not valid JSON. Resolution "
    "entries live in the dispositions/ directory beside the receipts they resolve.",
    "IO_DISPOSITION_INVALID": "The file is JSON but does not match the resolution schema. Re-run "
    "the verb that records a decision rather than hand-editing the entry, or pass --debug.",
    "IO_DISPOSITION_SCHEMA_UNSUPPORTED": "This resolution entry was written by a NEWER "
    "prompt-craft than the one reading it. Upgrade prompt-craft to read it. The file is well "
    "formed, not corrupt, so do not delete it and re-decide.",
}


def exit_code_for(code: str) -> int:
    """Map an error code to its CLI exit code. Per-code overrides win; then prefix."""
    if code in _EXIT_BY_CODE:
        return _EXIT_BY_CODE[code]
    for prefix, exit_code in _EXIT_BY_PREFIX.items():
        if code.startswith(prefix):
            return exit_code
    return 2


class PromptCraftError(Exception):
    """The one structured error type. Rename of shipcheck's ProductError."""

    def __init__(
        self,
        code: str,
        message: str,
        hint: str | None = None,
        *,
        cause: BaseException | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.hint = hint or DEFAULT_HINTS.get(code, "")
        self.cause = cause
        self.retryable = retryable
        super().__init__(f"[{code}] {message}")

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)

    def to_safe_text(self) -> str:
        """No stack trace. For end users / LLM / MCP output.

        CORRECTED IN PLACE (F-9bd8360e). The hint was emitted as one unbroken line regardless
        of length, so the code / message / hint hierarchy this module's docstring promises
        survived exactly one visual line. MEASURED over all 43 DEFAULT_HINTS as they actually
        render (the ``  hint: `` prefix included): 38 exceeded 80 columns and 31 exceeded 120,
        with GATE_FAIL -- the code every content failure lands on -- at 379 characters. At 80
        columns that hint occupied 5 visual lines of which 4 began at COLUMN 0, the same column
        as ``error[GATE_FAIL]:``, so the two-space indent that distinguishes advice from the
        error was visible only on the first line.

        ``exit_code`` gets its own field. Seven hints ended with a prose ``Exit N.`` sentence,
        which buried a structured fact this class already owns at the tail of the longest
        wrapped run AND let it drift from ``exit_code_for()``, which is the number the CLI
        actually returns. The prose copies are deleted; this line cannot disagree with itself.

        The MESSAGE is deliberately left unwrapped. Messages are composed by the domains that
        raise them and some carry their own structure -- the contract loader's aggregate
        separates field errors with a literal ``" | "`` that its own tests segment on, and
        wrapping would break that delimiter across a newline. Under this module's convention
        the headline owns its line and only the secondary blocks hang, which is the same rule
        the verdict rows and the checkpoint follow.
        """
        lines = [f"error[{self.code}]: {self.message}"]
        if self.hint:
            lines.extend(wrap_sentences("hint:", self.hint, indent=2, label_width=6))
        lines.append(f"  exit: {self.exit_code}")
        if self.retryable:
            lines.append("  (retryable)")
        return "\n".join(lines)

    def to_debug_text(self) -> str:
        """Includes the underlying traceback. Only behind --debug."""
        text = self.to_safe_text()
        if self.cause is not None:
            tb = "".join(traceback.format_exception(type(self.cause), self.cause, self.cause.__traceback__))
            text += f"\n  caused by:\n{tb}"
        return text


def wrap_error(err: BaseException, code: str, hint: str | None = None) -> PromptCraftError:
    """Wrap any exception into the structured type, passing through if already one."""
    if isinstance(err, PromptCraftError):
        return err
    return PromptCraftError(code, str(err) or err.__class__.__name__, hint, cause=err)
