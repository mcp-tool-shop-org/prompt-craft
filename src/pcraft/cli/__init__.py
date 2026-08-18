"""The ``pcraft`` CLI: synth | gate | bind | list | validate | compile | replay | sync-rules | demo | doctor | recipe | schema.

Errors use the structured shape (code/message/hint) and map to exit codes 0/1/2/3/4; raw
tracebacks are gated behind --debug. ``--json`` on the dumpable commands writes the pydantic
model to stdout and the human banner to stderr."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import typer
from pydantic import BaseModel, ConfigDict

# Typer 0.26 vendored Click as `typer._click`; 0.25 and earlier use the standalone
# `click` package. pyproject declares `typer>=0.12`, so BOTH are inside the range this
# package says it supports and neither import works on its own. Reaching for one and
# not the other made the whole CLI unimportable on a conforming install
# (ModuleNotFoundError at import time, before any command runs) — caught only because
# the swarm's deterministic floor happened to run on a different interpreter than the
# dev venv. These are the exception types Click raises for its OWN parser errors; there
# is no public re-export of them under either layout, so the fallback is the portable
# form rather than a preference.
try:
    from typer._click.exceptions import Abort as _ClickAbort
    from typer._click.exceptions import ClickException as _ClickException
except ModuleNotFoundError:  # typer < 0.26
    from click.exceptions import Abort as _ClickAbort
    from click.exceptions import ClickException as _ClickException
from typer.core import TyperGroup

from .. import package_version
from ..errors import PromptCraftError, wrap_error
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
            typer.echo("Aborted!", err=True)
            sys.exit(1)
        sys.exit(rv if isinstance(rv, int) else 0)


app = typer.Typer(
    add_completion=False,
    help="Contract-driven generative-asset production.",
    cls=_ExitContractGroup,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"pcraft {package_version()}")
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


def _emit(err: PromptCraftError, debug: bool) -> None:
    typer.echo(err.to_debug_text() if debug else err.to_safe_text(), err=True)
    raise typer.Exit(code=err.exit_code)


def _say(text: str, *, as_json: bool = False) -> None:
    """Human text. When ``--json``, the banner goes to stderr so stdout stays a document."""
    typer.echo(text, err=as_json)


def _emit_model(model: BaseModel) -> None:
    typer.echo(model.model_dump_json(indent=2))


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


@app.command()
def synth(
    contract: str = typer.Option("char:ashen-reaver", help="contract id to synthesize"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    as_json: bool = typer.Option(False, "--json", help="emit SynthResult as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """Synthesize a prompt from a contract (deterministic template synthesizer)."""
    from ..core.synth.signature import TemplateSynthesizer
    from ..sample import _encoder_rules, load_workspace

    try:
        store, resolved, _t, compiled = load_workspace(
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


@app.command()
def gate(
    image: Path = typer.Argument(..., help="rendered image to gate"),
    contract: str = typer.Option("char:ashen-reaver"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    generator_family: str = typer.Option(
        None,
        help="override the generator family the same-family gate guard checks against "
        "(defaults to the registered image domain's own generator.family)",
    ),
    as_json: bool = typer.Option(False, "--json", help="emit GateTranscript as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """Run the contract gate. Missing path, unreadable file, and 'no verifier
    could score' are refuses (nonzero exit). SKIPPED atoms are not a pass."""
    import pcraft.domains.image  # noqa: F401  (registers the plugin)
    from ..core.contract.compile_questions import compile_questions
    from ..core.gate import harness
    from ..core.plugin import get
    from ..sample import load_workspace

    try:
        from ..core.gate.exit_contract import error_from_transcript
        from ..core.gate.preflight import preflight_image

        preflight_image(image)
        store, resolved, table, _c = load_workspace(
            contracts_dirs=contracts_dir or None, thresholds=thresholds, contract_id=contract
        )
        dag = compile_questions(resolved)
        plugin = get("image")
        verifiers = plugin.verifiers()
        family = generator_family or plugin.generator().family
        transcript = harness.evaluate(dag, str(image), verifiers, table, generator_family=family)
        _say(format_transcript(transcript), as_json=as_json)
        if as_json:
            _emit_model(transcript)
        err = error_from_transcript(transcript)
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
    contract: str = typer.Option("char:ashen-reaver"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    mock: bool = typer.Option(True, help="use deterministic stubs (GPU-free); the default scaffold path"),
    records_dir: str = typer.Option("records"),
    as_json: bool = typer.Option(False, "--json", help="emit OrchestrationResult as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """Run the full synth->generate->gate->retry->bind loop and report the decision."""
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
            )
        _print_result(result, as_json=as_json)
        # Replaces a blanket `raise typer.Exit(code=3)`: every non-bound decision reported 3
        # regardless of cause, so "could not run at all" and "ran, unconfirmed" were the same
        # number to a caller — the merge the four-way contract exists to prevent.
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
    debug: bool = typer.Option(False),
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
    debug: bool = typer.Option(False),
) -> None:
    """Resolve a contract and compile its question DAG. No generate, no gate."""
    from ..core.contract.compile_questions import compile_questions
    from ..sample import load_workspace

    try:
        store, resolved, _t, _c = load_workspace(
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
        _say(f"required: {report.required}", as_json=as_json)
        _say(f"must_not: {report.must_not}", as_json=as_json)
        _say(f"questions: {len(dag.questions)}", as_json=as_json)
        if as_json:
            _emit_model(report)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def demo(
    records_dir: str = typer.Option("records"),
    as_json: bool = typer.Option(False, "--json", help="emit OrchestrationResult as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """End-to-end sample run on the generic example contract (GPU-free)."""
    from ..sample import load_sprite_example, run_mock_loop

    try:
        _s, resolved, _t, _c = load_sprite_example()
        _say(f"contract: {resolved.id}  lineage: {' -> '.join(resolved.lineage)}", as_json=as_json)
        _say(f"required atoms: {[a.id for a in resolved.required_atoms()]}", as_json=as_json)
        _say(f"must_not: {[m.id for m in resolved.must_not]}", as_json=as_json)
        _say("", as_json=as_json)
        result = run_mock_loop(records_dir=records_dir)
        _print_result(result, as_json=as_json)
        _exit_from_result(result, debug)
    except PromptCraftError as err:
        _emit(err, debug)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - the final backstop; classify, don't swallow
        _emit(wrap_error(e, "RUNTIME_UNEXPECTED"), debug)


@app.command()
def replay(
    record: Path = typer.Argument(...),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    as_json: bool = typer.Option(False, "--json", help="emit AssetRecord as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """Replay a receipt: reconstruct its question DAG from the contract and assert no drift."""
    from ..core.receipt.asset_record import load, replay as do_replay
    from ..sample import load_store

    try:
        rec = load(record)
        store = load_store(contracts_dir or None)
        resolved = store.resolve(rec.contract_id)
        do_replay(rec, resolved)
        _say(
            f"replay OK: {rec.record_id} reproduces from {rec.contract_id} ({rec.contract_hash[:19]}...)",
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


@app.command()
def doctor(
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    thresholds: Path | None = typer.Option(None, "--thresholds", help="threshold table JSON; default: shipped sprite calibration"),
    as_json: bool = typer.Option(False, "--json", help="emit DoctorReport as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """Check python, optional extras, and that the contract store loads. GPU-free."""
    try:
        report = _run_doctor(contracts_dir or None, thresholds)
        _say(f"pcraft {report.version}", as_json=as_json)
        py_mark = "ok" if report.python_ok else "FAIL"
        _say(f"python {report.python}  ({py_mark}; need >= 3.11)", as_json=as_json)
        for extra in report.extras:
            mark = "present" if extra.present else "missing"
            missing = [name for name, ok in extra.modules.items() if not ok]
            detail = f"  missing {missing}" if missing else ""
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


def _run_doctor(contracts_dirs: list[Path] | None, thresholds: Path | None) -> DoctorReport:
    from ..core.gate.thresholds import load_thresholds
    from ..domains.image.subdomains.sprite import THRESHOLDS_PATH
    from ..sample import load_store

    py = sys.version.split()[0]
    extras = [
        _extra_status("image", ("torch", "diffusers", "transformers", "PIL")),
        _extra_status("synth", ("dspy",)),
    ]
    report = DoctorReport(
        version=package_version(),
        python=py,
        python_ok=sys.version_info >= (3, 11),
        extras=extras,
        store_ok=False,
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
    debug: bool = typer.Option(False),
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
    """``local.png=cloud-hash.png`` pairs from --image-name."""
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise PromptCraftError(
                "INPUT_IMAGE_NAME",
                f"--image-name {raw!r} is not local=cloud",
                hint="Pass --image-name ashen-reaver-front.png=<cloud upload name>.",
            )
        local, cloud = raw.split("=", 1)
        local, cloud = local.strip(), cloud.strip()
        if not local or not cloud:
            raise PromptCraftError(
                "INPUT_IMAGE_NAME",
                f"--image-name {raw!r} is not local=cloud",
                hint="Both sides of the = must be non-empty.",
            )
        out[local] = cloud
    return out


@app.command()
def recipe(
    contract: str = typer.Option("char:ashen-reaver", help="contract id whose plates feed the stitch"),
    contracts_dir: list[Path] = typer.Option([], "--contracts-dir", help="tree of *.contract.json (repeatable); default: shipped sprite example"),
    out: Path = typer.Option(Path("kontext-fill.recipe.json"), "--out", help="write the Comfy API graph here"),
    fill_region: str = typer.Option("fist", help="Fill mask region. fist only — hands/weapon ate the bracer"),
    fill_mask: Path | None = typer.Option(None, help="optional painted fist-only mask (overrides --fill-region)"),
    seed: int = typer.Option(169405236028824, help="KSampler seed (the measured stitch used this)"),
    image_name: list[str] = typer.Option(
        [],
        "--image-name",
        help="remap a LoadImage filename to a Cloud upload name (local=cloud, repeatable)",
    ),
    as_json: bool = typer.Option(False, "--json", help="emit RecipeReport as JSON on stdout"),
    debug: bool = typer.Option(False),
) -> None:
    """Write the Cloud Kontext stitch + left crop + fist-only Fill graph. Does not submit."""
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
            graph = kontext_fill.bind_cloud_names(graph, names)
            report = report.model_copy(update={"cloud_names": names})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        report = report.model_copy(update={"graph_path": str(out.resolve())})
        _say(f"recipe {report.recipe_id}", as_json=as_json)
        _say(f"stages: {' -> '.join(report.stages)}", as_json=as_json)
        _say(f"crop: {report.crop}  fill: {report.fill_region}  bracer: not masked", as_json=as_json)
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
    debug: bool = typer.Option(False),
) -> None:
    """Offline synthesizer compile (GEPA). Heavy + Director-gated — not on a per-asset path."""
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
    debug: bool = typer.Option(False),
) -> None:
    """Regenerate domains/image/rules/encoder_craft.md from the readouts prompt-craft lane."""
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
    `decision="escalated"` with the code in `reason` — a RESULT, not a raised error. The CLI
    only ever wired exit codes to a raised PromptCraftError, so `pcraft demo` printed
    `decision: ESCALATED (error[RUNTIME_GENERATE_EXHAUSTED])` and exited **0**. Measured
    against the real subprocess, not CliRunner.

    The mapping is not invented here — it is `error_from_transcript`'s, so the escalation path
    reports exactly what `pcraft gate` would for the same transcript. When the loop never got
    far enough to produce a record, there is no transcript to consult and nothing scored: that
    is `GATE_UNAVAILABLE` (exit 4, could-not-run), never exit 2 — nothing ran to fail.
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


def _print_result(result, *, as_json: bool = False) -> None:
    # CLI-C-001: demo/bind --mock used to print BOUND + a wall of [PASS] 0.950
    # with no indication the scores never touched pixels.
    _say("mock: scores are scripted constants; the image pixels were not read.", as_json=as_json)
    _say(f"decision: {result.decision.upper()}  ({result.reason})", as_json=as_json)
    _say(f"attempts: {len(result.attempts)}", as_json=as_json)
    for a in result.attempts:
        extra = f" repair={a.repair.value}" if a.repair else ""
        _say(f"  #{a.attempt} seed={a.seed} -> {a.overall.value} ({a.verdict.value}){extra}", as_json=as_json)
    if result.record is not None:
        _say("", as_json=as_json)
        _say(format_transcript(result.record.gate_transcript), as_json=as_json)
        _say(
            f"receipt: records/{result.record.record_id}.json  hash={result.record.contract_hash[:19]}...",
            as_json=as_json,
        )
    if as_json:
        _emit_model(result)


if __name__ == "__main__":
    app()
