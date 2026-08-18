"""F-IMG-FEAT-001/002/003 — SDXL pose-lock, IP-Adapter, real inpaint.

GPU-free: fake torch / diffusers / PIL via monkeypatch. No download, no credit,
no 5090. Flux stays refused. Missing refs refuse before any pipeline load.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from pcraft.domains.image.generator import conditioning as cond
from pcraft.domains.image.generator.flux_generator import FluxGenerator
from pcraft.domains.image.generator.sdxl_generator import SDXLGenerator
from pcraft.errors import PromptCraftError
from pcraft.testing import write_solid_png


def _install_fake_torch(monkeypatch) -> None:
    fake_torch = types.ModuleType("torch")

    class _Cuda:
        @staticmethod
        def is_available():
            return False

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


class _FakeImage:
    def __init__(self, path=None, size=(64, 64)):
        self.path = path
        self.size = size

    def save(self, path):
        Path(path).write_bytes(b"fake-png")


class _FakePipe:
    def __init__(self, model_id, **kwargs):
        self.model_id = model_id
        self.init_kwargs = kwargs
        self.to_calls: list[str] = []
        self.call_kwargs = None
        self.device = "cpu"
        self.ip_adapter = None
        self.ip_scale = None
        self.controlnet = kwargs.get("controlnet")

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


def _install_fake_diffusers(monkeypatch) -> dict:
    fake = types.ModuleType("diffusers")
    captured: dict = {"pipes": [], "controlnets": []}

    class _Pipe:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            p = _FakePipe(model_id, **kwargs)
            captured["pipes"].append(p)
            captured["last"] = p
            captured[cls.__name__] = p
            return p

    class _SDXL(_Pipe):
        __name__ = "StableDiffusionXLPipeline"

    class _CN(_Pipe):
        __name__ = "StableDiffusionXLControlNetPipeline"

    class _Inpaint(_Pipe):
        __name__ = "StableDiffusionXLInpaintPipeline"

    class _CNInpaint(_Pipe):
        __name__ = "StableDiffusionXLControlNetInpaintPipeline"

    class _ControlNetModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            captured["controlnets"].append(model_id)
            return f"cn:{model_id}"

    fake.StableDiffusionXLPipeline = _SDXL
    fake.StableDiffusionXLControlNetPipeline = _CN
    fake.StableDiffusionXLInpaintPipeline = _Inpaint
    fake.StableDiffusionXLControlNetInpaintPipeline = _CNInpaint
    fake.ControlNetModel = _ControlNetModel
    monkeypatch.setitem(sys.modules, "diffusers", fake)
    return captured


def _install_fake_pil(monkeypatch) -> dict:
    fake_pil = types.ModuleType("PIL")
    fake_image = types.ModuleType("PIL.Image")
    fake_draw = types.ModuleType("PIL.ImageDraw")
    opened: dict = {"paths": []}

    class _Img:
        def __init__(self, mode="RGB", size=(64, 64), color=0):
            self.mode = mode
            self.size = size
            self.color = color

        def save(self, path):
            Path(path).write_bytes(b"fake-png")

    def open_image(path):
        opened["paths"].append(str(path))
        return _Img()

    def new_image(mode, size, color=0):
        return _Img(mode, size, color)

    class _Draw:
        def __init__(self, img):
            self.img = img
            self.rects = []

        def rectangle(self, box, fill=0):
            self.rects.append((box, fill))

    fake_image.open = open_image
    fake_image.new = new_image
    fake_draw.Draw = _Draw
    fake_pil.Image = fake_image
    fake_pil.ImageDraw = fake_draw
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", fake_draw)
    return opened


# --------------------------------------------------------------------------- region boxes (no PIL)


def test_region_box_head_is_the_top_third():
    assert cond.region_box(100, 100, "head") == (0, 0, 100, 35)
    assert cond.region_box(100, 100, "face") == (0, 0, 100, 35)


def test_region_box_torso_is_the_middle():
    left, top, right, bottom = cond.region_box(100, 100, "torso")
    assert left < right and top < bottom
    assert top > 0 and bottom < 100


def test_pipeline_kind_composes():
    assert cond.pipeline_kind({}) == "base"
    assert cond.pipeline_kind({"pose_refs": ["a.png"]}) == "controlnet"
    assert cond.pipeline_kind({"identity_refs": [{"plate": "p.png", "method": "ip_adapter"}]}) == "ip"
    assert (
        cond.pipeline_kind(
            {
                "pose_refs": ["a.png"],
                "identity_refs": [{"plate": "p.png", "method": "ip_adapter"}],
                "inpaint_from": "x.png",
            }
        )
        == "inpaint_controlnet_ip"
    )


# --------------------------------------------------------------------------- refuse-closed (no fakes)


def test_sdxl_missing_pose_is_ref_missing_not_unsupported():
    with pytest.raises(PromptCraftError) as exc:
        SDXLGenerator().generate("p", "n", {"pose_refs": ["nope.openpose.png"]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_REF_MISSING"


def test_sdxl_lora_identity_is_still_unsupported(tmp_path):
    plate = write_solid_png(tmp_path / "costume.png")
    with pytest.raises(PromptCraftError) as exc:
        SDXLGenerator().generate(
            "p",
            "n",
            {"identity_refs": [{"plate": str(plate), "method": "lora", "weight": 0.8}]},
            seed=1,
        )
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "lora" in exc.value.message


def test_sdxl_method_none_is_not_a_request(tmp_path):
    """method=none skips the plate. No ref to load, so we fall through to _load
    and (without the extra) DEP_IMAGE_MISSING -- never REF_MISSING / UNSUPPORTED."""
    with pytest.raises(PromptCraftError) as exc:
        SDXLGenerator().generate(
            "p",
            "n",
            {"identity_refs": [{"plate": str(tmp_path / "missing.png"), "method": "none"}]},
            seed=1,
        )
    assert exc.value.code == "DEP_IMAGE_MISSING"


def test_flux_still_refuses_pose_even_when_the_file_exists(tmp_path):
    pose = write_solid_png(tmp_path / "front.openpose.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator().generate("p", "n", {"pose_refs": [str(pose)]}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"
    assert "flux" in exc.value.message.lower()


def test_flux_still_refuses_inpaint(tmp_path):
    src = write_solid_png(tmp_path / "prev.png")
    with pytest.raises(PromptCraftError) as exc:
        FluxGenerator().generate("p", "n", {"inpaint_from": str(src), "inpaint_region": "head"}, seed=1)
    assert exc.value.code == "GATE_CONDITIONING_UNSUPPORTED"


# --------------------------------------------------------------------------- SDXL apply path (fakes)


def test_sdxl_pose_lock_uses_the_controlnet_pipeline(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch)
    captured = _install_fake_diffusers(monkeypatch)
    opened = _install_fake_pil(monkeypatch)
    pose = write_solid_png(tmp_path / "two-hand.openpose.png")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate("p", "n", {"pose_refs": [str(pose)]}, seed=3)
    assert Path(result.image_path).exists()
    assert captured["controlnets"] == ["xinsir/controlnet-openpose-sdxl-1.0"]
    pipe = captured["last"]
    assert "image" in pipe.call_kwargs
    assert "controlnet_conditioning_scale" in pipe.call_kwargs
    assert str(pose) in opened["paths"]
    assert result.conditioning["applied"]["kind"] == "controlnet"
    assert result.conditioning["applied"]["pose"] == [str(pose)]


def test_sdxl_ip_adapter_loads_the_plate_and_sets_scale(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch)
    captured = _install_fake_diffusers(monkeypatch)
    _install_fake_pil(monkeypatch)
    plate = write_solid_png(tmp_path / "face.png")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate(
        "p",
        "n",
        {
            "identity_refs": [{"plate": str(plate), "method": "ip_adapter", "weight": 0.6}],
            "identity_weight_bump": 0.15,
        },
        seed=4,
    )
    pipe = captured["last"]
    assert pipe.ip_adapter is not None
    assert pipe.ip_scale == pytest.approx(0.75)
    assert "ip_adapter_image" in pipe.call_kwargs
    assert result.conditioning["applied"]["kind"] == "ip"


def test_sdxl_inpaint_passes_init_image_and_mask(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch)
    captured = _install_fake_diffusers(monkeypatch)
    _install_fake_pil(monkeypatch)
    src = write_solid_png(tmp_path / "prev.png")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate(
        "p",
        "n",
        {"inpaint_from": str(src), "inpaint_region": "head"},
        seed=5,
    )
    pipe = captured["last"]
    assert "mask_image" in pipe.call_kwargs
    assert "image" in pipe.call_kwargs
    assert pipe.call_kwargs["strength"] == 0.85
    assert result.image_path.endswith("_inpaint.png")
    assert result.conditioning["applied"]["inpaint"]["region"] == "head"


def test_sdxl_pose_plus_identity_is_controlnet_ip(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch)
    captured = _install_fake_diffusers(monkeypatch)
    _install_fake_pil(monkeypatch)
    pose = write_solid_png(tmp_path / "pose.png")
    plate = write_solid_png(tmp_path / "face.png")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate(
        "p",
        "n",
        {
            "pose_refs": [str(pose)],
            "identity_refs": [{"plate": str(plate), "method": "ip_adapter", "weight": 0.6}],
        },
        seed=6,
    )
    assert result.conditioning["applied"]["kind"] == "controlnet_ip"
    assert captured["last"].ip_adapter is not None
    assert captured["controlnets"]


def test_sdxl_inpaint_plus_pose_uses_control_image(monkeypatch, tmp_path):
    _install_fake_torch(monkeypatch)
    captured = _install_fake_diffusers(monkeypatch)
    _install_fake_pil(monkeypatch)
    pose = write_solid_png(tmp_path / "pose.png")
    src = write_solid_png(tmp_path / "prev.png")
    gen = SDXLGenerator(out_dir=tmp_path / "out")
    result = gen.generate(
        "p",
        "n",
        {"pose_refs": [str(pose)], "inpaint_from": str(src), "inpaint_region": "torso"},
        seed=7,
    )
    pipe = captured["last"]
    assert "control_image" in pipe.call_kwargs
    assert "mask_image" in pipe.call_kwargs
    assert result.conditioning["applied"]["kind"] == "inpaint_controlnet"


def test_shipped_example_refs_resolve_without_cwd_files():
    """The example contract names poses/ and plates/ relative paths. Those
    must resolve from the packaged sprite tree, not from cwd."""
    from pcraft.core.loop.orchestrate import _assemble_conditioning
    from pcraft.sample import load_sprite_example

    _s, resolved, _t, _c = load_sprite_example()
    bound = cond.bind_refs(_assemble_conditioning(resolved))
    assert bound["pose_refs"]
    assert Path(bound["pose_refs"][0]).is_file()
    assert "two-hand-weapon.openpose.png" in bound["pose_refs"][0]
    plates = [Path(r["plate"]).name for r in bound["identity_refs"]]
    assert "ashen-reaver-front.png" in plates
    assert "ashen-pact-costume.png" in plates
    cond.refuse_unimplemented_identity("sdxl.base-1.0.v1", bound)


def test_a_sibling_pose_path_does_not_steal_the_turnaround_plate():
    """poses/front.openpose.png is not poses/turnaround/front.openpose.png."""
    with pytest.raises(FileNotFoundError):
        cond.resolve_ref("poses/front.openpose.png")
    assert cond.resolve_ref("poses/turnaround/front.openpose.png").is_file()


def test_eight_turnaround_openpose_plates_are_packaged():
    from pcraft.domains.image.subdomains.sprite import EIGHT_DIRECTIONS, POSE_REFS

    for direction in EIGHT_DIRECTIONS:
        path = cond.resolve_ref(POSE_REFS[direction])
        assert path.is_file(), direction
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_no_fake_modules_leak_past_this_files_tests():
    assert "torch" not in sys.modules
    assert "diffusers" not in sys.modules
    assert "PIL" not in sys.modules
    assert "PIL.Image" not in sys.modules
