"""The ``pcraft`` CLI: new | synth | gate | bind | resolve | list | validate | compile | replay | regrade | calibrate | sync-rules | demo | doctor | recipe | schema.

Errors use the structured shape (code/message/hint) and map to exit codes 0/1/2/3/4; raw
tracebacks are gated behind --debug. ``--json`` on the dumpable commands writes the pydantic
model to stdout and the human banner to stderr.

One deliberate exception to that table: an operator interrupt (Ctrl-C) exits **130**
(128 + SIGINT), the universal shell convention, and prints no structured error line.
That code is deliberately NOT folded into 0/1/2/3/4 -- exit 1 already means "bad user
input", so collapsing an interrupt into it would leave a scripted caller unable to tell
a typo from a Ctrl-C. Pinned in tests/test_amend_cli.py by
``test_an_interrupted_run_exits_130_outside_the_documented_code_table``. (F-df34f27e)"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import shutil
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

import typer
from pydantic import BaseModel, ConfigDict

# Typer 0.26 vendored Click as `typer._click`; 0.25 and earlier use the standalone
# `click` package; 0.27 moved Abort OUT of the vendored module into typer's own
# `typer.exceptions` and ships no `click` at all. pyproject declares
# `typer>=0.12,<0.28`, so all three layouts are inside the supported range and 0.27 is
# the top of it -- the ceiling is what makes that claim checkable on every install
# rather than a hope about future releases, and it ratchets forward deliberately (see
# pyproject's note beside the pin). The private-module import below
# broke twice, each time at import (before any command runs): once as
# ModuleNotFoundError on <0.26, then on 0.27 as ImportError from a module that still
# EXISTS -- which a `except ModuleNotFoundError` does not catch, so the "portable"
# fallback was unreachable exactly when needed, and the fallback's `click` no longer
# exists there anyway.
#
# Abort needs none of this: `typer.Abort` is public on every supported layout and is
# identity-equal to whatever class the active machinery raises (measured: on 0.26.7 it
# IS the vendored click Abort; on 0.27.2 it is typer.exceptions.Abort). Prefer the
# public name; keep the two-branch import only for ClickException, which stayed in the
# vendored module on >=0.26 and in real click before that.
from typer import Abort as _ClickAbort

try:
    from typer._click.exceptions import ClickException as _ClickException
except ModuleNotFoundError:  # typer < 0.26 -- click is a real dependency there
    # The ClickException import is WRAPPED because it exceeds line-length, and the ignore
    # must therefore sit on the statement's FIRST line: mypy does not apply a `type: ignore`
    # found on an inner line of a parenthesised import. Adopting isort wrapped this line and
    # left the comment inside, which silently detached the suppression -- caught by mypy in a
    # CI-equivalent venv, not locally. Do not move it back inside the parentheses.
    from click.exceptions import (  # type: ignore[assignment,no-redef]
        ClickException as _ClickException,
    )
from typer.core import TyperGroup

from .. import package_version, version_coherence
from ..errors import PromptCraftError, id_list, wrap_error
from ..gate_report import format_transcript  # local helper (see below)


class _ExitContractGroup(TyperGroup):
    """Give Click/Typer's own parser errors exit code 1, never this contract's 2.

    A mistyped flag, a missing argument, or an unknown (sub)command never reaches any
    command body -- Click validates argv before ``self.invoke(ctx)`` runs -- so no
    ``except PromptCraftError`` below ever sees it. Left alone, Click's ``UsageError``
    family (``MissingParameter`` / ``NoSuchOption`` / ``BadParameter`` /
    ``BadArgumentUsage`` / a bare ``UsageError`` for "no such command" or "missing
    command") exits 2 by the library's own default -- colliding head-on with errors.py's
    own ``GATE_``/``DEP_``/``IO_``/``RUNTIME_``/``STATE_`` exit 2 ("it ran, and a
    required atom failed"). A mistyped command is not that. (F-fb4f116a)

    ``standalone_mode=False`` is forced on the inner call so a Click parser exception
    propagates here as a distinguishable, catchable type instead of Click's own
    ``main()`` pre-converting it to a bare ``SystemExit(2)`` -- by the time that
    conversion has happened there is no way left to tell "the parser refused this" apart
    from a deliberate ``typer.Exit(2)`` (GATE_FAIL). ``typer.Exit``/``typer.Abort`` --
    what every command below raises for its OWN exit code -- subclass ``RuntimeError``,
    not Click's ``ClickException``, so they are a structurally different type and this
    override can never intercept one. The trade-off: with ``standalone_mode=False``,
    every OTHER path stops calling ``sys.exit`` internally and returns the code instead
    -- so this override has to replay that exit itself (the final line).
    """

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        # The single funnel for every invocation -- the console script (`pcraft.cli:app` ->
        # Typer.__call__ -> get_command(...)(...) -> this), `python -m pcraft`, and
        # `python -m pcraft.cli` all arrive here, and they arrive BEFORE Click renders help
        # or dispatches a command body. That is the one place a stdio decision can be made
        # early enough to cover both.
        _configure_stdio()
        try:
            rv = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except _ClickException as exc:
            exc.show()
            sys.exit(1)  # INPUT_-class: bad user input -- never GATE_'s exit 2
        except _ClickAbort:
            # NOT reachable for Ctrl-C, and kept anyway (F-df34f27e). typer converts a
            # KeyboardInterrupt to Exit(130) internally (core.py:197-198), never to Abort,
            # so an interrupt returns through the fall-through below instead of arriving
            # here. Abort still reaches this clause by its other route: core.py:194-196
            # turns a bare EOFError into Abort(), and core.py's own handler re-raises it
            # untouched under standalone_mode=False. Abort subclasses RuntimeError, so
            # nothing else here would catch it -- deleting this clause as "dead" trades a
            # one-line banner for a raw traceback. Both halves are pinned in
            # tests/test_amend_cli.py (the interrupt code, and this branch firing).
            typer.echo("Aborted!", err=True)
            sys.exit(1)
        # Also the interrupt path: super().main() RETURNS 130 with no exception raised,
        # because standalone_mode=False makes core.py's outer Exit handler return the code
        # instead of exiting. 130 passes through deliberately -- see the module docstring.
        sys.exit(rv if isinstance(rv, int) else 0)


app = typer.Typer(
    add_completion=False,
    help="Contract-driven generative-asset production.",
    cls=_ExitContractGroup,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"pcraft {package_version()}")
        # stdout stays exactly one bare version line -- that shape is scripted and covered.
        # A stale dist-info makes the line above a lie (F-4d031e47), so the contradiction
        # is said out loud on stderr, where it cannot corrupt a `pcraft --version` capture.
        note = version_coherence()
        if note is not None:
            typer.echo(f"warning: {note}", err=True)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        help="Print the installed version and exit.",
        callback=_show_version,
        is_eager=True,
    ),
) -> None:
    """Contract-driven generative-asset production."""


def _configure_stdio() -> None:
    """Choose this CLI's output encoding instead of inheriting the console codepage.

    Python derives stdout/stderr encoding from the locale or console codepage with
    ``errors='strict'``, and this CLI used to just write through it. Every command echoes
    back user-supplied path and id content -- a ``--contracts-dir`` under a non-English
    directory or user name is ordinary input, not adversarial -- and that content broke the
    output two ways, both measured against a real subprocess (F-90a9872f):

    * a path representable in the ambient codepage but not in ASCII exited **0** with a
      complete-looking ``--json`` document on stdout whose bytes were not valid UTF-8, so a
      caller's ordinary ``json.loads(stdout.decode('utf-8'))`` failed on a success;
    * a path outside the codepage raised ``UnicodeEncodeError`` from inside ``_say``, caught
      only by the outer backstop, so a found contract exited 2 as ``RUNTIME_UNEXPECTED``
      with **zero bytes** on stdout -- a representation failure read as a runtime one.

    This is the same class the module already fixed four times for its own static help
    strings; it survived on the one vector an ASCII sweep of the source cannot reach.

    An explicit ``PYTHONIOENCODING`` is left ALONE. It is an operator override -- the
    honest simulation of a legacy console, and what
    ``test_every_rendered_help_page_encodes_on_a_cp437_console`` pins -- so silently
    overruling it would delete a real signal and turn those tests vacuous. The two guards
    that survive an override carry the rest: ``_encodable`` below degrades human text
    instead of raising, and ``_emit_model`` escapes the ``--json`` document to pure ASCII,
    which every codepage can represent.

    ``backslashreplace`` rather than ``replace``: the escapes name the characters that could
    not be written (``\\u6f22``), where ``?`` would silently destroy them.
    """
    if os.environ.get("PYTHONIOENCODING"):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # a replaced stream that is not a TextIOWrapper
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError, LookupError):
            # A stream that will not change encoding can still stop raising. Failing to
            # improve the output is never a reason to take the command down.
            with contextlib.suppress(ValueError, OSError, LookupError):
                reconfigure(errors="backslashreplace")


def _encodable(text: str, stream: Any) -> str:
    """Text this stream can actually write, with anything it cannot represent escaped.

    The fallback for the case ``_configure_stdio`` deliberately does not touch: an operator
    who pinned ``PYTHONIOENCODING`` to a legacy codepage still gets output, degraded
    readably, instead of a ``UnicodeEncodeError`` that takes the whole command down and
    reports a successful lookup as an unclassified runtime failure.
    """
    errors = getattr(stream, "errors", None)
    if errors and errors != "strict":
        return text  # the stream already degrades on its own
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return text
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, "backslashreplace").decode(encoding, "replace")
    return text


def _emit(err: PromptCraftError, debug: bool) -> None:
    # Error text names paths too (INPUT_CONTRACTS_DIR quotes the directory it refused), so
    # the refusal has to survive the same consoles the success path does.
    typer.echo(_encodable(err.to_debug_text() if debug else err.to_safe_text(), sys.stderr), err=True)
    raise typer.Exit(code=err.exit_code)


def _say(text: str, *, as_json: bool = False) -> None:
    """Human text. When ``--json``, the banner goes to stderr so stdout stays a document."""
    typer.echo(_encodable(text, sys.stderr if as_json else sys.stdout), err=as_json)


# ---------------------------------------------------------------- layout (human channel)
#
# STABILITY.md puts human-readable output wording and layout under "Not covered" and sends
# machine callers to ``--json``; everything below moves characters on the human channel only
# and leaves every document byte-identical.
#
# The shape these three helpers converge on is the one the npm launcher already uses for its
# own multi-line output (``npm/bin/pcraft.mjs``): a headline at column 0, then the body
# indented under it, with blank lines separating blocks and anything copy-pasteable alone on
# its own row. Pure ASCII -- the structure is carried by spacing, not by glyphs or colour --
# so it survives every codepage ``_encodable`` has to write through.


def _wrap(text: str, width: int, initial: str, subsequent: str) -> list[str]:
    """One logical line as however many physical rows the terminal allows.

    ``break_long_words`` and ``break_on_hyphens`` are both off: the values in this output are
    atom ids, band keys and hyphenated colour words (``grey-ash``, ``no_rival_colours``), and
    a wrap that splits one of them mid-token produces a string the reader cannot search for.
    A token wider than the terminal overruns rather than being cut in half, which is the less
    damaging of the two failures.
    """
    return textwrap.wrap(
        text,
        width=max(width, len(subsequent) + 20),
        initial_indent=initial,
        subsequent_indent=subsequent,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [initial.rstrip()]


def _term_width(default: int = 80) -> int:
    """Columns to wrap human blocks to. ``COLUMNS`` wins, then the tty, then 80.

    ``shutil.get_terminal_size`` reads ``COLUMNS`` first, which is what the help pages already
    honour, so a wrapped block and the help page it sits beside agree about the geometry.
    Capped at 100: past that, prose lines get long enough that the eye loses the line it is
    on, and every other line this CLI prints was already written to fit inside 80.
    """
    return min(shutil.get_terminal_size(fallback=(default, 24)).columns, 100)


# ``version_coherence`` ends its warning with the one command that fixes it, parenthesised.
# That is the actionable half, and a parenthetical at the tail of a 219-character string is
# where it is least likely to be seen. Pulled out here and given its own row rather than
# reworded at the source: the same string is the ``version_warning`` field of the ``--json``
# DoctorReport, and rewriting it would change a document. Pinned from the other side by
# ``test_the_warning_the_shipped_check_produces_is_the_one_that_was_measured``.
_REMEDY = re.compile(r"[\s;,]*\((?:reinstall|fix|run):\s*(?P<cmd>[^()]+)\)\s*\Z")


def _version_mismatch_lines(warning: str, width: int) -> list[str]:
    """``doctor``'s loudest line, wrapped so it stays a CHILD of the version above it.

    The warning was emitted as one string whose entire structure was a two-space indent, so
    at 80 columns it soft-wrapped onto three rows of which two began at column 0 -- the same
    visual level as the sibling top-level rows (``python 3.14.5  (ok; need >= 3.11)``). The
    remedy, being last, landed at column 0 on row three, where it read as an unrelated status
    rather than as the fix for the warning three rows above (F-3c91e814).

    Four-space continuation keeps every row subordinate to ``pcraft <version>``; ``fix:`` on
    its own row is scannable and copy-pasteable. A warning that does not end in a remedy
    parenthetical still gets the wrap -- half the fix beats none.
    """
    remedy = _REMEDY.search(warning)
    body = warning[: remedy.start()] if remedy else warning
    body = body.rstrip(" ;,.")
    lines = _wrap(f"VERSION MISMATCH: {body}.", width, "  ", "    ")
    if remedy is not None:
        lines.append(f"    fix: {remedy.group('cmd').strip()}")
    return lines


def _reason_lines(reason: str, width: int) -> list[str]:
    """A multi-line decision reason as an indented block under the ``decision:`` headline.

    Since wave-8 an escalation's ``reason`` IS the ``build_checkpoint`` artifact -- a headline
    plus one ``  - `` bullet per unconfirmed atom -- and it was being interpolated into
    ``decision: {D}  ({reason})``. MEASURED: one ``_say`` call of 911 characters whose opening
    parenthesis sat at column 21 and whose closing one landed glued to a question mark four
    lines later; ``attempts:`` appeared only after it, and the bullets (204/225/157/199 chars)
    soft-wrapped with zero continuation indent, so the tail of one ran straight into the next
    bullet's marker. The one block written to be read by a person was the only one with no
    visual frame at all (F-1e1af911).

    Bullets stay contiguous -- the six-space continuation, not a blank line, is what separates
    one from the next -- and the blank after the headline is what separates summary from
    detail. The bullet text is re-wrapped, never re-parsed: its content is
    ``core.gate.checkpoint``'s to compose, and this is the layer that decides where it breaks.
    """
    # Composed-seam ruling (wave-10 fold): checkpoint.py now composes AND wraps its own
    # body under the errors.py convention (fixed width, hanging label columns), so this
    # layer must not strip or re-wrap it -- doing so flattened the claim/thought/chose
    # columns back to the block margin and orphaned wrapped continuations at column 2.
    # One wrap authority per line: the head (a single sentence, unformatted) is wrapped
    # HERE; every body row is pre-formatted THERE and only gets the block's two-space
    # frame, internal indentation preserved. Checkpoint content is <=78 wide, so framed
    # rows stay <=80.
    head, _, rest = reason.partition("\n")
    lines = _wrap(head, width, "  ", "  ")
    body = rest.splitlines()
    while body and not body[-1].strip():
        body.pop()
    if any(row.strip() for row in body):
        lines.append("")
    for row in body:
        lines.append(f"  {row}" if row.strip() else "")
    return lines


def _emit_model(model: BaseModel, **extra: Any) -> None:
    """The ``--json`` document, escaped to pure ASCII.

    ``extra`` carries ADDITIVE keys the CLI knows and the model does not -- today only
    ``receipt_path`` (F-5b783e17), which is a property of the invocation (``--records-dir``
    plus what ``persist`` actually wrote) rather than of the orchestration result. A key with
    nothing to say is OMITTED rather than emitted as ``null``: ``null`` reads as "there is a
    receipt path and it is empty", which is the opposite of "no receipt was written".

    ``model_dump_json`` emits raw UTF-8, which is only writable when the console agrees.
    Re-serialising the value pydantic produced with ``ensure_ascii`` makes the document
    representable in every codepage -- ASCII is a subset of all of them -- so ``--json``
    stays parseable even where ``_configure_stdio`` steps aside for an operator override.
    ``json.loads`` turns the ``\\uXXXX`` escapes back into the original characters, so this
    changes the document's bytes and not its value.

    The round trip goes through ``model_dump_json`` rather than ``model_dump(mode="json")``
    so pydantic's own serialisers stay the authority on what the value IS; only the encoding
    of that value changes here.
    """
    doc = json.loads(model.model_dump_json())
    doc.update({key: value for key, value in extra.items() if value is not None})
    _emit_json(doc)


def _emit_json(doc: Any) -> None:
    """The one ``--json`` serialisation, for the commands whose document is not one model.

    ``_emit_model`` above is the single-model case and now routes through here, so the
    encoding decision it documents at length (pure ASCII, so the document stays parseable
    on every codepage) has ONE spelling rather than one per command. ``pcraft regrade``
    reports on a corpus -- ``regrade_dir`` answers with a list -- and a list is not a
    ``BaseModel``; copying the echo line into it would have made the second spelling free
    to drift from the first, which is the defect the shared ``_DEBUG_HELP`` string and
    ``harness.verdict_reason`` were both extracted to prevent.
    """
    typer.echo(json.dumps(doc, indent=2, ensure_ascii=True))


_DEBUG_HELP = (
    "Print the full traceback and the validator's complete report instead of the one-line refusal."
)
"""One shared string for the flag every command offers (F-339753d3).

``--debug`` was declared as a bare ``typer.Option(False)`` on all twelve commands, so each help
page rendered ``--debug --no-debug [default: no-debug]`` with no description -- while the CLI's
own refusals actively send users here: the aggregated CONTRACT_INVALID message truncates itself
with "(+1 more, see --debug)" and its hint reads "Re-run with --debug for pydantic's full
report". The one flag the errors tell you to reach for was the one flag --help declined to
explain. Shared rather than copied twelve times so the pages cannot drift apart the way
``--contract`` did (documented on synth/validate/recipe, blank on gate/bind)."""


class ListedContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: str


class StoreListing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contracts: list[ListedContract]


class ValidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    lineage: list[str]
    required: list[str]
    must_not: list[str]
    questions: int


class ScaffoldReport(BaseModel):
    """What ``pcraft new`` wrote, as the LOADER read it back (F-62e7d1f0).

    Every field here is a fact about the file on disk after it was re-read through the same
    ``ContractStore.resolve`` a hand-written contract goes through -- never a copy of what the
    scaffold intended. ``stub_atoms`` is the list the human line says out loud: the atoms that
    still need a real claim and a deliberate severity before this contract gates anything.

    ``extends`` is NOT a field here on purpose: it is absent for a faction and would then have
    to be emitted as ``null``, which reads as "it extends nothing in particular" rather than
    "this level has no base". It travels as an ``_emit_model`` extra instead, which omits a key
    with nothing to say -- the same rule ``receipt_path`` follows.
    """

    model_config = ConfigDict(extra="forbid")
    id: str
    level: str
    path: str
    lineage: list[str]
    required: list[str]
    must_not: list[str]
    stub_atoms: list[str]


class ResolutionReport(BaseModel):
    """What ``pcraft resolve`` recorded against an escalated receipt (F-2b04f0b8).

    A CLI-owned document, deliberately: the ``Disposition`` FILE's schema belongs to
    ``core.receipt.disposition``, and this is the invocation's own answer -- which receipt,
    which verdict, who, and where the entry landed. ``decision`` is the receipt's own field,
    echoed unchanged, so a machine caller can see for itself that recording a resolution did
    not rewrite the receipt's verdict.

    ``verdict`` and ``resolution`` are BOTH here and are not redundant: ``verdict`` is the word
    the operator typed at this CLI (approve/reject) and ``resolution`` is the word written into
    the entry on disk (accepted/rejected), which is what a downstream reader filters on. A
    document that carried only one of them would make a caller guess the mapping.
    """

    model_config = ConfigDict(extra="forbid")
    record_id: str
    receipt_path: str
    decision: str
    verdict: str
    resolution: str
    note: str
    resolved_by: str
    resolution_path: str


class ExtraStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    present: bool
    modules: dict[str, bool]


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    python: str
    python_ok: bool
    extras: list[ExtraStatus]
    store_ok: bool
    store_ids: list[str] = []
    store_error: str | None = None
    thresholds_version: str | None = None
    # Additive, both defaulted: `version` above is read from installed metadata, which can
    # be stale (F-4d031e47 -- measured at 0.2.1 against a 1.0.0 tree). Reporting a number
    # with no way to say "and it disagrees with the source" is the defect. Existing readers
    # of this document are unaffected; nothing was renamed or removed.
    version_coherent: bool = True
    version_warning: str | None = None
    # Also additive, also defaulted (F-5b655328). `python` above is a bare version string
    # ('3.14.5'), which on a machine with more than one interpreter meeting the same floor
    # -- pyenv, conda, a project venv beside a global install, or the npm launcher's own
    # PCRAFT_PYTHON candidate list -- cannot say WHICH one answered. doctor is the one
    # command whose whole job is answering that, and it could not. `pcraft_python` is the
    # other half of the diagnosis: what the operator configured, beside what actually ran.
    executable: str = ""
    pcraft_python: str | None = None


@app.command()
def synth(
    contract: str = typer.Option("char:ashen-reaver", help="contract id to synthesize"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    as_json: bool = typer.Option(False, "--json", help="emit SynthResult as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Synthesize a prompt from a contract (deterministic template synthesizer)."""
    from ..core.synth.signature import TemplateSynthesizer
    from ..sample import _encoder_rules, load_workspace

    try:
        _store, resolved, _t, compiled = load_workspace(
            contracts_dirs=contracts_dir or None, thresholds=thresholds, contract_id=contract
        )
        result = TemplateSynthesizer(compiled).synthesize(resolved, _encoder_rules())
        _say(f"prompt: {result.prompt}", as_json=as_json)
        _say(f"negative: {result.negative_prompt}", as_json=as_json)
        _say(f"backend: {result.backend} (degraded={result.degraded})", as_json=as_json)
        _say("atom_coverage:", as_json=as_json)
        for atom_id, phrase in result.atom_coverage.items():
            _say(f"  {atom_id}: {phrase}", as_json=as_json)
        if as_json:
            _emit_model(result)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


BATCH_GLOB_DEFAULT = "*.png"
"""What ``--batch`` picks up when the operator does not say. Named, not inlined, so the
default in the signature and the one the help string quotes cannot drift apart."""

# ---------------------------------------------------------------- gate: the multi-image door
#
# F-76b0940b / F-8cfaf7ec. `pcraft gate` took exactly one image, so gating a turnaround was N
# processes -- and each process built the verifier dict fresh, while every verifier caches its
# scorer on the INSTANCE. N images was therefore N full loads of clip-flant5-xxl plus SigLIP2
# plus the Tier-2 localizer, for a library that was already shaped for the batch:
# `harness.evaluate(dag, image_path, verifiers, thresholds, *, generator_family)` takes an
# ALREADY-CONSTRUCTED verifier dict and a per-call image_path. The CLI was the only thing that
# was not, so the loop lives here and no new library primitive is needed for it.
#
# Three things this must not do, and the code below is arranged around them:
#
#   (1) a single `pcraft gate IMAGE` invocation is byte-identical -- same flags, same --json
#       transcript OBJECT (not an array), same 0/1/2/3/4 exit codes, same order of operations
#       (preflight before the store is even loaded). Batch mode is entered only when --batch
#       is given or more than one IMAGE is named, and the single path below is the original
#       body, unmoved;
#   (2) the four-way exit contract is not collapsed. The batch gets its OWN stated aggregation
#       rule (see the command's --help and `_batch_error`), and 4 keeps meaning could-not-run
#       for the batch AS A WHOLE -- never "one image could not run" merged onto 2;
#   (3) `preflight_image`'s refusal stays PER IMAGE. One unreadable file is listed by name and
#       the other N-1 results stand. Only preflight is caught per image: a verifier-discipline
#       refusal from inside evaluate() (GATE_SAME_FAMILY, GATE_CLIPSCORE_BANNED) is an andon
#       halt for the whole run and is deliberately left to propagate.


class _GateRow(NamedTuple):
    """One image's outcome: the transcript it produced, or the refusal that stopped it.

    ``error`` is the per-image exit-contract answer (``error_from_transcript``), or the
    preflight refusal when the file could not be read at all. ``None`` means that image passed.
    """

    path: Path
    transcript: Any | None
    error: PromptCraftError | None


_COULD_NOT_RUN_CODES = frozenset({"GATE_UNAVAILABLE", "IO_GATE_INPUT"})
_UNCONFIRMED_CODES = frozenset({"PARTIAL_UNCONFIRMED", "PARTIAL_TIER_CENSUS"})


def _gate_targets(images: list[Path], batch: Path | None, pattern: str) -> list[Path]:
    """Every image this invocation gates, in a deterministic order, or a refusal.

    Explicit IMAGE arguments come first in the order they were typed, then the directory's
    matches sorted by name, deduplicated by absolute path so naming a file twice does not
    gate it twice or count it twice in the summary.

    An EMPTY batch is a refusal, not a pass. A glob that matched nothing and a directory of
    images that all passed are the same exit 0 to a CI job, and only one of them means the
    renders were checked -- so a batch with nothing in it says so and exits 1.
    """
    targets = list(images)
    if batch is not None:
        if not batch.is_dir():
            raise PromptCraftError(
                "INPUT_GATE_BATCH",
                f"--batch {str(batch)!r} is not a directory",
                hint="Pass --batch at a folder of rendered images, or name the images as "
                "IMAGE arguments instead.",
            )
        found = sorted(p for p in batch.glob(pattern) if p.is_file())
        if not found and not targets:
            raise PromptCraftError(
                "INPUT_GATE_BATCH",
                f"no files matching {pattern!r} in {batch}",
                hint="A batch that gated nothing is not a batch that passed, so this "
                "refuses rather than exiting 0. Check --glob, or point --batch at the "
                "directory the renders actually landed in.",
            )
        targets += found
    if not targets:
        raise PromptCraftError(
            "INPUT_GATE_TARGET",
            "gate needs at least one IMAGE argument, or --batch DIR",
            hint="Pass one image to gate it, several to gate them in one run, or --batch "
            "at a directory of renders.",
        )
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in targets:
        key = os.path.normcase(str(Path(path).resolve()))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def _batch_summary(rows: list[_GateRow]) -> list[str]:
    """The one line a reader looks at after N transcripts, plus the unreadable files.

    The counts are the four outcomes the exit contract distinguishes, in the same order the
    exit-code table lists them, so the summary and the exit code cannot be read as saying
    different things. The unreadable images get their own row rather than a parenthetical:
    they are the half of the run that produced no verdict at all, and burying them beside a
    count is how "one file was missing" becomes invisible in a green log.
    """
    passed = [r for r in rows if r.error is None]
    failed = [r for r in rows if r.error is not None and r.error.code == "GATE_FAIL"]
    unconfirmed = [r for r in rows if r.error is not None and r.error.code in _UNCONFIRMED_CODES]
    unrun = [r for r in rows if r.error is not None and r.error.code in _COULD_NOT_RUN_CODES]
    lines = [
        f"{len(rows)} images: {len(passed)} passed, {len(failed)} failed, "
        f"{len(unconfirmed)} unconfirmed, {len(unrun)} could not run"
    ]
    if unrun:
        lines.append("could not run: " + id_list(str(r.path) for r in unrun))
    return lines


def _batch_error(rows: list[_GateRow]) -> PromptCraftError | None:
    """The batch's aggregate exit contract. ``None`` means every image passed (exit 0).

    THE RULE, stated once here and quoted in the command's --help:

      * a contract that declares no required atom refuses the whole run (exit 1) -- it is the
        same contract for every image, so no image can change the answer;
      * could-not-run on ANY image makes the whole run exit 4 only if NOTHING scored;
      * otherwise the worst SCORED outcome wins -- any failed required atom is 2, else any
        unconfirmed roll-up is 3, else 0 -- and the images nobody could read are listed
        rather than folded onto that number.

    The CODES are the single-image ones, deliberately: STABILITY.md tells callers to parse the
    code, and "a required atom failed" means the same thing whether one image or twenty were
    graded. Only the MESSAGE is batch-shaped, naming how many and which.
    """
    unusable = next(
        (r.error for r in rows if r.error is not None and r.error.code == "CONTRACT_NO_REQUIRED_ATOM"),
        None,
    )
    if unusable is not None:
        return unusable
    scored = [r for r in rows if r.transcript is not None and r.transcript.scored_required()]
    if not scored:
        unrun = [r for r in rows if r.error is not None and r.error.code in _COULD_NOT_RUN_CODES]
        return PromptCraftError(
            "GATE_UNAVAILABLE",
            f"no image produced a score on any required atom "
            f"({len(rows)} image(s), {len(unrun)} of them could not be read or scored)",
            hint="Nothing was graded, so this batch is could-not-run rather than a failure. "
            "Install the [image] extra (pip install 'prompt-crafter[image]', or from a "
            "checkout pip install -e '.[image]') so a verifier can score, and check that "
            "the images listed above are readable.",
        )
    failed = [r for r in rows if r.error is not None and r.error.code == "GATE_FAIL"]
    if failed:
        return PromptCraftError(
            "GATE_FAIL",
            f"{len(failed)} of {len(rows)} image(s) failed a required atom: "
            + id_list(str(r.path) for r in failed),
            hint="Each image's own transcript is printed above, with the atom, its score and "
            "the band that graded it. Images that could not be read are counted separately "
            "and never merged onto this code.",
        )
    unconfirmed = [r for r in rows if r.error is not None and r.error.code in _UNCONFIRMED_CODES]
    if unconfirmed:
        return PromptCraftError(
            "PARTIAL_UNCONFIRMED",
            f"{len(unconfirmed)} of {len(rows)} image(s) are unconfirmed after a real score: "
            + id_list(str(r.path) for r in unconfirmed),
            hint="This is the human band, not a pass. No image failed outright, so the batch "
            "takes the worst SCORED outcome, which is this one.",
        )
    return None


def _batch_documents(rows: list[_GateRow]) -> list[dict]:
    """The ``--json`` array: one row per image, always keyed by the image it graded.

    ``image_path`` is F-8cfaf7ec's additive field on ``GateTranscript`` and lands in the
    core-gate-loop domain. This layer fills it in when the transcript does not carry it (or
    carries the empty default), because the CLI is the thing that CHOSE the path it handed to
    ``evaluate`` -- so a batch document says which pixels each verdict is about both before
    and after that field exists, and never disagrees with it once it does.

    An image that could not be read still gets a row. Dropping it would leave a caller
    counting N-1 rows for N arguments with nothing saying which one went missing -- exactly
    the ambiguity AssetRecord.image_path was added to end. Those rows carry ``error`` and no
    verdicts, which is what actually happened.
    """
    docs: list[dict] = []
    for row in rows:
        if row.transcript is not None:
            doc = json.loads(row.transcript.model_dump_json())
            if not doc.get("image_path"):
                doc["image_path"] = str(row.path)
        elif row.error is not None:
            doc = {
                "image_path": str(row.path),
                "error": {"code": row.error.code, "message": row.error.message},
            }
        else:
            # Not constructible by the loop that fills `rows` -- an image either produced a
            # transcript or produced the refusal that stopped it. The row is emitted anyway
            # rather than dropped: "one row per image" is the property a caller counts on, and
            # a silently short array is the exact ambiguity this document exists to remove.
            doc = {"image_path": str(row.path)}
        docs.append(doc)
    return docs


@app.command()
def gate(
    images: list[Path] = typer.Argument(None, metavar="[IMAGE]...", help="rendered image(s) to gate; name several to gate them in one run"),
    batch: Path | None = typer.Option(None, "--batch", help="also gate every file matching --glob in this directory"),
    glob: str = typer.Option(BATCH_GLOB_DEFAULT, "--glob", help="which files --batch picks up"),
    contract: str = typer.Option("char:ashen-reaver", help="contract id whose atoms the gate blocks on"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    generator_family: str = typer.Option(
        None,
        help="override the generator family the same-family gate guard checks against "
        "(defaults to the registered image domain's own generator.family)",
    ),
    as_json: bool = typer.Option(False, "--json", help="emit GateTranscript as JSON on stdout (an ARRAY of them for a batch)"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Run the contract gate on image(s) you already have. SKIPPED atoms are not a pass.

    Exit codes:
      0  every required atom passed.
      1  the contract is unusable (no required atom, or a bad --contracts-dir).
      2  a required atom failed.
      3  a required atom was scored but the roll-up is UNCERTAIN.
      4  could not run: missing or unreadable image, or no verifier could score.

    4 is never folded into 2 -- could-not-check is not checked-clean, and a CI
    branch that merges them reads "the gate ran and failed" for a gate that
    never ran.

    One IMAGE and no --batch is the single-image command it has always been: one
    transcript, one --json object, those exit codes. Naming several images, or
    passing --batch DIR, builds the verifiers ONCE and grades every image against
    them, printing a transcript per image, then a summary line; --json then emits
    an ARRAY of transcripts, each keyed by the image_path it graded.

    A batch aggregates the same codes by this rule: could-not-run on ANY image
    makes the whole run exit 4 only if NOTHING scored. Otherwise the worst SCORED
    outcome wins -- a failed required atom anywhere is 2, else an unconfirmed
    roll-up anywhere is 3, else 0 -- and the images that could not be read are
    listed by name instead of being folded onto that code. An empty batch is
    exit 1, never 0: gating nothing is not gating cleanly.
    """
    import pcraft.domains.image  # noqa: F401  (registers the plugin)

    from ..core.contract.compile_questions import compile_questions
    from ..core.gate import harness
    from ..core.plugin import get
    from ..sample import load_workspace

    try:
        from ..core.gate.exit_contract import error_from_transcript
        from ..core.gate.preflight import preflight_image

        targets = _gate_targets(list(images or []), batch, glob)
        batched = batch is not None or len(targets) > 1
        if not batched:
            preflight_image(targets[0])
        _store, resolved, table, _c = load_workspace(
            contracts_dirs=contracts_dir or None, thresholds=thresholds, contract_id=contract
        )
        dag = compile_questions(resolved)
        plugin = get("image")
        # ONCE, outside the loop. This is the whole performance half of F-8cfaf7ec: the
        # verifiers cache their scorers on the instance, so constructing the dict per image
        # is a full model load per image.
        verifiers = plugin.verifiers()
        family = generator_family or plugin.generator().family
        if not batched:
            transcript = harness.evaluate(dag, str(targets[0]), verifiers, table, generator_family=family)
            _say(format_transcript(transcript, dag=dag), as_json=as_json)
            if as_json:
                _emit_model(transcript)
            err = error_from_transcript(transcript)
            if err is not None:
                _emit(err, debug)
            return
        rows: list[_GateRow] = []
        for path in targets:
            try:
                preflight_image(path)
            except PromptCraftError as unreadable:
                # Per image, on purpose (must-not-break 3): one file nobody can open does not
                # void the other N-1 verdicts. Only THIS refusal is caught here -- a verifier
                # discipline failure inside evaluate() below is an andon halt and propagates.
                rows.append(_GateRow(path=path, transcript=None, error=unreadable))
                continue
            transcript = harness.evaluate(dag, str(path), verifiers, table, generator_family=family)
            rows.append(
                _GateRow(path=path, transcript=transcript, error=error_from_transcript(transcript))
            )
        for row in rows:
            _say(f"image: {row.path}", as_json=as_json)
            if row.transcript is not None:
                _say(format_transcript(row.transcript, dag=dag), as_json=as_json)
            elif row.error is not None:
                _say(f"  {row.error.code}: {row.error.message}", as_json=as_json)
            _say("", as_json=as_json)
        for line in _batch_summary(rows):
            _say(line, as_json=as_json)
        if as_json:
            _emit_json(_batch_documents(rows))
        err = _batch_error(rows)
        if err is not None:
            _emit(err, debug)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def bind(
    contract: str = typer.Option("char:ashen-reaver", help="contract id to synthesize, gate and bind"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    mock: bool = typer.Option(True, help="use deterministic stubs (GPU-free); the default scaffold path"),
    records_dir: str = typer.Option("records", help="directory the receipt is written to; the path printed at the end is inside it"),
    as_json: bool = typer.Option(False, "--json", help="emit OrchestrationResult as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Run the full synth->generate->gate->retry->bind loop and report the decision.

    Exit codes:
      0  bound.
      1  the contract is unusable.
      2  a required atom failed.
      3  a required atom was scored but the roll-up is UNCERTAIN.
      4  the loop could not run and nothing was scored.

    2 means the gate ran and refused; 4 means there is no verdict to read.
    The last line names the receipt it wrote, inside --records-dir; run
    `pcraft replay` on exactly that path to re-check it.
    """
    from ..sample import run_live_loop, run_mock_loop

    try:
        if mock:
            result = run_mock_loop(
                records_dir=records_dir,
                contract_id=contract,
                contracts_dirs=contracts_dir or None,
                thresholds=thresholds,
            )
        else:
            result = run_live_loop(
                records_dir=records_dir,
                contract_id=contract,
                contracts_dirs=contracts_dir or None,
                thresholds=thresholds,
                on_attempt=_announce_attempt,
            )
        _print_result(result, records_dir=records_dir, as_json=as_json)
        # Replaces a blanket `raise typer.Exit(code=3)`: every non-bound decision reported 3
        # regardless of cause, so "could not run at all" and "ran, unconfirmed" were the same
        # number to a caller -- the merge the four-way contract exists to prevent.
        _exit_from_result(result, debug)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command(name="list")
def list_contracts(
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    as_json: bool = typer.Option(False, "--json", help="emit StoreListing as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """List contract ids in the store."""
    from ..sample import load_store

    try:
        store = load_store(contracts_dir or None)
        listing = StoreListing(
            contracts=[
                ListedContract(id=cid, source=str(store.source_path(cid))) for cid in store.ids()
            ]
        )
        for item in listing.contracts:
            _say(f"{item.id}  {item.source}", as_json=as_json)
        if as_json:
            _emit_model(listing)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def validate(
    contract: str = typer.Option("char:ashen-reaver", help="contract id to lint and resolve"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    as_json: bool = typer.Option(False, "--json", help="emit ValidateReport as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Resolve a contract and compile its question DAG. No generate, no gate."""
    from ..core.contract.compile_questions import compile_questions
    from ..sample import load_workspace

    try:
        _store, resolved, _t, _c = load_workspace(
            contracts_dirs=contracts_dir or None, contract_id=contract
        )
        dag = compile_questions(resolved)
        report = ValidateReport(
            id=resolved.id,
            lineage=list(resolved.lineage),
            required=[a.id for a in resolved.required_atoms()],
            must_not=[m.id for m in resolved.must_not],
            questions=len(dag.questions),
        )
        _say(f"ok  {resolved.id}", as_json=as_json)
        _say(f"lineage: {' -> '.join(resolved.lineage)}", as_json=as_json)
        # Joined, not repr'd (F-2d223d8e): the line above already renders its list FOR a
        # reader, and these two dumped brackets and quotes one row below it. Both values reach
        # a machine caller as real arrays in the `--json` ValidateReport, so the repr on the
        # human channel bought nothing and cost 18 characters of quoting on the wider row.
        _say(f"required: {', '.join(report.required)}", as_json=as_json)
        _say(f"must_not: {', '.join(report.must_not)}", as_json=as_json)
        _say(f"questions: {len(dag.questions)}", as_json=as_json)
        if as_json:
            _emit_model(report)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


# ------------------------------------------------------------------ new: the scaffold door
#
# F-62e7d1f0 (the CLI half of F-37f8764e / F-a9d86551). The product's front door for its own
# core artifact was a blank file: `pcraft schema` emits the JSON Schema, which is a validator
# and not a starting point, and `pcraft validate` refuses a bad contract, which only helps
# once one exists. This verb is thin on purpose -- it prompts for NOTHING, writes where it is
# told, and then reports what the LOADER said about the file, not what the scaffold intended.
#
# The four rules it owes the scaffold spec, each enforced below before the library is reached:
#   (1) never into the packaged sprite tree -- the shipped examples stay untouched;
#   (2) never over an existing file -- the same O_EXCL discipline `asset_record.persist` uses,
#       for the identical reason: a hand-authored contract is not a scaffold's to replace;
#   (3) a seeded atom is visibly a STUB, said OUT LOUD on stdout rather than buried in a
#       `_note` inside the file, or the scaffold manufactures a gate nobody authored;
#   (4) what is emitted loads back through the SAME _read_contract/resolve() path a
#       hand-written contract does -- never a shortcut around it.

CONTRACT_LEVELS = ("character", "faction")
"""The two levels the contract schema declares. One tuple: the refusal, the help string and
the directory name are all derived from it."""

_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def _is_under(path: Path | str, root: Path | str) -> bool:
    """Whether ``path`` sits inside ``root``. Never raises; unrelated drives answer False.

    ``resolve()`` rather than a string comparison, so a symlinked or relative ``--contracts-dir``
    that lands inside the packaged tree is still recognised as being inside it -- the check
    exists to protect the shipped examples, and a check a relative path walks past protects
    nothing. Neither side needs to exist yet: the scaffold's target is a file about to be
    written, and ``resolve()`` is non-strict.
    """
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _scaffold_target(level: str, contract_id: str, *, contracts_dir: Path, out: Path | None) -> Path:
    """Where ``pcraft new`` will write, and the refusals that are decided from the path alone.

    ``--out`` wins when given; otherwise the file lands at
    ``<contracts-dir>/<level>s/<slug>.contract.json``, the layout the shipped example already
    uses (``factions/`` beside ``characters/``). The slug is the id with everything that is not
    filename-safe collapsed to a hyphen -- ids carry a colon (``char:rook``), which is a legal
    path character on POSIX and an alternate-data-stream separator on NTFS.

    The store indexes by the contract's ``id`` FIELD, not by its filename, so the slug is a
    convenience for the human browsing the tree and never load-bearing.
    """
    from ..domains.image.subdomains.sprite import CONTRACTS_DIR as PACKAGED

    if out is not None:
        target = out
    else:
        slug = _SLUG.sub("-", contract_id.split(":", 1)[-1]).strip("-") or "contract"
        target = contracts_dir / f"{level}s" / f"{slug}.contract.json"
    if _is_under(target, PACKAGED):
        raise PromptCraftError(
            "INPUT_SCAFFOLD_TARGET",
            f"{target} is inside the packaged sprite example ({PACKAGED})",
            hint="Scaffold into your own tree instead: pass --contracts-dir at the directory "
            "your contracts live in. The shipped examples are the reference the docs quote "
            "and stay as they were installed.",
        )
    if target.exists():
        # Decided here as well as at the open() below. The O_EXCL claim is the authority (it
        # cannot be raced); this one exists so the refusal arrives before the scaffold runs,
        # naming the file rather than reporting a failed write at the end of the work.
        raise PromptCraftError(
            "IO_CONTRACT_EXISTS",
            f"a contract already exists at {target}; pcraft does not overwrite one",
            hint="Move or delete it deliberately, pass --out at a different path, or edit the "
            "file you already have. A scaffold that replaced a hand-written contract would "
            "destroy authored canon to save a copy step.",
        )
    return target


def _refuse_reference_sheet(sheet: Path) -> None:
    """``--reference-sheet`` names a capability that is a different VERB, and says where it is.

    STATED JUDGMENT (wave-13 fold). The finding's approved shape lists this flag, and the
    capability exists and is good: ``pcraft.domains.image.scaffold.scaffold_from_reference_sheet
    (sheet, *, contracts_dir, max_colours=4)`` reads a reference-sheet JSON (faction, character,
    named traits, plates), measures dominant hexes off a ``kind=palette`` plate, and emits an
    authorable faction+character PAIR.

    It cannot be driven by this verb without lying. That entry point derives BOTH ids from the
    sheet, writes TWO files, and chooses their names itself -- so ``pcraft new character
    char:rook --reference-sheet s.json --out x.json`` would have to silently ignore LEVEL, ID
    and --out, write two files while reporting one, and return a ScaffoldReport that can only
    describe half of what happened. Silently ignoring arguments the operator typed is the defect
    class this package exists to catch, so wiring it here is refused and the flag says where the
    capability actually lives. It wants its own verb (a `pcraft new --from-sheet` or a separate
    command), which is a slice, not a line -- filed for the coordinator rather than improvised.

    The refusal is INPUT_ (exit 1) and fires before anything is written.
    """
    raise PromptCraftError(
        "INPUT_SCAFFOLD_REFERENCE_SHEET",
        f"--reference-sheet {str(sheet)!r} is not wired into `pcraft new` yet",
        hint="The sheet-driven scaffold emits a faction+character PAIR and names both files "
        "itself, so it cannot honour this command's LEVEL, ID and --out arguments and needs a "
        "verb of its own. Call pcraft.domains.image.scaffold.scaffold_from_reference_sheet "
        "(sheet, contracts_dir=...) from Python meanwhile. Without this flag, `pcraft new` "
        "writes the single starter contract it describes.",
    )


def _write_new_contract(target: Path, text: str) -> Path:
    """Claim the path with O_EXCL and write it. A collision is an ANSWER, never a deletion."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as err:
        raise PromptCraftError(
            "IO_CONTRACT_EXISTS",
            f"a contract already exists at {target}; pcraft does not overwrite one",
            hint="Move or delete it deliberately, or pass --out at a different path.",
            cause=err,
        ) from err
    except OSError as err:
        raise PromptCraftError(
            "IO_CONTRACT_WRITE",
            f"could not write contract {target}: {err.strerror or err}",
            hint="Check that the directory is writable and has space, or pass --out at a "
            "path you can write to.",
            cause=err,
        ) from err
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")
    return target


def _stub_atoms(resolved) -> list[str]:
    """Atoms that are not yet something the gate may block on, read off the LOADED contract.

    Two signals, both facts about the file as the loader read it back rather than a convention
    the scaffold and this line would have to keep agreeing about:

      * a claim still carrying a TODO marker -- the scaffold never invents a claim the author
        did not write, so the placeholder is the visible half of that rule;
      * a severity that is not ``required`` -- ``required_atoms()`` is exactly the set the gate
        is allowed to block on, so anything outside it gates nothing yet however good its
        claim is.

    Reported, never repaired. Raising a severity is an authoring decision with evidence behind
    it (see ``MustNot.severity``'s own note); a CLI that quietly promoted these would be
    manufacturing the gate this whole verb exists to avoid manufacturing.
    """
    from ..core.contract.schema import Severity

    out: list[str] = []
    for atom in [*resolved.must_have, *resolved.must_not]:
        claim = getattr(atom, "claim", "") or ""
        if "TODO" in claim.upper() or getattr(atom, "severity", None) != Severity.required:
            out.append(atom.id)
    return out


@app.command()
def new(
    level: str = typer.Argument(..., metavar="LEVEL", help="character or faction -- the two levels the contract schema declares"),
    contract_id: str = typer.Argument(..., metavar="ID", help="the contract id to author, e.g. char:rook or faction:rooks"),
    contracts_dir: Path = typer.Option(Path("contracts"), "--contracts-dir", help="the tree to scaffold INTO and resolve --extends against; never the packaged sprite example"),
    extends: str = typer.Option(None, "--extends", help="the faction id a character contract inherits from"),
    reference_sheet: Path = typer.Option(None, "--reference-sheet", help="NOT WIRED HERE: the sheet-driven scaffold emits a faction+character PAIR and names both files itself, so it needs its own verb. Passing this is refused, and the refusal names the entry point"),
    out: Path = typer.Option(None, "--out", help="write exactly here, instead of the default path <id>.contract.json under the contracts dir's <level>s/ folder"),
    as_json: bool = typer.Option(False, "--json", help="emit ScaffoldReport as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Scaffold a new character or faction contract, then report what the loader made of it.

    Writes a STUB, never a gate. The starter contract declares no required atom --
    it carries the level, the id and the inheritance, and the claims are yours to
    write -- so it blocks on nothing until an author fills it in and raises a
    severity. The last lines printed here say exactly that, naming the file.
    Nothing is prompted for: this is flags in, one file out.

    The file lands under --contracts-dir (default ./contracts), never inside the
    packaged sprite example, and an existing file is never overwritten. What was
    written is then read back through the SAME store a hand-written contract goes
    through, and that loader's verdict -- lineage, required, must_not -- is what
    is printed. A scaffold that could not survive its own loader is not a start.

    Exit codes:
      0  the contract was written and it resolves.
      1  the level, the id, or the target directory is unusable.
      2  a contract already exists at that path, or the file could not be written.

    2 rather than 1 for an existing file: the input was fine and the filesystem
    answered, which is the same reading IO_RECORD_EXISTS has for a receipt.
    """
    try:
        if level not in CONTRACT_LEVELS:
            raise PromptCraftError(
                "INPUT_CONTRACT_LEVEL",
                f"level {level!r} is not one of: {', '.join(CONTRACT_LEVELS)}",
                hint="A faction is the base class and a character extends one. Those are the "
                "two levels the schema declares; pass --extends when scaffolding a character.",
            )
        if reference_sheet is not None:
            _refuse_reference_sheet(reference_sheet)
        target = _scaffold_target(level, contract_id, contracts_dir=contracts_dir, out=out)

        from ..core.contract.scaffold import scaffold_contract, scaffold_json
        from ..sample import load_store

        # The store is what turns `--extends` from a string into a CHECKED reference: with it,
        # scaffold_contract refuses a base that is not in the tree and a starter atom colliding
        # with an inherited id, while the author can still pick another. Loaded only when
        # --extends was given, because a first scaffold into an empty tree is the normal case
        # and INPUT_EMPTY_STORE would be a refusal about nothing.
        base_store = load_store([contracts_dir]) if extends is not None else None
        contract = scaffold_contract(level, contract_id, extends=extends, store=base_store)
        # `scaffold_json` is the CANONICAL serializer and the on-disk text has exactly one
        # owner. Spelling the dump here instead would be a second implementation of the file
        # format, free to drift from the one the library round-trips its own output through.
        _write_new_contract(target, scaffold_json(contract))

        # Read back through the real store. Roots stay minimal: the contracts dir is enough
        # when the file landed inside it, and indexing the same file under two roots is
        # INPUT_DUPLICATE_CONTRACT_ID by the store's own rule.
        roots = [contracts_dir] if contracts_dir.is_dir() else []
        if not any(_is_under(target, root) for root in roots):
            roots.append(target.parent)
        resolved = load_store(roots).resolve(contract_id)
        stubs = _stub_atoms(resolved)
        report = ScaffoldReport(
            id=resolved.id,
            level=resolved.level,
            path=str(target),
            lineage=list(resolved.lineage),
            required=[a.id for a in resolved.required_atoms()],
            must_not=[m.id for m in resolved.must_not],
            stub_atoms=stubs,
        )
        _say(f"wrote {report.level} {report.id} -> {report.path}", as_json=as_json)
        _say(f"lineage: {' -> '.join(report.lineage)}", as_json=as_json)
        _say(f"required: {', '.join(report.required) or 'none'}", as_json=as_json)
        _say(f"must_not: {', '.join(report.must_not) or 'none'}", as_json=as_json)
        # Said on the command's own channel, not only in the document: the whole failure this
        # guards against is an operator who reads "wrote ... -> path", runs `pcraft gate`, and
        # is told the contract passed when what actually happened is that it asserts nothing.
        #
        # Both shapes get a STUB line, because both are the same fact to the reader. MEASURED
        # against the real primitive: `scaffold_contract(level, id)` seeds NO atoms at all --
        # the skeleton is level, id, extends and identity_ref, and the claims are the author's
        # to write -- so the empty case is the ordinary one and printing nothing for it would
        # leave the loudest run silent. A caller that seeds starter atoms (the domain layers do)
        # gets the count and the ids instead.
        _say("", as_json=as_json)
        if stubs:
            _say(
                f"STUB: {len(stubs)} atom(s) need a real claim before this binds; "
                f"see {report.path}",
                as_json=as_json,
            )
            for line in _wrap(id_list(stubs), _term_width(), "  ", "  "):
                _say(line, as_json=as_json)
        else:
            for line in _wrap(
                f"STUB: this contract declares no atoms yet, so it asserts nothing. Write the "
                f"must_have / must_not claims in {report.path} before it binds.",
                _term_width(),
                "",
                "  ",
            ):
                _say(line, as_json=as_json)
        if not report.required:
            for line in _wrap(
                "No atom is severity=required yet, so the gate has nothing it may block on: "
                "`pcraft gate` refuses this contract with CONTRACT_NO_REQUIRED_ATOM until an "
                "atom is raised. That refusal is the scaffold working, not a defect.",
                _term_width(),
                "  ",
                "  ",
            ):
                _say(line, as_json=as_json)
        if as_json:
            _emit_model(report, extends=extends)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def demo(
    records_dir: str = typer.Option("records", help="directory the receipt is written to; the path printed at the end is inside it"),
    as_json: bool = typer.Option(False, "--json", help="emit OrchestrationResult as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """End-to-end sample run on the generic example contract (GPU-free)."""
    from ..sample import load_sprite_example, run_mock_loop

    try:
        _s, resolved, _t, _c = load_sprite_example()
        _say(f"contract: {resolved.id}  lineage: {' -> '.join(resolved.lineage)}", as_json=as_json)
        # The first two lines a new user sees from the command the README points at, so they
        # are the last two that should read like a repl transcript (F-2d223d8e).
        _say(f"required atoms: {', '.join(a.id for a in resolved.required_atoms())}", as_json=as_json)
        _say(f"must_not: {', '.join(m.id for m in resolved.must_not)}", as_json=as_json)
        _say("", as_json=as_json)
        result = run_mock_loop(records_dir=records_dir)
        _print_result(result, records_dir=records_dir, as_json=as_json)
        _exit_from_result(result, debug)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def replay(
    record: Path = typer.Argument(..., help="receipt JSON to replay -- the path `pcraft bind` printed"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON to check the receipt against; default: shipped sprite calibration"),
    skip_threshold_check: bool = typer.Option(False, "--skip-threshold-check", help="replay without comparing the threshold table (states that you have no table to compare, rather than hiding that you did not look)"),
    as_json: bool = typer.Option(False, "--json", help="emit AssetRecord as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Replay a receipt: reconstruct its question DAG from the contract and assert no drift.

    Exit codes:
      0  the receipt reproduces.
      1  it was written by a NEWER prompt-craft than this one -- upgrade, do
         not re-bind.
      2  it drifted, is unreadable, or is not a receipt.

    Nothing is generated and nothing is scored here, so exit 4 (could-not-run)
    cannot occur. RECORD is the path `pcraft bind` printed.
    """
    from ..core.gate.thresholds import load_thresholds
    from ..core.receipt.asset_record import load
    from ..core.receipt.asset_record import replay as do_replay
    from ..domains.image.subdomains.sprite import THRESHOLDS_PATH
    from ..sample import load_store

    try:
        rec = load(record)
        store = load_store(contracts_dir or None)
        resolved = store.resolve(rec.contract_id)
        # The receipt has always stamped the table version; nothing compared it until v1.0.0, so a
        # replay under a retuned table re-decided in silence. Opting out is a flag you have to type.
        #
        # The TABLE now goes across too, not just its version string (F-70ea9458). A version
        # comparison only catches a retune whose author remembered to bump the label; band
        # VALUES edited under an unchanged version are the case that walked straight through,
        # which is precisely the drift with no other signal. The loaded table was already in
        # hand here and only `.version` was being read off it.
        table = None if skip_threshold_check else load_thresholds(thresholds or THRESHOLDS_PATH)
        table_version = table.version if table is not None else None
        do_replay(rec, resolved, thresholds_version=table_version, thresholds=table)
        _say(
            f"replay OK: {rec.record_id} reproduces from {rec.contract_id} ({rec.contract_hash[:19]}...)"
            + (f"  thresholds={table_version}" if table_version else "  thresholds=NOT CHECKED"),
            as_json=as_json,
        )
        if as_json:
            _emit_model(rec)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


# --------------------------------------------------------------- resolve: the disposition door
#
# F-2b04f0b8's CLI half, over `core.receipt.disposition.record_disposition`. The loop builds a
# genuine contrastive checkpoint, persists it inside the receipt, prints it and returns
# decision='escalated' -- and then the trail stopped: there was no verb and no format for what
# the Director decided. The `escalation-ticket` compensator already declared its owner as
# "pipeline (Director resolves)" and its post-rollback state as "ticket closed with a
# resolution note", and neither the ticket nor the note existed.
#
# What this door does NOT do, and must never grow into:
#   * it does not edit the receipt. Not one field. The entry goes to a `dispositions/`
#     SUBDIRECTORY of the records dir, which is load-bearing rather than tidy: `receipt_paths`
#     walks *.json non-recursively, so `regrade_dir`, the index and any caller globbing the
#     records dir see exactly what they saw before, and an entry can never be handed to
#     `load()` as a malformed receipt;
#   * it does not turn a refusal into a pass. Exit 0 here means RECORDED. `bind` and `gate`
#     still refuse the asset afterwards, because a human's judgment is provenance, not a
#     retroactive gate result a scripted caller can no longer see;
#   * it does not accept anything without a reason. --note is required by the parser, because
#     a resolution with no reasoning is an auto-accept wearing a verdict (UNCERTAINTY_GATED_
#     HUMANS: the record is EVIDENCE a human decided).

VERDICT_RESOLUTIONS: dict[str, str] = {"approve": "accepted", "reject": "rejected"}
"""The CLI's verdict words, and the library ``RESOLUTIONS`` value each one records.

Two vocabularies on purpose, mapped in ONE place. ``approve``/``reject`` are what an operator
types -- imperative, and what the finding's own shape names -- while ``accepted``/``rejected``
are what goes on disk and what a downstream reader filters on. The library's third value,
``deferred``, is deliberately NOT reachable from here yet: "I looked and I am not deciding"
needs a surface of its own (it is a different act from approving, and pretending it is a
--verdict value would make an operator choose it by accident), so it stays library-only until
that surface is designed. The mapping is a dict rather than two branches so the CLI cannot
grow a verdict the library has no value for."""


@app.command()
def resolve(
    record: Path = typer.Argument(..., metavar="RECEIPT", help="the escalated receipt to record a decision against -- the path `pcraft bind` printed"),
    verdict: str = typer.Option(..., "--verdict", help="approve or reject -- what the human decided about this asset"),
    note: str = typer.Option(..., "--note", help="why. Required: a resolution with no reasoning is an auto-accept wearing a verdict"),
    by: str = typer.Option("director", "--by", help="who decided; recorded in the resolution as its owner"),
    as_json: bool = typer.Option(False, "--json", help="emit ResolutionReport as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Record a human's decision about an ESCALATED receipt, beside it on disk.

    The receipt is never touched. A receipt already on disk is never replaced, so
    the decision becomes a NEW entry under `<records-dir>/dispositions/` that
    references its record_id -- the same rule `pcraft replay`'s drift refusal
    states as "Do not edit the receipt". The subdirectory is deliberate: every
    reader that globs the records dir for receipts keeps seeing exactly what it
    saw before, so a resolution can never be read back as a malformed receipt.

    Exit 0 means the decision was RECORDED. It does not mean the asset passes:
    the receipt still reads escalated, and `pcraft gate` and `pcraft bind` still
    refuse it, because making a human's judgment retroactively invisible to a
    scripted caller is the one thing this record must not do.

    --verdict approve records the library's `accepted`, reject records `rejected`.
    Its third value, `deferred` ("I looked and I am not deciding yet"), is
    library-only for now: it is a different act and wants a surface of its own
    rather than a third word in this flag.

    Exit codes:
      0  the resolution was written.
      1  the verdict is not approve/reject, or that receipt is not escalated.
      2  the receipt is unreadable or is not a receipt, or the resolution could
         not be written.

    A receipt that already reads bound has nothing to resolve, and that is exit 1
    (fix the path you passed), never a silent success.
    """
    from ..core.receipt.asset_record import load
    from ..core.receipt.disposition import record_disposition

    try:
        if verdict not in VERDICT_RESOLUTIONS:
            raise PromptCraftError(
                "INPUT_RESOLVE_VERDICT",
                f"--verdict {verdict!r} is not one of: {', '.join(VERDICT_RESOLUTIONS)}",
                hint="approve records that a human looked and accepted this asset anyway; "
                "reject records that they looked and did not. The library also knows "
                "'deferred', which this flag does not offer yet -- not deciding is a "
                "different act from deciding and should not be one keystroke away.",
            )
        if not note.strip():
            raise PromptCraftError(
                "INPUT_RESOLVE_NOTE",
                "--note is empty; a resolution must say why",
                hint="Write the reasoning a later reader needs: which atom you looked at and "
                "what you saw. A blank note makes the record indistinguishable from an "
                "automatic accept, which is exactly what it exists to be distinguishable from.",
            )
        rec = load(record)
        if rec.decision != "escalated":
            raise PromptCraftError(
                "INPUT_RECEIPT_NOT_ESCALATED",
                f"receipt {rec.record_id} reads decision {rec.decision!r}, not 'escalated', "
                f"so there is no escalation to resolve",
                hint="Only an escalated receipt carries a checkpoint a human was asked to "
                "decide. Point this at the receipt whose run escalated -- `pcraft bind` "
                "prints the path it wrote at the end of every run.",
            )

        # `record_disposition` owns the entry, its dispositions/ subdirectory, the O_EXCL claim
        # on the exact path, and the `disposition-write` compensator gate it requires BEFORE
        # writing -- the same NAMED_COMPENSATORS discipline `orchestrate.run` applies to
        # records-write. The registry is left to default, which registers that action; nothing
        # here re-implements or re-states any of it. The refusals above are this layer's, and
        # they fire first so the message is shaped for someone at a terminal rather than for a
        # library caller: the library refuses the same non-escalated receipt as
        # INPUT_DISPOSITION_TARGET if it is ever reached another way.
        written = record_disposition(
            rec,
            Path(record).parent,
            resolution=VERDICT_RESOLUTIONS[verdict],
            resolved_by=by,
            note=note,
        )
        report = ResolutionReport(
            record_id=rec.record_id,
            receipt_path=str(record),
            decision=rec.decision,
            verdict=verdict,
            resolution=VERDICT_RESOLUTIONS[verdict],
            note=note,
            resolved_by=by,
            resolution_path=str(written),
        )
        _say(
            f"recorded {report.verdict.upper()} ({report.resolution}) by {report.resolved_by}",
            as_json=as_json,
        )
        _say(f"receipt: {report.receipt_path}", as_json=as_json)
        _say(f"  decision: {report.decision} (unchanged -- the receipt was not edited)", as_json=as_json)
        for line in _wrap(report.note, _term_width(), "  note: ", "        "):
            _say(line, as_json=as_json)
        _say("", as_json=as_json)
        # Last, alone on its own line, for the same reason `bind` ends with the receipt path:
        # a `tail -1` or a line-select yields exactly the path and nothing else.
        _say("resolution:", as_json=as_json)
        _say(f"  {report.resolution_path}", as_json=as_json)
        if as_json:
            _emit_model(report)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def regrade(
    table: Path = typer.Option(..., "--table", help="CANDIDATE threshold table to re-grade against -- the file `pcraft calibrate` emitted, not the one the receipts were decided under"),
    records_dir: Path | None = typer.Option(None, "--records-dir", help="directory of receipts to re-grade (every *.json directly under it)"),
    record: Path | None = typer.Option(None, "--record", help="a single receipt to re-grade, instead of --records-dir"),
    as_json: bool = typer.Option(False, "--json", help="emit the RegradeReport models as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Ask what a candidate threshold table WOULD have decided about receipts already bound.

    This is the question `pcraft replay` refuses: replay's job is to assert that a receipt
    still reproduces, so a retuned table is STATE_REPLAY_DRIFT there and must stay that
    way. Here the same difference is the ANSWER, reported per atom.

    Reports, never gates. Nothing is written, no receipt is re-stamped, and a verdict that
    moves is an answer rather than a refusal -- so this exits 0 whenever it could read its
    inputs, and atoms the gate never scored are carried and named rather than re-zoned.

    Exit codes:
      0  the re-grade ran; flips, if any, are in the report.
      1  the candidate table is unreadable or invalid, or neither/both of
         --records-dir and --record was given.
      2  a receipt is unreadable or is not a receipt.
    """
    try:
        # Both-or-neither is decided BEFORE the table is read, so the refusal names the
        # mistake the operator made rather than whatever the loader met first.
        if (records_dir is None) == (record is None):
            raise PromptCraftError(
                "INPUT_REGRADE_TARGET",
                "regrade needs exactly one of --records-dir or --record",
                hint="Pass --records-dir at a directory of receipts for the corpus "
                "question, or --record at one receipt for a single asset.",
            )
        from ..core.gate.regrade import regrade as regrade_record
        from ..core.gate.regrade import regrade_dir
        from ..core.gate.thresholds import load_thresholds
        from ..core.receipt.asset_record import load

        candidate = load_thresholds(table)
        if records_dir is not None:
            reports = regrade_dir(records_dir, candidate)
        elif record is not None:
            reports = [regrade_record(load(record), candidate)]
        else:  # unreachable: the both-or-neither refusal above already fired
            raise PromptCraftError(
                "INPUT_REGRADE_TARGET",
                "regrade needs exactly one of --records-dir or --record",
                hint="Pass --records-dir at a directory of receipts for the corpus "
                "question, or --record at one receipt for a single asset.",
            )
        for report in reports:
            _say(f"{report.record_id}: {report.summary()}", as_json=as_json)
        blocking = [r for r in reports if r.blocking_flips]
        total = sum(len(r.blocking_flips) for r in reports)
        _say(
            f"{len(reports)} receipt{'' if len(reports) == 1 else 's'}, "
            f"{len(blocking)} with blocking flips, {total} blocking flips total",
            as_json=as_json,
        )
        if as_json:
            _emit_json(
                {
                    "table": candidate.version,
                    "receipts": [json.loads(r.model_dump_json()) for r in reports],
                    "receipts_total": len(reports),
                    "with_blocking_flips": len(blocking),
                    "blocking_flips_total": total,
                }
            )
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def calibrate(
    manifest: Path = typer.Argument(..., help="labelled holdout manifest (JSONL: image, contract, atom, label in present|absent|borderline)"),
    out: Path = typer.Option(..., "--out", help="write the emitted sprite.cal.v2 table here -- a NEW file; the packaged calibration is refused"),
    scored_out: Path | None = typer.Option(None, "--scored-out", help="also write the scored companion (the manifest rows plus the score each verifier gave)"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="base table the emitted one is built from; default: shipped sprite calibration"),
    as_json: bool = typer.Option(False, "--json", help="emit CalibrationResult as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Fit threshold bands against a labelled holdout and EMIT a sprite.cal.v2 table.

    Emits, never adopts. The shipped table stays the default until a Director ratifies the
    swap, and every existing receipt keeps replaying under the table that decided it -- so
    the new numbers go to a new file under a new version name, and writing them over
    sprite.cal.v1 is refused. Adopt one explicitly with --thresholds when you mean to.

    A band the holdout did not measure is reported unmeasured and left OUT of the emitted
    table rather than defaulted: an invented number where a measurement is claimed is the
    exact defect this harness exists to end.

    The holdout and its images are DATA and stay outside the wheel -- MANIFEST is a path,
    and nothing here ships or writes a corpus.

    Exit codes:
      0  the holdout was scored and the table was emitted.
      1  the manifest is unusable, or the target refuses the write.
      2  the [image] extra is missing, or the holdout loader is unavailable.
    """
    try:
        # Inside the try, unlike `gate`'s: that command imports modules this package always
        # ships, while the calibration harness is an optional-extra-adjacent import whose
        # failure must arrive as a classified refusal rather than as the raw traceback this
        # CLI's docstring says --debug is the only route to.
        import pcraft.domains.image  # noqa: F401  (registers the plugin)

        from ..core.gate.thresholds import load_thresholds
        from ..core.plugin import get
        from ..domains.image.subdomains.sprite import calibrate as harness

        base = load_thresholds(thresholds) if thresholds is not None else None
        result = harness.calibrate_from_manifest(
            manifest,
            contracts_dirs=contracts_dir or None,
            verifiers=list(get("image").verifiers().values()),
            base_table=base,
        )
        table_path = harness.write_table(result.table, out)
        _say(f"holdout: {result.manifest}  rows: {result.rows}", as_json=as_json)
        for fit in result.bands:
            _say(
                f"  {fit.band_key}: {fit.high}/{fit.low}"
                if fit.fitted
                else f"  {fit.band_key}: UNMEASURED ({fit.reason})",
                as_json=as_json,
            )
        _say(f"emitted {result.table.version} -> {table_path}", as_json=as_json)
        _say("NOT adopted: pass --thresholds at this file to use it.", as_json=as_json)
        if scored_out is not None:
            _say(f"scored companion -> {harness.write_scored(result.scored, scored_out)}", as_json=as_json)
        if as_json:
            _emit_model(result)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def doctor(
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    as_json: bool = typer.Option(False, "--json", help="emit DoctorReport as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Check python, optional extras, and that the contract store loads. GPU-free."""
    try:
        report = _run_doctor(contracts_dir or None, thresholds)
        _say(f"pcraft {report.version}", as_json=as_json)
        if report.version_warning is not None:
            # Loud on purpose. The number on the line above is what `pcraft --version`
            # reports, and a user who does not know the dist-info is stale has no way to
            # tell that from here -- the whole reason this check moved out of the
            # maintainer-only `verify.py --installed` leg.
            #
            # Loud in bytes is not loud in layout (F-3c91e814): as one 219-character string it
            # soft-wrapped onto three rows of which two started at column 0, so the only row
            # that still read as a child of `pcraft <version>` was the first one.
            for line in _version_mismatch_lines(report.version_warning, _term_width()):
                _say(line, as_json=as_json)
        py_mark = "ok" if report.python_ok else "FAIL"
        _say(f"python {report.python}  ({py_mark}; need >= 3.11)", as_json=as_json)
        _say(f"  interpreter: {report.executable}", as_json=as_json)
        if report.pcraft_python is not None:
            # Named even when it matches: "what I configured is what answered" is the fact
            # an operator came here for, and silence cannot carry it.
            _say(
                f"  PCRAFT_PYTHON: {report.pcraft_python}"
                + ("" if _same_interpreter(report.pcraft_python, report.executable)
                   else "  (NOT the interpreter that answered)"),
                as_json=as_json,
            )
        for extra in report.extras:
            mark = "present" if extra.present else "missing"
            missing = [name for name, ok in extra.modules.items() if not ok]
            # `mark` is already the word "missing", so the old `f"  missing {missing}"` printed
            # it twice and then repr'd the module list after it: `[image] missing  missing
            # ['torch', ...]`. Naming the modules as a parenthetical says what to install
            # instead of restating the status (F-2d223d8e).
            detail = f"  (need {', '.join(missing)})" if missing else ""
            _say(f"[{extra.name}] {mark}{detail}", as_json=as_json)
        if report.store_ok:
            _say(
                f"store ok  {len(report.store_ids)} contracts"
                + (f"  thresholds={report.thresholds_version}" if report.thresholds_version else ""),
                as_json=as_json,
            )
        else:
            _say(f"store FAIL  {report.store_error}", as_json=as_json)
        if as_json:
            _emit_model(report)
        if not report.python_ok or not report.store_ok:
            raise typer.Exit(code=1)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


def _extra_status(name: str, modules: tuple[str, ...]) -> ExtraStatus:
    found = {mod: importlib.util.find_spec(mod) is not None for mod in modules}
    return ExtraStatus(name=name, present=all(found.values()), modules=found)


def _same_interpreter(configured: str, running: str) -> bool:
    """Whether PCRAFT_PYTHON and sys.executable name the same file.

    A best-effort comparison, and deliberately so: a bare name like ``python`` resolves
    through PATH and a bogus path does not resolve at all, so this must never raise. When it
    cannot tell, it says "not the same" -- flagging a match that is really a mismatch is the
    failure that sends an operator away satisfied.
    """
    try:
        return os.path.normcase(os.path.realpath(configured)) == os.path.normcase(
            os.path.realpath(running)
        )
    except (OSError, ValueError):
        return False


def _run_doctor(contracts_dirs: list[Path] | None, thresholds: Path | None) -> DoctorReport:
    from ..core.gate.thresholds import load_thresholds
    from ..domains.image.subdomains.sprite import THRESHOLDS_PATH
    from ..sample import IMAGE_EXTRA_MODULES, load_store

    py = sys.version.split()[0]
    extras = [
        # IMAGE_EXTRA_MODULES, not a second literal: doctor's list and bind --no-mock's
        # live door drifted apart once (F-62bb6e8d), and the door was the weaker of the
        # two. One constant, both call sites.
        _extra_status("image", IMAGE_EXTRA_MODULES),
        _extra_status("synth", ("dspy",)),
    ]
    note = version_coherence()
    report = DoctorReport(
        version=package_version(),
        python=py,
        python_ok=sys.version_info >= (3, 11),
        extras=extras,
        store_ok=False,
        version_coherent=note is None,
        version_warning=note,
        executable=sys.executable,
        pcraft_python=os.environ.get("PCRAFT_PYTHON"),
    )
    try:
        store = load_store(contracts_dirs)
        report.store_ids = list(store.ids())
        table = load_thresholds(thresholds or THRESHOLDS_PATH)
        report.thresholds_version = table.version
        report.store_ok = True
    except PromptCraftError as err:
        report.store_error = err.to_safe_text()
    return report


@app.command(name="schema")
def schema_cmd(
    out: Path | None = typer.Option(None, "--out", help="write the JSON Schema here; default stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Emit JSON Schema for the authoring contract. No generate, no gate."""
    from ..core.contract.schema import export_json_schema

    try:
        text = json.dumps(export_json_schema(), indent=2)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        typer.echo(text)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


def _parse_image_names(pairs: list[str]) -> dict[str, str]:
    """``local.png=cloud-hash.png`` pairs from --image-name. Splits on the LAST ``=``.

    The split direction is a decision, not a default (F-b795e5ca). ``=`` is a legal filename
    character on Windows and POSIX alike, and the local side is a free-form plate filename --
    ``kontext_fill`` builds it from ``Path(lock.identity[0]).name``, which is whatever the
    contract's reference lock points at. The cloud side is a Comfy upload name and cannot
    contain one. So the ambiguity in ``a=b=c`` has exactly one safe reading: the extra ``=``
    belongs to the local filename.

    Splitting on the FIRST ``=`` read it the other way and said nothing: measured,
    ``['weird=name.png=cloud-upload.png']`` returned ``{'weird': 'name.png=cloud-upload.png'}``
    -- a local key matching no ``LoadImage`` node and a cloud name Comfy never issued. Nothing
    downstream refuses that: ``bind_cloud_names``'s documented behaviour for an unrecognised
    key is "missing keys stay", so the graph is written, uploaded and submitted at real spend
    with the remap silently not applied. Argument parsing is the layer positioned to catch it,
    and it is the layer that has to.

    Refusing multi-``=`` input instead would be fail-closed in form only: it leaves an operator
    whose plate legitimately contains an ``=`` no way to use the flag at all, to protect
    against an ambiguity that is not actually ambiguous. Empty sides are still refused below --
    those have no correct reading.
    """
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise PromptCraftError(
                "INPUT_IMAGE_NAME",
                f"--image-name {raw!r} is not local=cloud",
                hint="Pass --image-name ashen-reaver-front.png=<cloud upload name>.",
            )
        local, cloud = raw.rsplit("=", 1)
        local, cloud = local.strip(), cloud.strip()
        if not local or not cloud:
            raise PromptCraftError(
                "INPUT_IMAGE_NAME",
                f"--image-name {raw!r} is not local=cloud",
                hint="Both sides of the = must be non-empty.",
            )
        out[local] = cloud
    return out


def _loadimage_filenames(graph: dict) -> list[str]:
    """Every filename a ``LoadImage`` node in the emitted graph carries, in node order.

    The GRAPH is the source of truth here, deliberately, and not the upload manifest the
    image domain hangs off ``RecipeReport``. ``bind_cloud_names`` matches on exactly this
    field -- ``inputs['image']`` of every ``class_type == 'LoadImage'`` node -- so diffing
    the parsed pairs against anything else would be checking a DESCRIPTION of the graph
    rather than the thing the rewrite will actually consult. The manifest describes the
    same nodes (it is built from the same ``build_graph`` output), so the two agree by
    construction; where they could ever disagree, the graph is the half that decides what
    gets remapped. Reading it here also means the check needs no field that may or may not
    be present on the report, so ``--image-name`` behaves identically on a build with the
    manifest and one without.
    """
    out: list[str] = []
    for node in graph.values():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        current = (node.get("inputs") or {}).get("image")
        if isinstance(current, str) and current and current not in out:
            out.append(current)
    return out


def _refuse_unmatched_image_names(graph: dict, names: dict[str, str]) -> None:
    """Refuse ``--image-name`` local sides no ``LoadImage`` node in this graph carries.

    F-69661dda. ``_parse_image_names`` above owns the SHAPE half of this refusal -- it can
    see that ``a=b`` is malformed, but it has no graph, so it cannot see that
    ``ashen-reaver-frnt.png`` is a real-looking name matching nothing. That difference was
    the whole failure: ``bind_cloud_names``'s documented behaviour for an unrecognised key
    is "missing keys stay", which is correct for a pure graph rewrite with no opinion about
    intent, and MEASURED the result was exit 0, a graph on disk with the original filename
    still in it, and ``RecipeReport.cloud_names`` recording the pair as though it had been
    applied. The artifact then asserts a remap the graph does not carry, and the next step
    is a Comfy Cloud submit at real spend naming a file Comfy never issued.

    This is a PRE-FLIGHT check, not a change to ``bind_cloud_names``: it runs before the
    rewrite, before the graph is written, and it does not exist when no pairs were passed.
    ``INPUT_`` rather than ``GATE_`` for the same reason ``INPUT_FILL_MASK`` is: a typo'd
    filename is bad user input (exit 1, "fix your input"), not a gate-discipline violation.
    """
    carried = _loadimage_filenames(graph)
    unmatched = [key for key in names if key not in carried]
    if not unmatched:
        return
    keys = ", ".join(repr(k) for k in unmatched)
    side = "local side" if len(unmatched) == 1 else "local sides"
    verb = "matches" if len(unmatched) == 1 else "match"
    loads = ", ".join(repr(name) for name in carried) if carried else "no images at all"
    raise PromptCraftError(
        "INPUT_IMAGE_NAME",
        f"--image-name {side} {keys} {verb} no LoadImage node in this graph",
        hint=f"This graph loads: {loads}. The local side is the basename the node carries, "
        "not a path -- pass it exactly as listed. An unmatched name is not applied by "
        "bind_cloud_names, so the graph would have been written and submitted at real "
        "spend with the original filename still in it.",
    )


# F-763b6107. `recipe`'s whole job is the Kontext reference-lock stitch, and
# `method=reference` is the only identity method that path can apply -- an ip_adapter
# contract is refused by name at assemble time and always will be. So the default has to
# name a contract that DECLARES reference, or a zero-argument `pcraft recipe` cannot
# demonstrate the one path the command exists for; MEASURED on the shipped tree, the bare
# invocation exited 2 with GATE_CONDITIONING_UNSUPPORTED, which is a correct refusal of an
# incorrect default. The SDXL example keeps its own commands: synth / gate / bind /
# validate still default to `char:ashen-reaver`, and naming it here still produces the
# same clean refusal.
#
# STABILITY.md covers this command's "flags and the emitted recipe graph". The flag is
# unchanged -- same name, same string type -- but a zero-argument invocation's OUTPUT
# moves for existing callers, which is a real behaviour change on a covered command and is
# flagged as such rather than filed as obviously safe.
RECIPE_DEFAULT_CONTRACT = "char:ashen-reaver-cloud"


@app.command()
def recipe(
    contract: str = typer.Option(RECIPE_DEFAULT_CONTRACT, help="contract id whose plates feed the stitch; needs identity_ref.method=reference (ip_adapter is the SDXL encoder and is refused here)"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    out: Path = typer.Option(Path("kontext-fill.recipe.json"), "--out", help="write the Comfy API graph here"),
    fill_region: str = typer.Option("fist", help="Fill mask region. fist only -- hands/weapon ate the bracer"),
    fill_mask: Path | None = typer.Option(None, help="optional painted fist-only mask (overrides --fill-region)"),
    seed: int = typer.Option(169405236028824, help="KSampler seed (the measured stitch used this)"),
    image_name: list[str] = typer.Option(
        [],
        "--image-name",
        help="remap a LoadImage filename to a Cloud upload name (local=cloud, repeatable; "
        "split on the LAST '=', so a local filename may contain one). A local side no "
        "LoadImage node carries is refused, and the refusal lists the ones that exist",
    ),
    as_json: bool = typer.Option(False, "--json", help="emit RecipeReport as JSON on stdout"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Write the Cloud Kontext stitch + left crop + fist-only Fill graph. Does not submit.

    This is the method=reference path and only that path. The contract's identity_ref must
    declare method=reference; ip_adapter is the SDXL encoder and is refused by name here,
    so `--contract char:ashen-reaver` (the SDXL example the other commands default to)
    exits 2 rather than building a graph the Kontext recipe could not have applied.
    """
    from ..core.loop.orchestrate import _assemble_conditioning
    from ..domains.image.generator import kontext_fill
    from ..sample import load_workspace

    try:
        _store, resolved, _t, _compiled = load_workspace(
            contracts_dirs=contracts_dir or None, contract_id=contract
        )
        graph, report = kontext_fill.from_conditioning(
            _assemble_conditioning(resolved),
            fill_region=fill_region,
            fill_mask=fill_mask,
            seed=seed,
        )
        names = _parse_image_names(image_name)
        if names:
            # Before the rewrite and before anything is written: a pair naming no node is
            # not applied by bind_cloud_names and must not reach disk as if it were.
            _refuse_unmatched_image_names(graph, names)
            graph = kontext_fill.bind_cloud_names(graph, names)
            report = report.model_copy(update={"cloud_names": names})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        report = report.model_copy(update={"graph_path": str(out.resolve())})
        _say(f"recipe {report.recipe_id}", as_json=as_json)
        _say(f"stages: {' -> '.join(report.stages)}", as_json=as_json)
        bracer_line = {
            True: "bracer: not masked",
            False: "bracer: MASKED",
            None: "bracer: unverified (caller-painted mask)",
        }[report.do_not_mask_bracer]
        _say(f"crop: {report.crop}  fill: {report.fill_region}  {bracer_line}", as_json=as_json)
        _say(f"graph: {report.graph_path}", as_json=as_json)
        _say(f"measured: {report.measured_graph}", as_json=as_json)
        if as_json:
            _emit_model(report)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def compile(  # noqa: A001 - the verb is the command name
    seed: bool = typer.Option(False, help="(re)write the scaffold SEED artifact"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Offline synthesizer compile (GEPA). Heavy + Director-gated -- not on a per-asset path."""
    try:
        if seed:
            from ..core.optimize.compile import write_seed_artifact
            from ..domains.image import COMPILED_ARTIFACT

            prog = write_seed_artifact(COMPILED_ARTIFACT, "sprite.synth",
                                       "Convert depictable atoms into one prompt; every token traces to an atom.")
            typer.echo(f"pinned seed artifact {prog.artifact_id} -> {COMPILED_ARTIFACT}")
            return
        # The compile API is wired. The CLI does not generate pixels, so it
        # cannot build an EXTERNAL gate metric. Python callers pass gate_metric.
        try:
            import dspy  # noqa: F401
        except Exception as err:
            raise PromptCraftError(
                "DEP_SYNTH_MISSING",
                "offline compile needs DSPy + an LM backend",
            ) from err
        raise PromptCraftError(
            "STATE_COMPILE_NEEDS_GATE",
            "pcraft compile needs a Python gate_metric; the CLI does not generate pixels",
            hint="Call compile_synthesizer(trainset, gate_metric, ...) from Python. "
            "The metric is the EXTERNAL gate pass-rate. Use --seed to pin the scaffold artifact.",
        )
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command(name="sync-rules")
def sync_rules(
    db: Path = typer.Option(None, help="path to the readouts sprites-knowledge recipes.db"),
    debug: bool = typer.Option(False, "--debug", help=_DEBUG_HELP),
) -> None:
    """Regenerate domains/image/rules/encoder_craft.md from the readouts prompt-craft lane."""
    # The one command body that used to run unguarded. Only SystemExit was caught, which
    # happens to be how the current script reports a missing DB -- so the contract looked
    # honoured by luck. A PromptCraftError out of module.generate(), an AttributeError from
    # the dynamically loaded script's interface drifting (DEFAULT_OUT / DEFAULT_DB /
    # generate), or a broken transitive import inside it all escaped this file's entire
    # error contract as a raw traceback with Python's default exit 1 -- this contract's
    # code for USER error, for what is an internal defect. (F-dc0ca73f)
    try:
        script = _find_sync_script()
        if script is None:
            _emit(PromptCraftError("IO_SCRIPT_MISSING", "scripts/sync_rules_from_readouts.py not found "
                  "(run from the repo checkout)"), debug)
        spec = importlib.util.spec_from_file_location("_pcraft_sync", script)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        out = module.DEFAULT_OUT
        db_path = db or module.DEFAULT_DB
        try:
            module.generate(Path(db_path), Path(out))
        except SystemExit as err:
            raise typer.Exit(code=int(err.code) if isinstance(err.code, int) else 2) from err
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


def _find_sync_script() -> Path | None:
    # Search only from this package upward. Cwd-first would exec the first
    # scripts/sync_rules_from_readouts.py a caller can plant (CLI-B-001).
    for base in Path(__file__).resolve().parents:
        cand = base / "scripts" / "sync_rules_from_readouts.py"
        if cand.exists():
            return cand
    return None


def _exit_from_result(result, debug: bool) -> None:
    """A non-bound decision must not exit 0.

    Fold-time gap between two wave-2 fixes that could not see each other: core-loop began
    CLASSIFYING a failed generate() instead of letting it escape as a traceback, returning
    `decision="escalated"` with the code in `reason` -- a RESULT, not a raised error. The CLI
    only ever wired exit codes to a raised PromptCraftError, so `pcraft demo` printed
    `decision: ESCALATED (error[RUNTIME_GENERATE_EXHAUSTED])` and exited **0**. Measured
    against the real subprocess, not CliRunner.

    The mapping is not invented here -- it is `error_from_transcript`'s, so the escalation path
    reports exactly what `pcraft gate` would for the same transcript. When the loop never got
    far enough to produce a record, there is no transcript to consult and nothing scored: that
    is `GATE_UNAVAILABLE` (exit 4, could-not-run), never exit 2 -- nothing ran to fail.
    """
    if result.decision == "bound":
        return

    from ..core.gate.exit_contract import error_from_transcript

    if result.record is not None:
        err = error_from_transcript(result.record.gate_transcript)
        if err is not None:
            _emit(err, debug)

    _emit(
        PromptCraftError(
            "GATE_UNAVAILABLE",
            f"the loop did not bind and produced no gate transcript: {result.reason}",
            hint="Nothing was scored, so this is could-not-run (exit 4), not a failed atom "
            "(exit 2). Check the generator/verifier the reason names.",
        ),
        debug,
    )


def _announce_attempt(attempt: int, seed: int, state: str, detail: str = "") -> None:
    """One progress line per generate, on stderr, while it is still useful (F-710c9599).

    ``bind`` printed nothing whatsoever between invocation and final verdict, and the loop it
    drives can run many generate-and-verify cycles inside that silence -- MEASURED with the
    generator slowed, a single failing bind drove the repair ladder to seven attempts and
    emitted zero bytes before returning. Nothing in the report is incremental: the whole
    attempt table is reconstructed by ``_print_result`` after the fact. On live hardware each
    attempt is a real generation plus a full verifier pass, so ``bind --no-mock`` is minutes of
    silence on this product's one spend path, during which an operator cannot distinguish
    "working through attempt 5" from "hung on a model load" -- and the natural answer to that
    ambiguity is Ctrl-C, which the CLI handles correctly (exit 130) and which discards the work
    regardless.

    ``as_json=True`` unconditionally: that is this file's existing routing for non-document
    output, so stdout stays a clean parseable document for --json callers and the lines are
    still there for everyone else. No logger and no levels -- the declined framing is not
    reopened. Only the live path passes this callback in; the mock path is fast enough that
    silence costs nothing, and chattering there would be a regression for the command the test
    suite calls most.
    """
    _say(f"[attempt {attempt}] seed={seed} {state}{detail}", as_json=True)


def _receipt_path(result, records_dir: str | Path) -> Path | None:
    """Where the receipt for this run actually landed. ``None`` when none was written.

    This line used to be built from the literal prefix ``records/`` while both commands that
    print it accept ``--records-dir``, so every non-default value was misreported (F-5b783e17).
    MEASURED through a real subprocess: ``bind --records-dir out/receipts`` wrote
    ``out/receipts/char_...json`` and printed ``receipt: records/char_...json``; feeding the
    printed path to ``replay`` -- the documented next command -- refused ``IO_RECORD_READ`` at
    exit 2, and THAT refusal's hint reads "pcraft bind prints the path it wrote", which sends
    the operator back to the line that misreported it. The recovery loop was closed, not open.

    ``getattr`` rather than a plain attribute read: ``persist()`` already returns the Path it
    wrote and the loop is growing a field to hand that back, but the fallback is not a
    placeholder -- ``persist`` derives the filename as ``Path(records_dir) / f"{record_id}.json"``
    and refuses to overwrite, so reconstructing it here is exact for every path this CLI can
    take. Preferring the written value when it exists means the two can never drift; deriving
    it when it does not means this fix does not wait on a sibling landing.
    """
    if result.record is None:
        return None
    written = getattr(result, "receipt_path", None) or getattr(result, "record_path", None)
    return Path(written) if written else Path(records_dir) / f"{result.record.record_id}.json"


def _ran_mock(result) -> bool | None:
    """Whether the GPU-free stub produced these pixels. ``None`` when nothing was generated.

    Keyed on the generator identity the RECEIPT stamps, never on the ``--mock`` flag
    (F-b1b8fd21). The flag is a request; ``generator_id`` is what actually ran, and it is the
    only one of the two that cannot be wrong. The unconditional banner this replaces printed
    "scores are scripted constants; the image pixels were not read" above a real ``--no-mock``
    BOUND verdict -- the exact inverse of the defect the line was added for, and permanent in
    any CI log archived from that run.

    ``None`` (no record) prints no banner in either direction, and that is the honest answer
    rather than a gap: a run that produced no record produced no scores, so there is nothing
    to disclaim and nothing to vouch for. ``Attempt`` rows carry no generator id, so the
    record is the only evidence available here.
    """
    if result.record is None:
        return None
    from ..testing import is_mock_identity

    return is_mock_identity(result.record.generator_id)


def _print_result(result, *, records_dir: str | Path = "records", as_json: bool = False) -> None:
    # CLI-C-001: demo/bind --mock used to print BOUND + a wall of [PASS] 0.950
    # with no indication the scores never touched pixels. F-b1b8fd21: and then printed the
    # same line on the live path, which is the same conflation running the other way. The
    # live case is marked POSITIVELY -- an absent disclaimer is easy to misread as a stripped
    # banner, whereas a claim in the affirmative is something a reader can check.
    mock = _ran_mock(result)
    if mock is True:
        _say("mock: scores are scripted constants; the image pixels were not read.", as_json=as_json)
    elif mock is False:
        _say("live: scores came from the [image] verifiers reading this image.", as_json=as_json)
    # F-1e1af911. A one-line reason keeps the compact form -- `decision: BOUND  (all required
    # atoms passed)` is 44 characters and correctly grouped, and was never the defect. A reason
    # that arrived with newlines in it is the checkpoint, and it gets the decision line to
    # itself and a block of its own below, so `attempts:` is not stranded behind a parenthesis
    # the reader cannot see the end of.
    reason = result.reason or ""
    if "\n" in reason.strip():
        _say(f"decision: {result.decision.upper()}", as_json=as_json)
        for line in _reason_lines(reason, _term_width()):
            _say(line, as_json=as_json)
        _say("", as_json=as_json)
    else:
        _say(f"decision: {result.decision.upper()}  ({reason})", as_json=as_json)
    _say(f"attempts: {len(result.attempts)}", as_json=as_json)
    for a in result.attempts:
        extra = f" repair={a.repair.value}" if a.repair else ""
        _say(f"  #{a.attempt} seed={a.seed} -> {a.overall.value} ({a.verdict.value}){extra}", as_json=as_json)
    receipt = _receipt_path(result, records_dir)
    if result.record is not None:
        _say("", as_json=as_json)
        _say(
            format_transcript(result.record.gate_transcript, dag=result.record.question_dag),
            as_json=as_json,
        )
        # F-d4e6686f. `bind --help` promises "The last line names the receipt it wrote ...
        # run `pcraft replay` on exactly that path", and the last line was path + two spaces
        # + hash -- which `replay` refuses. That is the recovery loop F-5b783e17 closed,
        # reopened at the layout level. The path now ends the output alone, so a line-select
        # or `tail -1` yields exactly what `replay` accepts at any terminal width; the hash
        # keeps its place in the record by moving UP to its own labelled row. The blank line
        # above detaches the block from the ten-row atom table it was visually continuing.
        _say("", as_json=as_json)
        _say("receipt:", as_json=as_json)
        _say(f"  hash: {result.record.contract_hash[:19]}...", as_json=as_json)
        _say(f"  {receipt}", as_json=as_json)
    if as_json:
        # Additive, and omitted when there is no receipt. The document already carried
        # `record.record_id` and `record.image_path` but never said where the receipt itself
        # landed, so a machine caller had to rejoin record_id with the flag it passed --
        # reimplementing the exact line that was wrong.
        _emit_model(result, receipt_path=None if receipt is None else str(receipt))


if __name__ == "__main__":
    app()
