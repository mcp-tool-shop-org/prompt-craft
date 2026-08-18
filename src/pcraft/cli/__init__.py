"""The ``pcraft`` CLI: synth | gate | bind | compile | replay | sync-rules | demo.

Errors use the structured shape (code/message/hint) and map to exit codes 0/1/2/3; raw tracebacks
are gated behind --debug."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer

from ..errors import PromptCraftError
from ..gate_report import format_transcript  # local helper (see below)

app = typer.Typer(add_completion=False, help="Contract-driven generative-asset production.")


def _emit(err: PromptCraftError, debug: bool) -> None:
    typer.echo(err.to_debug_text() if debug else err.to_safe_text(), err=True)
    raise typer.Exit(code=err.exit_code)


@app.command()
def synth(
    contract: str = typer.Option("char:ashen-reaver", help="contract id to synthesize"),
    debug: bool = typer.Option(False),
) -> None:
    """Synthesize a prompt from a contract (deterministic template synthesizer)."""
    from ..core.synth.signature import TemplateSynthesizer
    from ..sample import _encoder_rules, load_sprite_example

    try:
        store, _resolved, _t, compiled = load_sprite_example()
        resolved = store.resolve(contract)
        result = TemplateSynthesizer(compiled).synthesize(resolved, _encoder_rules())
        typer.echo(f"prompt: {result.prompt}")
        typer.echo(f"negative: {result.negative_prompt}")
        typer.echo(f"backend: {result.backend} (degraded={result.degraded})")
        typer.echo("atom_coverage:")
        for atom_id, phrase in result.atom_coverage.items():
            typer.echo(f"  {atom_id}: {phrase}")
    except PromptCraftError as err:
        _emit(err, debug)


@app.command()
def gate(
    image: Path = typer.Argument(..., help="rendered image to gate"),
    contract: str = typer.Option("char:ashen-reaver"),
    debug: bool = typer.Option(False),
) -> None:
    """Run the contract gate. Missing path, unreadable file, and 'no verifier
    could score' are refuses (nonzero exit). SKIPPED atoms are not a pass."""
    import pcraft.domains.image  # noqa: F401  (registers the plugin)
    from ..core.contract.compile_questions import compile_questions
    from ..core.gate import harness
    from ..core.plugin import get
    from ..sample import load_sprite_example

    try:
        from ..core.gate.exit_contract import error_from_transcript
        from ..core.gate.preflight import preflight_image

        preflight_image(image)
        store, _r, thresholds, _c = load_sprite_example()
        resolved = store.resolve(contract)
        dag = compile_questions(resolved)
        verifiers = get("image").verifiers()
        transcript = harness.evaluate(dag, str(image), verifiers, thresholds)
        typer.echo(format_transcript(transcript))
        err = error_from_transcript(transcript)
        if err is not None:
            _emit(err, debug)
    except PromptCraftError as err:
        _emit(err, debug)


@app.command()
def bind(
    contract: str = typer.Option("char:ashen-reaver"),
    mock: bool = typer.Option(True, help="use deterministic stubs (GPU-free); the default scaffold path"),
    records_dir: str = typer.Option("records"),
    debug: bool = typer.Option(False),
) -> None:
    """Run the full synth->generate->gate->retry->bind loop and report the decision."""
    from ..sample import run_mock_loop

    if not mock:
        _emit(PromptCraftError("DEP_IMAGE_MISSING", "real bind needs the [image] extra + a GPU; "
              "use --mock for the GPU-free scaffold path"), debug)
    try:
        result = run_mock_loop(records_dir=records_dir)
        _print_result(result)
        if result.decision != "bound":
            raise typer.Exit(code=3)
    except PromptCraftError as err:
        _emit(err, debug)


@app.command()
def demo(records_dir: str = typer.Option("records"), debug: bool = typer.Option(False)) -> None:
    """End-to-end sample run on the generic example contract (GPU-free)."""
    from ..sample import load_sprite_example, run_mock_loop

    try:
        _s, resolved, _t, _c = load_sprite_example()
        typer.echo(f"contract: {resolved.id}  lineage: {' -> '.join(resolved.lineage)}")
        typer.echo(f"required atoms: {[a.id for a in resolved.required_atoms()]}")
        typer.echo(f"must_not: {[m.id for m in resolved.must_not]}")
        typer.echo("")
        result = run_mock_loop(records_dir=records_dir)
        _print_result(result)
    except PromptCraftError as err:
        _emit(err, debug)


@app.command()
def replay(record: Path = typer.Argument(...), debug: bool = typer.Option(False)) -> None:
    """Replay a receipt: reconstruct its question DAG from the contract and assert no drift."""
    from ..core.receipt.asset_record import load, replay as do_replay
    from ..sample import load_sprite_example

    try:
        rec = load(record)
        store, _r, _t, _c = load_sprite_example()
        resolved = store.resolve(rec.contract_id)
        do_replay(rec, resolved)
        typer.echo(f"replay OK: {rec.record_id} reproduces from {rec.contract_id} ({rec.contract_hash[:19]}...)")
    except PromptCraftError as err:
        _emit(err, debug)


@app.command()
def compile(  # noqa: A001 - the verb is the command name
    seed: bool = typer.Option(False, help="(re)write the scaffold SEED artifact"),
    debug: bool = typer.Option(False),
) -> None:
    """Offline synthesizer compile (GEPA). Heavy + Director-gated — not on a per-asset path."""
    if seed:
        from ..core.optimize.compile import write_seed_artifact
        from ..domains.image import COMPILED_ARTIFACT

        prog = write_seed_artifact(COMPILED_ARTIFACT, "sprite.synth",
                                   "Convert depictable atoms into one prompt; every token traces to an atom.")
        typer.echo(f"pinned seed artifact {prog.artifact_id} -> {COMPILED_ARTIFACT}")
        return
    typer.echo(
        "offline compile is GEPA over the EXTERNAL gate pass-rate (no self-verification), run with\n"
        "the [synth] extra + watchdog up, gated by the Director. The 600B compiles; the cheap local\n"
        "model runs the pinned artifact per asset. Wire dspy.GEPA in core/optimize/compile.py, then\n"
        "pin via optimize.artifact.pin(). Use --seed to (re)write the scaffold seed."
    )


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
    for base in (Path.cwd(), *Path(__file__).resolve().parents):
        cand = base / "scripts" / "sync_rules_from_readouts.py"
        if cand.exists():
            return cand
    return None


def _print_result(result) -> None:
    typer.echo(f"decision: {result.decision.upper()}  ({result.reason})")
    typer.echo(f"attempts: {len(result.attempts)}")
    for a in result.attempts:
        extra = f" repair={a.repair.value}" if a.repair else ""
        typer.echo(f"  #{a.attempt} seed={a.seed} -> {a.overall.value} ({a.verdict.value}){extra}")
    if result.record is not None:
        typer.echo("")
        typer.echo(format_transcript(result.record.gate_transcript))
        typer.echo(f"receipt: records/{result.record.record_id}.json  hash={result.record.contract_hash[:19]}...")


if __name__ == "__main__":
    app()
