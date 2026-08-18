"""Regression tests for the wave-2 image-plugin amend pass (health-amend-a).

Six Director-approved findings (F-657db549, F-d628ec97, F-dd568f7f, F-2ef1bb79, F-4409b547,
F-10b380ba, F-721a7139 -- conditioning silently ignored on two generators counts as one finding
pair), fixed with an explicit scope ceiling: no ControlNet, no IP-Adapter, no GPU extra install, no
model download. The governing fact: this domain's code has never executed on any machine (no torch,
no diffusers, no ai_eyes_mcp, no t2v_metrics installed here). Every test below either

  (a) exercises a code path that fails/returns BEFORE any of those imports is needed, or
  (b) injects a minimal fake stand-in into ``sys.modules`` via ``monkeypatch`` (auto-reverted at
      teardown, per test) so the branch logic is covered without ever requiring the real package.

``test_no_fake_modules_leak_past_this_files_tests`` at the bottom is the canary for (b): every
fake-module test must use ``monkeypatch.setitem``, never raw ``sys.modules[...] =`` assignment, or
this file would poison later tests (notably ``tests/test_core_is_gpu_free.py``, which this file must
never cause to fail)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import pcraft.domains.image  # noqa: F401  (registers the plugin)
from pcraft.core.contract.compile_questions import Polarity, Question
from pcraft.core.contract.schema import CheckType, Severity
from pcraft.domains.image.generator.flux_generator import FluxGenerator
from pcraft.domains.image.generator.sdxl_generator import SDXLGenerator
from pcraft.domains.image.subdomains.sprite.identity_subgate import IdentitySubGate
from pcraft.domains.image.verifier.dsg_verifier import DSGVerifier
from pcraft.domains.image.verifier.siglip2_screen import SigLIP2Screen
from pcraft.domains.image.verifier.vqascore_verifier import DEFAULT_MODEL_ID, VQAScoreVerifier
from pcraft.errors import PromptCraftError


def _question(check_type: CheckType = CheckType.vqa) -> Question:
    return Question(
        atom_id="atom-1",
        text="Does this image show a crimson tabard?",
        check_type=check_type,
        polarity=Polarity.affirm,
        severity=Severity.required,
    )


# --------------------------------------------------------------------------- fake module builders
# Minimal stand-ins installed into sys.modules via monkeypatch, so the `import torch` / `from
# diffusers import ...` / `from ai_eyes_mcp.engine import ...` / `import t2v_metrics` statements
# inside the real source resolve without a real install. Every call site below takes `monkeypatch`
# and uses `monkeypatch.setitem` so the change is undone automatically after each test.


def _install_fake_torch(monkeypatch, *, cuda_available: bool) -> types.ModuleType:
    fake_torch = types.ModuleType("torch")

    class _Cuda:
        @staticmethod
        def is_available():
            return cuda_available

    class _Generator:
        def __init__(self, device="cpu"):
            self.device = device

        def manual_seed(self, seed):
            self.seed = seed
            return self

    fake_torch.cuda = _Cuda
    fake_torch.Generator = _Generator
    fake_torch.float16 = "float16-sentinel"
    fake_torch.bfloat16 = "bfloat16-sentinel"
    fake_torch.float32 = "float32-sentinel"
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    return fake_torch


class _FakeImage:
    def save(self, path):
        Path(path).write_bytes(b"fake-png")


class _FakePipe:
    """Records every .to()/call so tests can assert on the device+dtype+conditioning plumbing."""

    def __init__(self, model_id, **kwargs):
        self.model_id = model_id
        self.init_kwargs = kwargs
        self.to_calls: list[str] = []
        self.call_kwargs = None
        self.device = "cpu"

    def to(self, device):
        self.to_calls.append(device)
        self.device = device
        return self

    def load_ip_adapter(self, *args, **kwargs):
        self.ip_adapter = {"args": args, "kwargs": kwargs}

    def set_ip_adapter_scale(self, scale):
        self.ip_scale = scale

    def __call__(self, **kwargs):
        self.call_kwargs = kwargs
        return types.SimpleNamespace(images=[_FakeImage()])


class _RaisingOnToPipe(_FakePipe):
    def to(self, device):
        raise RuntimeError("simulated CUDA out of memory on .to()")


class _RaisingOnCallPipe(_FakePipe):
    def __call__(self, **kwargs):
        raise RuntimeError("simulated shape mismatch at call time")


def _install_fake_diffusers(monkeypatch, *, pipeline_attr: str, pipe_cls=_FakePipe) -> dict:
    """Installs a fake `diffusers` module exposing one pipeline class at `pipeline_attr`
    ("StableDiffusionXLPipeline" or "FluxPipeline"). Returns a dict that gets `["pipe"]` set to the
    constructed fake pipe once `.from_pretrained(...)` runs, so a test can inspect it afterwards."""
    fake_diffusers = types.ModuleType("diffusers")
    captured: dict = {}

    class _PipelineCls:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            p = pipe_cls(model_id, **kwargs)
            captured["pipe"] = p
            return p

    setattr(fake_diffusers, pipeline_attr, _PipelineCls)
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    return captured


def _install_fake_ai_eyes_engine(monkeypatch, engine_cls) -> None:
    fake_pkg = types.ModuleType("ai_eyes_mcp")
    fake_engine_mod = types.ModuleType("ai_eyes_mcp.engine")
    fake_engine_mod.SigLIPEngine = engine_cls
    monkeypatch.setitem(sys.modules, "ai_eyes_mcp", fake_pkg)
    monkeypatch.setitem(sys.modules, "ai_eyes_mcp.engine", fake_engine_mod)


def _install_fake_t2v_metrics(monkeypatch, vqascore_cls) -> None:
    fake_t2v = types.ModuleType("t2v_metrics")
    fake_t2v.VQAScore = vqascore_cls
    monkeypatch.setitem(sys.modules, "t2v_metrics", fake_t2v)


# =========================================================================== F-657db549 / F-d628ec97
# conditioning is accepted, documented, and never read. generate() must now refuse rather than
# silently no-op when asked for pose_refs/identity_refs it cannot apply. No fake torch/diffusers
# needed for the refusal cases: the check fires before _load() is ever called.


def test_sdxl_refuses_a_missing_pose_ref():
    """Feature pass: SDXL implements ControlNet, but a missing plate is still a refuse
    (not a silent txt2img). The Stage A code was GATE_CONDITIONING_UNSUPPORTED for any
    nonempty list; the capability exists now, the unreadability does not."""
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"pose_refs": ["poses/front.openpose.png"]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_REF_MISSING"


def test_sdxl_refuses_a_missing_identity_plate():
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"identity_refs": [{"plate": "ref.png", "method": "ip_adapter"}]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_REF_MISSING"
    assert "identity" in (exc.value.hint or "").lower()
    assert "Drop pose_refs" not in (exc.value.hint or "")


def test_sdxl_allows_empty_pose_and_identity_lists():
    """_assemble_conditioning() (core/loop/orchestrate.py) always includes both keys, often as [].
    An empty list means 'not requested', not 'requested and unsupported' -- it must fall through to
    _load(), not be refused. torch/diffusers are genuinely absent here, so the next thing that
    happens is DEP_IMAGE_MISSING -- but it must NOT be GATE_CONDITIONING_UNSUPPORTED."""
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"pose_refs": [], "identity_refs": []}, seed=1)
    assert exc.value.code == "DEP_IMAGE_MISSING"


def test_sdxl_allows_conditioning_with_no_pose_or_identity_keys_at_all():
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {}, seed=1)
    assert exc.value.code == "DEP_IMAGE_MISSING"


def test_flux_refuses_nonempty_pose_refs():
    gen = FluxGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"pose_refs": ["poses/front.openpose.png"]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"


def test_flux_refuses_nonempty_identity_refs():
    gen = FluxGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"identity_refs": [{"plate": "ref.png"}]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"


def test_conditioning_refusal_names_the_generator_that_refused():
    """Not a generic message -- names which generator refused, so a human reading the crash knows
    which plugin lacks the capability rather than having to guess."""
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"pose_refs": ["x"]}, seed=1)
    assert gen.generator_id in str(exc.value)
    assert exc.value.code == "GATE_CONDITIONING_REF_MISSING"


# =========================================================================== F-10b380ba
# neither _load() ever called .to(<device>) on the pipeline, nor passed an explicit torch_dtype.


def test_sdxl_load_moves_pipe_to_cpu_and_uses_float32_when_no_cuda(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=False)
    captured = _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    gen = SDXLGenerator()
    pipe = gen._load()
    assert pipe.to_calls == ["cpu"]
    assert captured["pipe"].init_kwargs["torch_dtype"] == "float32-sentinel"


def test_sdxl_load_moves_pipe_to_cuda_and_uses_float16_when_cuda_available(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=True)
    captured = _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    gen = SDXLGenerator()
    pipe = gen._load()
    assert pipe.to_calls == ["cuda"]
    assert captured["pipe"].init_kwargs["torch_dtype"] == "float16-sentinel"


def test_flux_prefers_bfloat16_on_cuda(monkeypatch):
    """FLUX.1-dev is the 12B-parameter model whose official usage snippet loads bf16 specifically
    to avoid roughly doubling its footprint in float32 -- a distinct dtype policy from SDXL."""
    _install_fake_torch(monkeypatch, cuda_available=True)
    captured = _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    gen = FluxGenerator()
    pipe = gen._load()
    assert pipe.to_calls == ["cuda"]
    assert captured["pipe"].init_kwargs["torch_dtype"] == "bfloat16-sentinel"


def test_flux_uses_float32_on_cpu_not_bfloat16(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=False)
    captured = _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    gen = FluxGenerator()
    gen._load()
    assert captured["pipe"].init_kwargs["torch_dtype"] == "float32-sentinel"


def test_sdxl_select_device_failure_is_classified_not_unboundlocal(monkeypatch):
    """IMG-W8-001: if select_device raises, the except used to interpolate unbound `device`."""
    fake = _install_fake_torch(monkeypatch, cuda_available=True)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")

    def boom():
        raise RuntimeError("cuda init failed")

    monkeypatch.setattr(fake.cuda, "is_available", boom)
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen._load()
    assert exc.value.code == "RUNTIME_GENERATOR_LOAD_FAILED"
    assert "unset" in exc.value.message
    assert isinstance(exc.value.cause, RuntimeError)


def test_sdxl_load_failure_on_to_is_classified_not_raw(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=True)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline", pipe_cls=_RaisingOnToPipe)
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen._load()
    assert exc.value.code == "RUNTIME_GENERATOR_LOAD_FAILED"
    assert isinstance(exc.value.cause, RuntimeError)


def test_sdxl_load_is_memoized_so_to_is_called_once(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    gen = SDXLGenerator()
    pipe1 = gen._load()
    pipe2 = gen._load()
    assert pipe1 is pipe2
    assert pipe1.to_calls == ["cpu"]  # not called a second time on the memoized path


# =========================================================================== F-4409b547
# SDXLGenerator reported `sampler` verbatim though _load() never configures a scheduler to match
# it. Chosen fix (see sdxl_generator.py's module docstring): stop claiming it was applied, rather
# than implement a real DPMSolverMultistepScheduler swap this pass cannot verify without diffusers.


def test_default_sampler_is_reported_as_unapplied(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {}, seed=1)
    assert "dpmpp_2m_karras" in result.sampler
    assert "not applied" in result.sampler.lower()


def test_an_explicit_sampler_override_is_also_reported_as_unapplied(monkeypatch, tmp_path):
    """Closes the gap a naive 'just change the default' fix would miss: even a caller who
    explicitly requests a specific sampler gets an honest receipt, because _load() never
    configures ANY scheduler regardless of what was requested."""
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    gen = SDXLGenerator(sampler="euler-a", out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {}, seed=1)
    assert "euler-a" in result.sampler
    assert "not applied" in result.sampler.lower()


def test_flux_sampler_claim_is_unchanged_and_out_of_scope(monkeypatch, tmp_path):
    """F-4409b547 names SDXLGenerator specifically. FluxGenerator's hardcoded 'flow-match' is
    plausibly accurate (FLUX ships a flow-match-family scheduler by default, unconfigured) and is
    deliberately left untouched -- this pins the current reported value so any future change to it
    is a conscious decision, not silent drift. FluxGenerator also has no `sampler` constructor
    param at all (nothing for a caller to be misled by)."""
    import inspect

    assert "sampler" not in inspect.signature(FluxGenerator.__init__).parameters

    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    gen = FluxGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {}, seed=1)
    assert result.sampler == "flow-match"


# =========================================================================== F-2ef1bb79 (generators)
# once _load() succeeds, nothing caught a failure inside the actual pipe(...) invocation -- it used
# to surface as a completely raw, unclassified exception.


def test_sdxl_call_time_failure_is_classified(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline", pipe_cls=_RaisingOnCallPipe)
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {}, seed=1)
    assert exc.value.code == "RUNTIME_GENERATE_FAILED"
    assert isinstance(exc.value.cause, RuntimeError)


def test_flux_call_time_failure_is_classified(monkeypatch):
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline", pipe_cls=_RaisingOnCallPipe)
    gen = FluxGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {}, seed=1)
    assert exc.value.code == "RUNTIME_GENERATE_FAILED"
    assert isinstance(exc.value.cause, RuntimeError)


def test_sdxl_happy_path_still_produces_a_real_image_file(monkeypatch, tmp_path):
    """The new wrapping try/except must not swallow the success path."""
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {}, seed=42)
    assert Path(result.image_path).exists()
    assert result.seed == 42
    assert result.generator_family == "stable-diffusion"


def test_flux_happy_path_still_produces_a_real_image_file(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    gen = FluxGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {}, seed=7)
    assert Path(result.image_path).exists()
    assert result.generator_family == "flux"


# =========================================================================== F-dd568f7f
# every verifier's lazy loader swallowed ALL exceptions into SKIPPED, conflating "the extra isn't
# installed" with "construction failed for a real reason". Only ImportError is SKIPPED now.


def test_siglip2_real_absence_still_skips_gracefully():
    """Unchanged behaviour: ai_eyes_mcp genuinely is not installed in this environment."""
    v = SigLIP2Screen()
    assert v.score("x.png", _question(CheckType.siglip2)) is None
    assert v._unavailable is True


def test_siglip2_genuine_construction_failure_raises_distinctly(monkeypatch):
    class _Raising:
        def __init__(self, model_id=None):
            raise ValueError("unrecognized model checkpoint")

    _install_fake_ai_eyes_engine(monkeypatch, _Raising)
    v = SigLIP2Screen()
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _question(CheckType.siglip2))
    assert exc.value.code == "RUNTIME_VERIFIER_INIT_FAILED"
    assert isinstance(exc.value.cause, ValueError)
    assert v._unavailable is False  # NOT masquerading as "extra not installed"


def test_vqascore_real_absence_still_skips_gracefully():
    v = VQAScoreVerifier()
    assert v.score("x.png", _question()) is None
    assert v._unavailable is True


def test_vqascore_genuine_construction_failure_raises_distinctly(monkeypatch):
    class _Raising:
        def __init__(self, model=None):
            raise ValueError("unrecognized model checkpoint")

    _install_fake_t2v_metrics(monkeypatch, _Raising)
    v = VQAScoreVerifier()
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _question())
    assert exc.value.code == "RUNTIME_VERIFIER_INIT_FAILED"
    assert v._unavailable is False


def test_dsg_real_absence_still_skips_gracefully():
    v = DSGVerifier()
    assert v.score("x.png", _question()) is None
    assert v._unavailable is True


def test_dsg_genuine_construction_failure_raises_distinctly(monkeypatch):
    class _Raising:
        def __init__(self, model=None):
            raise ValueError("unrecognized model checkpoint")

    _install_fake_t2v_metrics(monkeypatch, _Raising)
    v = DSGVerifier()
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _question())
    assert exc.value.code == "RUNTIME_VERIFIER_INIT_FAILED"
    assert v._unavailable is False


def test_identity_subgate_real_absence_still_skips_gracefully():
    g = IdentitySubGate()
    assert g.evaluate("plate.png", {"front": "f.png"}) is None
    assert g._unavailable is True


def test_identity_subgate_genuine_construction_failure_propagates_raw(monkeypatch):
    """Deliberately DIFFERENT from the other three verifiers above: the Director's standing ruling
    on identity_subgate.py permits ONLY narrowing the except clause and nothing else in that file,
    so a genuine failure propagates as whatever raw exception the engine raised rather than being
    wrapped into a PromptCraftError. See the comment on that except clause in identity_subgate.py."""

    class _Raising:
        def __init__(self):
            raise ValueError("bad ctor")

    _install_fake_ai_eyes_engine(monkeypatch, _Raising)
    g = IdentitySubGate()
    with pytest.raises(ValueError):
        g.evaluate("plate.png", {"front": "f.png"})
    assert g._unavailable is False  # not masquerading as "extra not installed" either


def test_identity_subgate_floor_and_variance_are_untouched():
    """Fence check: the Director's floor=0.55 / max_variance=0.05 must survive this pass
    byte-for-byte -- no delete, no promote, no wire, no threshold change."""
    g = IdentitySubGate()
    assert g.floor == 0.55
    assert g.max_variance == 0.05


# =========================================================================== F-2ef1bb79 (verifiers)
# once construction succeeded, nothing caught a failure inside the actual score/answer call -- it
# used to propagate as a bare, unclassified exception, indistinguishable from any other bug.


def test_siglip2_call_time_failure_is_classified(monkeypatch):
    class _Engine:
        def __init__(self, model_id=None):
            pass

        def score(self, image_path, text):
            raise RuntimeError("simulated siglip2 call-time failure")

    _install_fake_ai_eyes_engine(monkeypatch, _Engine)
    v = SigLIP2Screen()
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _question(CheckType.siglip2))
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    assert isinstance(exc.value.cause, RuntimeError)


def test_vqascore_call_time_failure_is_classified(monkeypatch):
    class _Scorer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            raise RuntimeError("simulated vqascore call-time failure")

    _install_fake_t2v_metrics(monkeypatch, _Scorer)
    v = VQAScoreVerifier()
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _question())
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    assert isinstance(exc.value.cause, RuntimeError)


def test_dsg_call_time_failure_is_classified(monkeypatch):
    class _Answerer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            raise RuntimeError("simulated dsg call-time failure")

    _install_fake_t2v_metrics(monkeypatch, _Answerer)
    v = DSGVerifier()
    with pytest.raises(PromptCraftError) as exc:
        v.score("x.png", _question())
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    assert isinstance(exc.value.cause, RuntimeError)


def test_siglip2_happy_path_still_scores_normally(monkeypatch):
    """The new wrapping try/except must not swallow the success path."""

    class _Engine:
        def __init__(self, model_id=None):
            pass

        def score(self, image_path, text):
            return 0.87

    _install_fake_ai_eyes_engine(monkeypatch, _Engine)
    v = SigLIP2Screen()
    assert v.score("x.png", _question(CheckType.siglip2)) == pytest.approx(0.87)


def test_vqascore_happy_path_still_scores_normally(monkeypatch):
    class _Scorer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            return [[0.73]]

    _install_fake_t2v_metrics(monkeypatch, _Scorer)
    v = VQAScoreVerifier()
    assert v.score("x.png", _question()) == pytest.approx(0.73)


def test_dsg_happy_path_still_scores_normally(monkeypatch):
    class _Answerer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            return [[0.91]]

    _install_fake_t2v_metrics(monkeypatch, _Answerer)
    v = DSGVerifier()
    assert v.score("x.png", _question()) == pytest.approx(0.91)


# =========================================================================== F-721a7139
# DSGVerifier's answerer_model defaults to the SAME model id VQAScoreVerifier uses, and qg_model is
# never read by scoring -- no real question decomposition happens. Real decomposition is
# feature-pass work (a pinned QG LM) out of scope for this pass; instead the shared model is
# surfaced via `shares_model_with` rather than hidden behind the distinct-looking `family` label.


def test_default_dsg_shares_the_tier1_default_model():
    dsg = DSGVerifier()
    vqa = VQAScoreVerifier()
    assert dsg.answerer_model == vqa.model_id == DEFAULT_MODEL_ID
    assert dsg.shares_model_with == vqa.verifier_id


def test_a_genuinely_distinct_answerer_model_reports_no_sharing():
    dsg = DSGVerifier(answerer_model="a-genuinely-different-qa-model")
    assert dsg.shares_model_with is None


def test_qg_model_is_stored_but_confirmed_unused_by_scoring(monkeypatch):
    """Documents the current reality rather than asserting it should be different: qg_model does
    not change what question gets asked of the answerer. If this starts failing, someone changed
    DSGVerifier to actually read qg_model -- update the shares_model_with/family story to match."""
    seen_texts: list[str] = []

    class _Answerer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            seen_texts.extend(texts)
            return [[0.5]]

    _install_fake_t2v_metrics(monkeypatch, _Answerer)
    q = _question()

    DSGVerifier(qg_model="qg-lm-alpha").score("x.png", q)
    DSGVerifier(qg_model="an-entirely-different-qg-lm").score("x.png", q)

    assert seen_texts == [q.text, q.text]  # identical single top-level claim both times


def test_dsg_family_label_is_unchanged():
    """This pass does NOT rename DSGVerifier.family away from 'dsg-qg'. Renaming it to match
    VQAScoreVerifier's 'clip-flant5' would break
    tests/test_image_plugin.py::test_image_plugin_builds_without_gpu (which asserts 'dsg-qg' is
    present) and would not even gain enforcement -- family_guard's assert_distinct_families only
    checks generator-vs-verifier, never verifier-vs-verifier. shares_model_with is the chosen fix
    instead of a family rename."""
    assert DSGVerifier().family == "dsg-qg"


# =========================================================================== suite hygiene canary


def test_no_fake_modules_leak_past_this_files_tests():
    """Every fake-module test above uses monkeypatch.setitem (auto-reverted per test), never raw
    sys.modules mutation. This is the invariant tests/test_core_is_gpu_free.py depends on; if a
    future edit here breaks that discipline, this canary should catch it before that file does."""
    assert "torch" not in sys.modules
    assert "diffusers" not in sys.modules
    assert "ai_eyes_mcp" not in sys.modules
    assert "ai_eyes_mcp.engine" not in sys.modules
    assert "t2v_metrics" not in sys.modules
