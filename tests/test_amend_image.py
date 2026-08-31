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
from pcraft.testing import write_solid_png


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


def _install_fake_pil(monkeypatch) -> None:
    # The suite must pass on a bare [dev] install: cond.open_image / mask_for_region
    # import PIL at call time, so the Fill-branch test needs PIL faked the same way
    # torch and diffusers are (coordinator fold fix: this test passed only where the
    # [image] extra happened to be installed -- CI has no PIL and refused with
    # DEP_IMAGE_MISSING, which is the door working and the test leaning on the env).
    fake_pil = types.ModuleType("PIL")
    fake_image = types.ModuleType("PIL.Image")
    fake_draw = types.ModuleType("PIL.ImageDraw")

    class _Img:
        def __init__(self, mode="RGB", size=(64, 64), color=0):
            self.mode = mode
            self.size = size
            self.color = color

        def save(self, path):
            Path(path).write_bytes(b"fake-png")

    fake_image.open = lambda path: _Img()
    fake_image.new = lambda mode, size, color=0: _Img(mode, size, color)

    class _Draw:
        def __init__(self, img):
            self.img = img

        def rectangle(self, box, fill=0):
            pass

    fake_draw.Draw = _Draw
    fake_pil.Image = fake_image
    fake_pil.ImageDraw = fake_draw
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", fake_draw)


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


def _stub_sdxl_load(monkeypatch):
    """Reach _load without a live pipeline. [image] may be installed; this suite stays GPU-free."""

    def boom(self, kind="base"):
        raise PromptCraftError("DEP_IMAGE_MISSING", "test stub — do not load a pipeline")

    monkeypatch.setattr(SDXLGenerator, "_load", boom)


def test_sdxl_allows_empty_pose_and_identity_lists(monkeypatch):
    """_assemble_conditioning() (core/loop/orchestrate.py) always includes both keys, often as [].
    An empty list means 'not requested', not 'requested and unsupported' -- it must fall through to
    _load(), not be refused. The next coded error is DEP_IMAGE_MISSING (stubbed here so a live
    [image] extra cannot fire a 30-step generate) -- never GATE_CONDITIONING_UNSUPPORTED."""
    _stub_sdxl_load(monkeypatch)
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"pose_refs": [], "identity_refs": []}, seed=1)
    assert exc.value.code == "DEP_IMAGE_MISSING"


def test_sdxl_allows_conditioning_with_no_pose_or_identity_keys_at_all(monkeypatch):
    _stub_sdxl_load(monkeypatch)
    gen = SDXLGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {}, seed=1)
    assert exc.value.code == "DEP_IMAGE_MISSING"


def test_flux_refuses_nonempty_pose_refs(tmp_path):
    pose = write_solid_png(tmp_path / "front.openpose.png")
    gen = FluxGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"pose_refs": [str(pose)]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"


def test_flux_refuses_nonempty_identity_refs(tmp_path):
    plate = write_solid_png(tmp_path / "ref.png")
    gen = FluxGenerator()
    with pytest.raises(PromptCraftError) as exc:
        gen.generate("p", "n", {"identity_refs": [{"plate": str(plate), "method": "ip_adapter"}]}, seed=1)
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


def test_flux_sampler_names_itself_as_the_pipeline_default(monkeypatch, tmp_path):
    """F-4409b547 named SDXLGenerator specifically and this pin deliberately left FluxGenerator's
    hardcoded 'flow-match' alone as a flat assertion. F-cd07fe00 is the conscious change that pin
    was waiting for: 'flow-match' is accurate only because nothing here ever configures a scheduler,
    which is exactly the fact the SDXL receipt spells out and the Flux receipt did not. FluxGenerator
    still has no `sampler` constructor param (nothing for a caller to request), so the honest stamp
    is "this is the checkpoint default", not "this algorithm was chosen"."""
    import inspect

    assert "sampler" not in inspect.signature(FluxGenerator.__init__).parameters

    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    gen = FluxGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {}, seed=1)
    assert result.sampler.startswith("flow-match")
    assert "default" in result.sampler


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


# =========================================================================== F-721a7139 / F-IMG-FEAT-005
# Answerer still defaults to the Tier-1 VQAScore model; that sharing stays on
# shares_model_with. Decomposition is real now (template QG / injected qg).


def test_default_dsg_shares_the_tier1_default_model():
    dsg = DSGVerifier()
    vqa = VQAScoreVerifier()
    assert dsg.answerer_model == vqa.model_id == DEFAULT_MODEL_ID
    assert dsg.shares_model_with == vqa.verifier_id


def test_a_genuinely_distinct_answerer_model_reports_no_sharing():
    dsg = DSGVerifier(answerer_model="a-genuinely-different-qa-model")
    assert dsg.shares_model_with is None


def test_qg_slot_is_read_by_scoring(monkeypatch):
    """F-IMG-FEAT-005: qg_model used to be stored and ignored. The QG slot now
    expands the atom. An injected qg is what the answerer sees."""
    from pcraft.domains.image.verifier.dsg_expand import SubProbe

    seen_texts: list[str] = []

    class _Answerer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            seen_texts.extend(texts)
            return [[0.5]]

    _install_fake_t2v_metrics(monkeypatch, _Answerer)
    q = _question()

    def qg(_question):
        return [SubProbe(id="one", text="Does this image show the QG probe?", kind="entity")]

    DSGVerifier(qg_model="test-qg", qg=qg).score("x.png", q)
    assert seen_texts == ["Does this image show the QG probe?"]


def test_dsg_family_label_is_unchanged():
    """This pass does NOT rename DSGVerifier.family away from 'dsg-qg'. Renaming it to match
    VQAScoreVerifier's 'clip-flant5' would break
    tests/test_image_plugin.py::test_image_plugin_builds_without_gpu (which asserts 'dsg-qg' is
    present) and would not even gain enforcement -- family_guard's assert_distinct_families only
    checks generator-vs-verifier, never verifier-vs-verifier. shares_model_with is the chosen fix
    instead of a family rename."""
    assert DSGVerifier().family == "dsg-qg"


# ================================================ F-916e73b6 / F-43da2300 (identity lock honesty)
# One defect family: a plate can be stamped on the receipt as a bound identity lock that no
# generator ever applied.
#
# F-916e73b6 -- _UNIMPLEMENTED_METHODS was an EMPTY frozenset, so refuse_unimplemented_identity()
# was a structurally dead refusal: an unrecognised method ('ip-adapter', 'pulid', ...) passed the
# bare-`str` contract field, was resolved and existence-checked by bind_refs, then dropped by every
# method-specific accessor -- while the receipt still carried the resolved absolute plate path. The
# deny-list is now an allow-list.
#
# F-43da2300 -- reference_lock.assemble() bucketed by `scope` alone, so method=none (documented in
# conditioning.py as a skip) was promoted into lock.identity and became THE Kontext stitch identity,
# shadowing the real method=reference plate purely by list order.


def _stub_flux_load(monkeypatch):
    """Same containment as _stub_sdxl_load: no pipeline, no weights, no GPU."""

    def boom(self, kind="base"):
        raise PromptCraftError("DEP_IMAGE_MISSING", "test stub — do not load a pipeline")

    monkeypatch.setattr(FluxGenerator, "_load", boom)


@pytest.mark.parametrize("method", ["ip-adapter", "ipadapter", "pulid", "faceid", "IP_Adapter"])
def test_sdxl_refuses_an_unrecognised_identity_method(monkeypatch, tmp_path, method):
    """The measured shape: SDXL.generate() SUCCEEDED with method='ip-adapter' and returned a
    receipt whose conditioning.identity_refs carried the resolved plate, while applied.ip_adapter
    was []. It must refuse by name instead."""
    _stub_sdxl_load(monkeypatch)
    plate = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        SDXLGenerator(out_dir=tmp_path / "out").generate(
            "p", "n", {"identity_refs": [{"plate": str(plate), "method": method}]}, seed=1
        )
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert method in exc.value.message


@pytest.mark.parametrize("method", ["ip-adapter", "pulid"])
def test_flux_refuses_an_unrecognised_identity_method(monkeypatch, tmp_path, method):
    _stub_flux_load(monkeypatch)
    plate = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator(out_dir=tmp_path / "out").generate(
            "p", "n", {"identity_refs": [{"plate": str(plate), "method": method}]}, seed=1
        )
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert method in exc.value.message


@pytest.mark.parametrize("method", ["ip_adapter", "reference", "lora", "instantid", "none"])
def test_the_five_named_methods_are_not_refused_as_unsupported(tmp_path, method):
    """The allow-list must not over-refuse. This is the guard on the inversion itself."""
    from pcraft.domains.image.generator import conditioning as cond

    plate = write_solid_png(tmp_path / "face.png")
    conditioning = {"identity_refs": [{"plate": str(plate), "method": method}]}
    assert cond.unsupported_identity_methods(conditioning) == []
    cond.refuse_unimplemented_identity("sdxl.base-1.0.v1", conditioning)  # no raise


def test_method_none_never_lands_in_the_reference_lock(tmp_path):
    """MEASURED before the fix: assemble() returned lock.identity == [<the method=none plate>].
    method=none is documented as a skip; a skipped plate is not an identity lock."""
    from pcraft.domains.image.generator.reference_lock import assemble

    disabled = write_solid_png(tmp_path / "disabled.png")
    real = write_solid_png(tmp_path / "real.png")
    lock = assemble(
        {
            "pose_refs": [str(write_solid_png(tmp_path / "pose.openpose.png"))],
            "identity_refs": [
                {"plate": str(disabled), "method": "none", "scope": "face"},
                {"plate": str(real), "method": "reference", "scope": "face"},
            ],
        }
    )
    assert str(disabled) not in lock.all_paths()
    assert lock.identity == [str(real)]


def test_a_ghost_method_none_plate_is_never_stitched_into_the_cloud_graph(tmp_path):
    """The full measured chain: bind_refs deliberately does not resolve a skip-method plate, so a
    path that does NOT exist escaped GATE_CONDITIONING_REF_MISSING, was bucketed by scope, and then
    became the ImageStitch identity LoadImage of an emitted Cloud graph. Dropped is the fix; a
    disabled plate must never reach the graph."""
    from pcraft.domains.image.generator import kontext_fill

    real = write_solid_png(tmp_path / "ashen-reaver-front.png")
    pose = write_solid_png(tmp_path / "two-hand.openpose.png")
    graph, report = kontext_fill.from_conditioning(
        {
            "pose_refs": [str(pose)],
            "identity_refs": [
                {"plate": "does/not/exist/ghost-plate.png", "method": "none", "scope": "face"},
                {"plate": str(real), "method": "reference", "scope": "face"},
            ],
        }
    )
    loaded = {n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"}
    assert "ghost-plate.png" not in loaded
    assert "ghost-plate" not in report.identity
    assert report.identity == str(real)


def test_assemble_refuses_an_unrecognised_method_rather_than_bucketing_it(tmp_path):
    """assemble() honours method or refuses. It must not silently bucket by scope alone."""
    from pcraft.domains.image.generator.reference_lock import assemble

    plate = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        assemble({"identity_refs": [{"plate": str(plate), "method": "pulid", "scope": "face"}]})
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "pulid" in exc.value.message


def test_flux_refuses_a_wrong_family_lock_before_it_writes_a_recipe(tmp_path):
    """Ordering half of F-43da2300: flux_generator tested reference_refs BEFORE calling
    refuse_unmeasured_family, so a conditioning carrying BOTH a reference ref and an ip_adapter ref
    wrote the Cloud recipe and raised GATE_CLOUD_SUBMIT without ever refusing the wrong-family
    lock. No recipe file may exist after the refusal."""
    out = tmp_path / "out"
    identity = write_solid_png(tmp_path / "face.png")
    costume = write_solid_png(tmp_path / "costume.png")
    pose = write_solid_png(tmp_path / "pose.openpose.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator(out_dir=out).generate(
            "p",
            "n",
            {
                "pose_refs": [str(pose)],
                "identity_refs": [
                    {"plate": str(identity), "method": "reference", "scope": "face"},
                    {"plate": str(costume), "method": "ip_adapter", "scope": "costume"},
                ],
            },
            seed=1,
        )
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "ip_adapter" in exc.value.message
    assert not list(out.glob("*.json")), "a recipe was written before the wrong-family refusal"


# ============================================== F-cd07fe00 (the discarded negative prompt)
# FluxGenerator.generate() accepts negative_prompt and builds its call dict as
# {prompt, num_inference_steps, generator} -- the negative is never referenced again, with nothing
# on the receipt saying so. Dropping it is CORRECT for the model (rules/encoder_craft.md:843: on
# FLUX-dev/schnell negatives are ignored), so this is a receipt-honesty gap, not a wrong render.
# The tell is the asymmetry with sdxl_generator, which goes to deliberate lengths to stamp
# "requested, NOT applied" for exactly this situation. Upstream the negative is not vestigial:
# core/synth/signature.py builds it by joining every must_not claim and cli/__init__.py PRINTS it,
# so a Flux run showed the operator a negative composed of their must_not claims that the pipeline
# never received.


def test_flux_records_the_negative_prompt_it_discards(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch, cuda_available=False)
    captured = _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    gen = FluxGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "no tusks, no crimson sash", {}, seed=1)

    # Dropping it stays correct -- this is not a request to start passing it.
    assert "negative_prompt" not in captured["pipe"].call_kwargs
    dropped = result.conditioning["applied"]["negative_prompt"]
    assert dropped["requested"] == "no tusks, no crimson sash"
    assert dropped["applied"] is False
    assert dropped["reason"]


def test_flux_records_the_drop_on_the_fill_branch_too(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_pil(monkeypatch)
    captured = _install_fake_diffusers(monkeypatch, pipeline_attr="FluxFillPipeline")
    src = write_solid_png(tmp_path / "prev.png")
    gen = FluxGenerator(out_dir=tmp_path / "out")
    result = gen.generate(
        "p", "no bracer damage", {"inpaint_from": str(src), "inpaint_region": "fist"}, seed=2
    )
    assert "negative_prompt" not in captured["pipe"].call_kwargs
    assert result.conditioning["applied"]["negative_prompt"]["applied"] is False


def test_flux_does_not_stamp_a_negative_it_was_never_given(monkeypatch, tmp_path):
    """An empty negative is not a drop. The receipt records the drop, not a ceremony."""
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="FluxPipeline")
    result = FluxGenerator(out_dir=tmp_path / "out").generate("p", "", {}, seed=3)
    assert result.conditioning["applied"]["negative_prompt"] is None


def test_flux_method_reference_still_raises_cloud_submit(tmp_path):
    """Established fact, pinned so the ordering fix above cannot regress it: a clean
    method=reference conditioning still writes the recipe and refuses with GATE_CLOUD_SUBMIT --
    the pose map it carries is the recipe's own input, not an SDXL ControlNet request."""
    out = tmp_path / "out"
    identity = write_solid_png(tmp_path / "face.png")
    pose = write_solid_png(tmp_path / "pose.openpose.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator(out_dir=out).generate(
            "p",
            "n",
            {
                "pose_refs": [str(pose)],
                "identity_refs": [{"plate": str(identity), "method": "reference", "scope": "face"}],
            },
            seed=1,
        )
    assert exc.value.code == "GATE_CLOUD_SUBMIT"
    assert (out / "flux.kontext-stitch-crop-fill.v1.json").is_file()


# =========================================================================== suite hygiene canary


def test_no_fake_modules_leak_past_this_files_tests():
    """Every fake-module test above uses monkeypatch.setitem (auto-reverted per test), never raw
    sys.modules mutation. [image] may now be installed, so torch/diffusers can be present —
    they must be the real packages, not a leftover ModuleType stand-in."""
    for name in ("torch", "diffusers"):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        assert getattr(mod, "__file__", None), f"{name} leaked as a fake ModuleType"
    assert "ai_eyes_mcp" not in sys.modules
    assert "ai_eyes_mcp.engine" not in sys.modules
    assert "t2v_metrics" not in sys.modules
