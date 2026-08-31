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
from pcraft.domains.image.verifier.palette_verifier import PaletteVerifier, Tier0Router
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


# ======================================================= wave 8 (health-amend-c) -- Stage C polish
# Four observability/receipt findings and one wording fix, all inside this domain. Nothing here
# moves a score, a band, or a zone: every assertion below is about what the operator can READ back
# off an instrument that already computed the answer and then dropped it.


def _palette_q(enum: list[str], atom_id: str = "palette") -> Question:
    return Question(
        atom_id=atom_id,
        text="Does this image match the faction palette?",
        check_type=CheckType.palette,
        polarity=Polarity.affirm,
        severity=Severity.required,
        enum=enum,
    )


# --------------------------------------------------------------------------------- F-1675985a
# PaletteVerifier.score computed `hits = [_presence(pixels, rgb) for rgb in colours]` and then
# collapsed it into `round(sum(hits) / len(hits), 4)`, retaining nothing. On the shipped
# example.faction.contract.json enum (`['#3a3a3a','#d9d4c8','#7a1f1f']`, hand-written) a 0.3333 FAIL
# could equally mean "all three partially present" or "one present, two entirely absent" -- and the
# reason string it renders through is the bare 'score 0.3333 -> FAIL (band palette)', naming no
# colour. This is the ONE verifier in the domain with no model and no GPU, i.e. the one case where
# an exact answer to "what is missing" is computable -- and it was computed, then discarded.


def test_palette_names_which_colour_is_absent_not_only_the_mean(tmp_path):
    ash = write_solid_png(tmp_path / "ash.png", (58, 58, 58))  # exactly #3a3a3a
    v = PaletteVerifier()
    score = v.score(str(ash), _palette_q(["#3a3a3a", "#d9d4c8", "#7a1f1f"]))
    assert score == pytest.approx(0.3333)
    breakdown = v.last_breakdown
    assert breakdown is not None, "the per-colour hit vector is computed and then thrown away"
    # Echoed as AUTHORED, for the same reason CONTRACT_PALETTE_ENUM_MIXED echoes the written
    # members: the operator has to find these strings in the contract.
    assert [entry["hex"] for entry in breakdown] == ["#3a3a3a", "#d9d4c8", "#7a1f1f"]
    assert breakdown[0]["hit"] == pytest.approx(1.0)
    assert breakdown[1]["hit"] == pytest.approx(0.0)
    assert breakdown[2]["hit"] == pytest.approx(0.0)
    detail = v.breakdown_detail()
    assert detail is not None
    assert "#d9d4c8" in detail and "#7a1f1f" in detail
    assert "absent" in detail


def test_the_palette_breakdown_leaves_the_aggregate_score_untouched(tmp_path):
    """Band semantics must not move. The breakdown is an ADDITIONAL answer beside the mean, never
    a second number: palette high=0.85/low=0.50 grades exactly what it graded before."""
    ash = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    q = _palette_q(["#3a3a3a", "#d9d4c8", "#7a1f1f"])
    assert PaletteVerifier().score(str(ash), q) == pytest.approx(0.3333)
    blood = write_solid_png(tmp_path / "blood.png", (122, 31, 31))  # exactly #7a1f1f
    only = PaletteVerifier()
    assert only.score(str(blood), _palette_q(["#7a1f1f"])) == pytest.approx(1.0)
    assert "absent" not in (only.breakdown_detail() or "")


def test_the_router_never_reports_a_stale_palette_breakdown(tmp_path):
    """last_delegate's own lesson (F-64b4f422): a value left over from the PREVIOUS atom is worse
    than no value. A siglip2 atom never touches the histogram, so the router must not still be
    holding the colours of the palette atom before it."""
    ash = write_solid_png(tmp_path / "ash.png", (58, 58, 58))
    router = Tier0Router()
    router.score(str(ash), _palette_q(["#3a3a3a", "#7a1f1f"]))
    assert router.last_breakdown is not None
    router.score(str(ash), _question(CheckType.siglip2))
    assert router.last_breakdown is None
    assert router.score_detail() is None


# --------------------------------------------------------------------------------- F-1d5992bd
# The palette verifier's own RUNTIME_VERIFIER_CALL_FAILED carried no inline hint, unlike its three
# model-backed siblings (VQAScoreVerifier.score, SigLIP2Screen.score, DSGVerifier._ask), whose hints
# all name "CUDA OOM mid-run". This is the one Tier-0 delegate whose module docstring opens "No
# model, no GPU", so that wording is not merely unhelpful here, it is wrong.


def test_the_palette_read_failure_hint_does_not_blame_a_gpu_it_does_not_have(tmp_path):
    v = PaletteVerifier()
    with pytest.raises(PromptCraftError) as exc:
        v.score(str(tmp_path / "gone.png"), _palette_q(["#3a3a3a"]))
    assert exc.value.code == "RUNTIME_VERIFIER_CALL_FAILED"
    hint = exc.value.hint or ""
    assert hint, "the one raise in this verifier family with no inline hint"
    assert "no gpu" in hint.lower()
    assert "cuda oom mid-run" not in hint.lower()  # the model-backed siblings' words, wrong here


# --------------------------------------------------------------------------------- F-60b76831
# SDXL's receipt said which identity locks FIRED and nothing at all about the ones that did not. A
# method=none ref -- a documented skip (conditioning._SKIP_METHODS) -- simply never appeared in any
# applied[...] sub-list, so an operator had to diff the request against the result by hand and still
# could not tell an intentional skip from a bug. Both siblings in this file family already answer
# this: flux_generator stamps applied["negative_prompt"] = {requested, applied: False, reason} and
# kontext_fill.RecipeReport carries identity_unchosen.


def test_sdxl_receipt_names_the_identity_lock_it_skipped(monkeypatch, tmp_path):
    """The untested shape: one method=none ref MIXED with a ref that does apply."""
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    _install_fake_pil(monkeypatch)
    plate = write_solid_png(tmp_path / "face.png")
    ghost = tmp_path / "inherited.png"  # never resolved: bind_refs does not touch a skip method
    result = SDXLGenerator(out_dir=tmp_path / "out").generate(
        "p",
        "n",
        {
            "identity_refs": [
                {"plate": str(ghost), "method": "none", "scope": "face"},
                {"plate": str(plate), "method": "ip_adapter", "scope": "face"},
            ]
        },
        seed=5,
    )
    applied = result.conditioning["applied"]
    assert [entry["plate"] for entry in applied["ip_adapter"]] == [str(plate)]
    skipped = applied["identity_skipped"]
    assert [entry["plate"] for entry in skipped] == [str(ghost)]
    assert skipped[0]["method"] == "none"
    assert skipped[0]["applied"] is False
    assert "none" in skipped[0]["reason"]


def test_sdxl_stamps_an_empty_skip_list_when_every_lock_applied(monkeypatch, tmp_path):
    """The field is always present, like its pose/ip_adapter/lora/instantid siblings in the same
    dict -- absence of a key is exactly the silence this fix removes."""
    _install_fake_torch(monkeypatch, cuda_available=False)
    _install_fake_diffusers(monkeypatch, pipeline_attr="StableDiffusionXLPipeline")
    _install_fake_pil(monkeypatch)
    plate = write_solid_png(tmp_path / "face.png")
    result = SDXLGenerator(out_dir=tmp_path / "out").generate(
        "p",
        "n",
        {"identity_refs": [{"plate": str(plate), "method": "ip_adapter", "scope": "face"}]},
        seed=6,
    )
    assert result.conditioning["applied"]["identity_skipped"] == []


# --------------------------------------------------------------------------------- F-65fe58d5
# DSGVerifier.score builds the full entity/attribute/relation trail on every call and parks it on
# last_expansion -- and a grep of the worktree showed the ONLY readers anywhere were this suite.
# Same shape as F-64b4f422 on the router's last_delegate: a field that looks live, with tests
# asserting the field rather than the behaviour.


def test_dsg_can_say_which_probe_went_na_not_only_the_mean(monkeypatch):
    class _Answerer:
        def __init__(self, model=None):
            pass

        def __call__(self, images, texts):
            # entity absent -> its dependents are N/A, which is the localization DSG exists for
            return [[0.10]] if "tabard" in texts[0] else [[0.99]]

    _install_fake_t2v_metrics(monkeypatch, _Answerer)
    v = DSGVerifier()
    assert v.score("x.png", _question()) is not None
    summary = v.expansion_summary()
    assert summary, "last_expansion still has no reader in src/"
    assert {row["kind"] for row in summary} >= {"entity", "attribute"}
    na = [row for row in summary if row["score"] is None]
    assert na, "the attribute probe goes N/A when the entity is absent"
    detail = v.localization_detail()
    assert detail is not None
    assert na[0]["id"] in detail


def test_dsg_has_nothing_to_localize_before_it_has_scored():
    assert DSGVerifier().expansion_summary() == []
    assert DSGVerifier().localization_detail() is None


# --------------------------------------------------------------------------------- F-de4136eb
# reference_lock's refusal said "cannot bucket identity method(s)" -- this module's own internal
# vocabulary -- for what is, from the operator's side, the identical authoring mistake that
# conditioning.refuse_unimplemented_identity reports as "{who} cannot apply identity method(s)".


def test_reference_lock_refuses_in_the_operators_words_not_its_own_buckets(tmp_path):
    from pcraft.domains.image.generator.reference_lock import RECIPE_GENERATOR_ID, assemble

    plate = write_solid_png(tmp_path / "face.png")
    with pytest.raises(PromptCraftError) as exc:
        assemble({"identity_refs": [{"plate": str(plate), "method": "pulid", "scope": "face"}]})
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "cannot apply" in exc.value.message
    assert "bucket" not in exc.value.message
    assert RECIPE_GENERATOR_ID in exc.value.message  # the same door FluxGenerator guards
    assert "pulid" in exc.value.message


# =========================== F-a6acaab1 -- user-facing text in this domain must survive cp437
#
# Family-of-call-sites sibling of the em-dash crash the cli-ux, core-gate-loop and contract agents
# closed in their own files; this is the image domain's share of the same family. A structured
# refusal is worth nothing if PRINTING it raises: `_emit` writes message and hint to stdout, and a
# classic cmd.exe console is cp437, which has no U+2026. The refusal then dies as a
# UnicodeEncodeError -- a clean exit-2 diagnosis turned into a traceback, at the exact moment the
# operator is trying to read what to do next.
#
# One live literal in this domain carried a non-ASCII character: flux_generator.py's
# GATE_CLOUD_SUBMIT hint ("pcraft recipe --image-name U+2026"), which is raised on the reference
# path -- the shipped Cloud-recipe route, not a corner case.
#
# The sweep covers whole files rather than a hand-picked list, because which text is user-facing is
# not a stable property of where that text sits.

_CONSOLE_ENCODING = "cp437"

_OWNED_SOURCE_GLOBS = ("domains/**/*.py",)


def _owned_sources():
    import pcraft

    root = Path(pcraft.__file__).parent
    found: list[Path] = []
    for pattern in _OWNED_SOURCE_GLOBS:
        found.extend(sorted(root.glob(pattern)))
    assert found, "owned-source globs matched nothing; the fixture is broken, not the code"
    return found


def _string_constants_under(node) -> list[str]:
    """Every str literal beneath a node, f-string fragments included."""
    import ast

    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _user_facing_literals(path: Path) -> list[tuple[str, str]]:
    """(where, text) for every refusal message/hint literal in one owned source file."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        # every string inside a PromptCraftError(...) construction: code, message, hint
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "PromptCraftError":
                where = f"{path.name}:{node.lineno} PromptCraftError"
                out.extend((where, text) for text in _string_constants_under(node))
        # and every module-level hint constant those calls point at by name
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("_HINT"):
                    where = f"{path.name}:{node.lineno} {target.id}"
                    out.extend((where, text) for text in _string_constants_under(node.value))
    return out


def test_every_refusal_message_and_hint_in_this_domain_encodes_on_a_cp437_console():
    offenders = []
    scanned = 0
    for path in _owned_sources():
        for where, text in _user_facing_literals(path):
            scanned += 1
            try:
                text.encode(_CONSOLE_ENCODING, errors="strict")
            except UnicodeEncodeError as err:
                offenders.append(f"{where}: {err.reason} at {text[err.start : err.end]!r}")
    assert scanned, "the AST sweep found no refusal literals at all -- the pattern has drifted"
    assert not offenders, "user-facing text that a cp437 console cannot print:\n" + "\n".join(
        offenders
    )


def test_the_cloud_submit_refusal_renders_on_a_cp437_console(tmp_path, monkeypatch):
    """End to end through the real object: to_safe_text() is what `_emit` hands to the console, and
    this is the refusal the shipped reference path raises every time it writes a recipe."""
    identity = write_solid_png(tmp_path / "face.png")
    pose = write_solid_png(tmp_path / "two-hand.openpose.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator(out_dir=tmp_path / "out").generate(
            "p",
            "n",
            {
                "pose_refs": [str(pose)],
                "identity_refs": [{"plate": str(identity), "method": "reference", "scope": "face"}],
            },
            seed=1,
        )
    assert exc.value.code == "GATE_CLOUD_SUBMIT"
    exc.value.to_safe_text().encode(_CONSOLE_ENCODING, errors="strict")


# =========================================================================== suite hygiene canary


# F-56f08800: the hotfix that added _install_fake_pil did not add PIL to the canary that exists to
# catch exactly a faked module leaking. The tuple below iterated only ('torch', 'diffusers'), so a
# raw sys.modules mutation of PIL -- or a fake outliving its test -- would have silently poisoned
# every later test that reads an image, including the palette verifier's Pillow branch, with no
# signal at all. The gap was latent rather than live (the helper uses monkeypatch.setitem like its
# siblings, so it is auto-reverted), which is precisely why it could sit there unnoticed.
#
# Two lists rather than one tuple, because the two groups are checked differently: the first may
# legitimately be installed for real, the second is never installed in this environment and so must
# be absent outright. test_the_canary_watches_every_module_this_file_fakes below keeps both in step
# with the _install_fake_* helpers automatically, so the next helper cannot repeat this.
_FAKED_MAY_BE_REAL = ("torch", "diffusers", "PIL", "PIL.Image", "PIL.ImageDraw")
_FAKED_NEVER_INSTALLED = ("ai_eyes_mcp", "ai_eyes_mcp.engine", "t2v_metrics")


def test_no_fake_modules_leak_past_this_files_tests():
    """Every fake-module test above uses monkeypatch.setitem (auto-reverted per test), never raw
    sys.modules mutation. [image] may now be installed, so torch/diffusers/PIL can be present —
    they must be the real packages, not a leftover ModuleType stand-in."""
    for name in _FAKED_MAY_BE_REAL:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        assert getattr(mod, "__file__", None), f"{name} leaked as a fake ModuleType"
    for name in _FAKED_NEVER_INSTALLED:
        assert name not in sys.modules


def test_the_canary_catches_a_leaked_fake_pil(monkeypatch):
    """The canary's own coverage, measured rather than assumed: with a fake PIL in sys.modules it
    must FAIL. Before PIL was added to the watch list this passed happily, which is the whole
    defect -- a canary that does not sing for one of the three modules its file fakes."""
    _install_fake_pil(monkeypatch)
    with pytest.raises(AssertionError, match="PIL"):
        test_no_fake_modules_leak_past_this_files_tests()


def test_the_canary_watches_every_module_this_file_fakes():
    """Keeps the watch lists in step with the _install_fake_* helpers by construction. The stale
    tuple was a maintenance gap, so the fix is one that cannot go stale: every module name this
    file hands to monkeypatch.setitem(sys.modules, ...) must appear in a watch list."""
    import re

    source = Path(__file__).read_text(encoding="utf-8")
    faked = set(re.findall(r'setitem\(\s*sys\.modules,\s*"([^"]+)"', source))
    watched = set(_FAKED_MAY_BE_REAL) | set(_FAKED_NEVER_INSTALLED)
    assert faked, "the scan found no fake-module installs at all -- the pattern has drifted"
    assert faked <= watched, f"faked but unwatched: {sorted(faked - watched)}"


# ============================================================ F-37f8764e (a real-canon front door)
# Every contract this product ships is labelled, in its own `_note`, "GENERIC EXAMPLE -- invented
# for the scaffold, NOT real game canon". The gap between that and a studio binding REAL canon is
# entirely manual: hand-write JSON with atom ids, claims, check_type per atom, severity per atom,
# depends_on edges, spatial.kind/ref, identity_ref (plate + method + weight + scope) and hex enum
# members -- and get the inheritance shape right. MEASURED, the CLI is synth | gate | bind | list |
# validate | demo | replay | doctor | schema | recipe | compile | sync-rules: `schema` emits a
# validator and `validate` refuses a bad file, so the front door for the product's own core
# artifact is a blank file. Half of the scaffold can be MEASURED rather than guessed --
# palette_verifier.load_rgb is deterministic, GPU-free, and already knows which colours are in a
# plate, which is exactly the enum an author would otherwise eyeball out of an image editor.
#
# The content-awareness is MAPPING DECLARED TRAITS TO ATOMS. Nothing here looks at a plate to
# decide what is in it; the only pixels read are a colour histogram.


def _plate_png(path, colours, size: int = 60):
    """A plate of equal horizontal bands -- write_solid_png cannot express a palette."""
    import struct
    import zlib

    band = size // len(colours)
    rows = []
    for y in range(size):
        rgb = colours[min(y // band, len(colours) - 1)]
        rows.append(bytes([0]) + bytes(rgb) * size)

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    blob = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return p


_ASH, _BONE, _BLOOD = (58, 58, 58), (217, 212, 200), (122, 31, 31)


def _sheet(tmp_path, **overrides):
    """A reference sheet: a directory of plates plus one small JSON of NAMED traits."""
    import json

    root = tmp_path / "sheet"
    costume = _plate_png(root / "plates" / "costume.png", [_ASH, _BONE, _BLOOD])
    face = _plate_png(root / "plates" / "face.png", [_ASH, _BLOOD])
    body = {
        "faction": "ashen-pact",
        "character": "ashen-reaver",
        "faction_plate": "plates/costume.png",
        "character_plate": "plates/face.png",
        "traits": [
            {"id": "tabard", "kind": "costume", "scope": "faction"},
            {"id": "sigil", "kind": "insignia", "scope": "faction", "depends_on": "tabard"},
            {"id": "palette", "kind": "palette", "scope": "faction", "plate": "plates/costume.png"},
            {"id": "face", "kind": "face", "claim": "a visible orcish face with tusks"},
            {"id": "gait", "kind": "trait"},
        ],
        "drift_cues": ["a smooth human face", "a shield"],
    }
    body.update(overrides)
    path = root / "sheet.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert costume.is_file() and face.is_file()
    return path


def _scaffold(tmp_path, out=None, **overrides):
    from pcraft.domains.image.scaffold import scaffold_from_reference_sheet

    return scaffold_from_reference_sheet(
        _sheet(tmp_path, **overrides), contracts_dir=out or (tmp_path / "contracts")
    )


def test_the_scaffold_emits_both_halves_and_they_load_back_through_the_loader(tmp_path):
    """Emit BOTH, and prove it by the only means that counts: re-read the written files through
    the SAME ContractStore/_read_contract/resolve() path a hand-written pair goes through. A
    scaffold whose output does not load is worse than a blank file."""
    from pcraft.core.contract.loader import ContractStore

    result = _scaffold(tmp_path)
    assert result.faction_path.is_file() and result.character_path.is_file()
    store = ContractStore([tmp_path / "contracts"])
    assert store.ids() == ["char:ashen-reaver", "faction:ashen-pact"]
    resolved = store.resolve("char:ashen-reaver")
    assert resolved.lineage == ["faction:ashen-pact", "char:ashen-reaver"]
    ids = [a.id for a in resolved.must_have]
    assert ids == ["tabard", "sigil", "palette", "face", "gait"], "faction atoms first, then the child"
    assert [m.id for m in resolved.must_not] == ["no_smooth_human_face", "no_shield"]
    assert len(resolved.identity_refs) == 2, "the faction costume plate composes with the face plate"


def test_a_seeded_atom_is_visibly_a_stub_and_never_required(tmp_path):
    """MUST NOT BREAK. A scaffold that emits `severity: required` on an atom nobody reviewed
    manufactures a gate nobody authored -- the exact failure this whole package exists to catch.
    And a claim the author did not write is a claim the gate would then enforce."""
    from pcraft.core.contract.loader import ContractStore

    result = _scaffold(tmp_path)
    resolved = ContractStore([tmp_path / "contracts"]).resolve("char:ashen-reaver")
    assert not resolved.required_atoms(), "nothing an author has not reviewed may block a bind"
    stubs = {a.id: a for a in resolved.must_have}
    assert stubs["gait"].claim.startswith("TODO"), "an unwritten claim says so in its own text"
    assert stubs["face"].claim == "a visible orcish face with tusks", "an authored claim is verbatim"
    assert set(result.stub_atom_ids) == {"tabard", "sigil", "palette", "gait"}


def test_the_stub_shows_the_shape_rather_than_making_the_author_discover_it(tmp_path):
    """`spatial` and `depends_on` are emitted present-but-empty on a stub with nothing to say, so
    the fields are visible in the file instead of being found in the JSON Schema."""
    import json

    _scaffold(tmp_path)
    data = json.loads((tmp_path / "contracts" / "characters" / "ashen-reaver.character.contract.json").read_text(encoding="utf-8"))
    gait = next(a for a in data["must_have"] if a["id"] == "gait")
    assert "spatial" in gait and gait["spatial"] is None
    assert "depends_on" in gait and gait["depends_on"] is None


def test_each_trait_kind_gets_the_image_domains_own_defaults(tmp_path):
    """THE CONTENT-AWARENESS: a declared trait KIND maps to a check_type and to the window that
    kind lives in. `insignia` is chest-center because that is where a sigil goes -- the same names
    conditioning.region_box knows, so a scaffolded region is one the gate can actually check."""
    from pcraft.core.contract.loader import ContractStore

    _scaffold(tmp_path)
    atoms = {a.id: a for a in ContractStore([tmp_path / "contracts"]).resolve("char:ashen-reaver").must_have}
    assert atoms["tabard"].check_type.value == "vqa"
    assert atoms["tabard"].spatial.ref == "torso"
    assert atoms["sigil"].spatial.ref == "chest-center"
    assert atoms["sigil"].depends_on == "tabard", "a declared edge survives into the DAG"
    assert atoms["face"].spatial.ref == "head"
    assert atoms["palette"].check_type.value == "palette"
    assert atoms["palette"].spatial is None, "a palette atom's window is a separate decision"
    assert atoms["gait"].spatial is None


def test_the_palette_enum_is_measured_from_the_plate_and_the_verifier_accepts_it(tmp_path):
    """The half that can be MEASURED rather than guessed. And the measurement is worthless if the
    verifier that will read it refuses the text: an emitted '#00FF00' is not '#00ff00' to the text
    search `_written_hex` exists to serve, so the emitted members round-trip _colours_or_refuse."""
    from pcraft.core.contract.loader import ContractStore
    from pcraft.domains.image.verifier.palette_verifier import _colours_or_refuse

    result = _scaffold(tmp_path)
    atoms = {a.id: a for a in ContractStore([tmp_path / "contracts"]).resolve("char:ashen-reaver").must_have}
    enum = atoms["palette"].enum
    assert set(enum) == {"#3a3a3a", "#d9d4c8", "#7a1f1f"}, "the three bands actually in the plate"
    assert enum == [m.lower() for m in enum], "one spelling, so a text search finds it"
    assert list(result.palette_enum) == enum
    q = Question(
        atom_id="palette",
        text="probe",
        check_type=CheckType.palette,
        polarity=Polarity.affirm,
        severity=Severity.optional,
        enum=enum,
    )
    assert len(_colours_or_refuse(q)) == 3, "the verifier parses every member the scaffold wrote"


def test_the_seeded_enum_is_never_mixed_hex_and_text(tmp_path):
    """CONTRACT_PALETTE_ENUM_MIXED: no single instrument measures both, and that refusal's own hint
    tells authors the answer is two atoms. A scaffold must not emit the shape it warns about."""
    from pcraft.core.contract.loader import ContractStore

    atoms = {
        a.id: a
        for a in (_scaffold(tmp_path) and ContractStore([tmp_path / "contracts"]).resolve("char:ashen-reaver").must_have)
    }
    assert all(m.startswith("#") for m in atoms["palette"].enum)


def test_the_note_says_the_hexes_are_a_measurement_not_canon(tmp_path):
    """MUST NOT BREAK. Background and anti-aliasing colours land in any naive dominant-colour
    extraction, so the emitted enum is a fact about the PLATE, never a statement of canon."""
    import json

    _scaffold(tmp_path)
    faction = json.loads((tmp_path / "contracts" / "factions" / "ashen-pact.faction.contract.json").read_text(encoding="utf-8"))
    note = faction["_note"].lower()
    assert "measured" in note and "plate" in note
    assert "not canon" in note
    assert "stub" in note, "and the atoms are stubs until an author reviews them"


def test_the_drift_cues_become_must_not_atoms_in_the_authors_own_words(tmp_path):
    """A must_not claim IS author-written -- they typed the cue -- so it is carried verbatim. Its
    severity is still `optional`, for the reason the shipped examples give: absence-verification is
    not measured on this stack, and promotion is the intended direction."""
    from pcraft.core.contract.loader import ContractStore

    resolved = _scaffold(tmp_path) and ContractStore([tmp_path / "contracts"]).resolve("char:ashen-reaver")
    cues = {m.id: m for m in resolved.must_not}
    assert cues["no_shield"].claim == "a shield", "the id loses the article; the claim never does"
    assert all(m.severity.value == "optional" for m in cues.values())


def test_the_scaffold_refuses_to_write_into_the_packaged_sprite_tree(tmp_path):
    """MUST NOT BREAK. The shipped examples are the de facto template every contract is copied
    from; a scaffold that lands beside them (or on top of them) destroys the reference."""
    from pcraft.domains.image.generator.conditioning import _SPRITE_ROOT

    with pytest.raises(PromptCraftError) as exc:
        _scaffold(tmp_path, out=_SPRITE_ROOT / "contracts")
    assert exc.value.code == "INPUT_SCAFFOLD_TARGET"
    assert "packaged" in (exc.value.hint or "").lower()
    assert "--contracts-dir" in (exc.value.hint or "")


def test_the_scaffold_never_silently_overwrites_an_existing_contract(tmp_path):
    _scaffold(tmp_path)
    with pytest.raises(PromptCraftError) as exc:
        _scaffold(tmp_path)
    assert exc.value.code == "INPUT_SCAFFOLD_TARGET"
    assert "overwrite" in (exc.value.hint or "").lower()


def test_an_identity_method_no_encoder_implements_is_refused_by_name(tmp_path):
    """Same allow-list discipline as conditioning._SUPPORTED_METHODS, moved to authoring time: a
    scaffold that writes `method: ipadapter` produces a contract whose lock is dropped at generate
    time while the receipt still stamps the resolved plate."""
    with pytest.raises(PromptCraftError) as exc:
        _scaffold(tmp_path, identity_method="ipadapter")
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "ipadapter" in exc.value.message


def test_an_unknown_trait_kind_is_refused_rather_than_defaulted(tmp_path):
    """A kind nobody wired must not quietly become a generic vqa atom: the author would get an
    atom with no window and no sign that the kind they wrote meant nothing."""
    traits = [{"id": "aura", "kind": "vibes"}]
    with pytest.raises(PromptCraftError) as exc:
        _scaffold(tmp_path, traits=traits)
    assert exc.value.code == "INPUT_SCAFFOLD_TRAIT"
    assert "vibes" in exc.value.message
    assert "insignia" in (exc.value.hint or ""), "the refusal lists the kinds that DO exist"


def test_the_sheet_is_json_and_says_so(tmp_path):
    """The minimal honest input. This package declares no YAML dependency (pydantic + typer), and
    the contract format is already JSON, so a .yaml sheet is refused by name rather than parsed by
    whatever happens to be installed in the operator's environment."""
    from pcraft.domains.image.scaffold import read_reference_sheet

    sheet = _sheet(tmp_path)
    renamed = sheet.with_suffix(".yaml")
    renamed.write_bytes(sheet.read_bytes())
    with pytest.raises(PromptCraftError) as exc:
        read_reference_sheet(renamed)
    assert exc.value.code == "INPUT_SCAFFOLD_SHEET"
    assert "json" in (exc.value.hint or "").lower()


def test_the_skeleton_comes_from_the_core_primitive_when_the_build_carries_one(monkeypatch, tmp_path):
    """This is the image-domain HALF of the scaffold: the defaults, the trait mapping, the measured
    palette. The contract SKELETON belongs to core/contract (F-a9d86551), so when that primitive is
    present it is used, and the result says which one ran -- a fallback nobody can see is a fork."""
    from pcraft.core.contract.schema import Contract
    from pcraft.domains.image import scaffold as sc

    called: list[tuple] = []

    def fake_scaffold_contract(level, contract_id, extends=None):
        called.append((level, contract_id, extends))
        return Contract(id=contract_id, level=level, extends=extends)

    monkeypatch.setattr(sc, "core_scaffold_primitive", lambda: fake_scaffold_contract)
    result = _scaffold(tmp_path)
    assert result.skeleton_source == "core-primitive"
    assert called == [
        ("faction", "faction:ashen-pact", None),
        ("character", "char:ashen-reaver", "faction:ashen-pact"),
    ]


def test_without_the_primitive_the_fallback_is_named_not_hidden(tmp_path):
    """Until F-a9d86551 lands there is no primitive to call. The skeleton is then built here from
    the same schema the primitive must use, and the result SAYS so, so 'the fold did not connect'
    is a visible fact rather than a silent duplicate implementation."""
    from pcraft.domains.image import scaffold as sc

    result = _scaffold(tmp_path)
    assert result.skeleton_source in ("core-primitive", "image-domain-fallback")
    if sc.core_scaffold_primitive() is None:
        assert result.skeleton_source == "image-domain-fallback"


def test_the_scaffold_reads_no_pixels_it_was_not_pointed_at(tmp_path):
    """The docstring's own claim, measured. 'Content-aware' here means mapping DECLARED traits to
    atoms; the only plate read is the one a palette trait names, and it is read by a histogram, not
    by anything that recognises what is in it."""
    from pcraft.domains.image import scaffold as sc

    read: list[str] = []
    real = sc.dominant_hex

    def spy(path, **kwargs):
        read.append(Path(path).name)
        return real(path, **kwargs)

    original = sc.dominant_hex
    sc.dominant_hex = spy
    try:
        _scaffold(tmp_path)
    finally:
        sc.dominant_hex = original
    assert read == ["costume.png"], "one plate, because one trait named one"


def test_every_region_the_scaffold_writes_is_one_the_gate_can_actually_honour(tmp_path):
    """The join between this wave's two halves. F-2c77d698 made a declared region CHECKABLE and
    made an unrecognised one a refusal -- so a scaffold that seeded a plausible-sounding window
    would emit contracts that refuse at gate time. Measured through the compiled DAG, which is what
    the gate actually receives, rather than against the defaults table this file also owns."""
    from pcraft.core.contract.compile_questions import compile_questions
    from pcraft.core.contract.loader import ContractStore
    from pcraft.domains.image.verifier.region import declared_region, region_window

    _scaffold(tmp_path)
    dag = compile_questions(ContractStore([tmp_path / "contracts"]).resolve("char:ashen-reaver"))
    regions = [(q.atom_id, declared_region(q)) for q in dag.questions]
    assert [r for _id, r in regions if r], "the scaffold seeded no regions at all"
    for atom_id, region in regions:
        if region is None:
            continue
        assert region_window(64, 64, region, atom_id=atom_id), f"{atom_id} names {region!r}"
