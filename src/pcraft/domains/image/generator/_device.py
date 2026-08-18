"""Device + dtype selection shared by the diffusion generators (F-10b380ba).

Neither ``SDXLGenerator._load()`` nor ``FluxGenerator._load()`` used to call ``.to(<device>)`` on the
pipeline returned by ``from_pretrained``, and neither passed an explicit ``torch_dtype``. That is not
a crash -- it is standard, documented diffusers behaviour: an un-moved, un-cast pipeline loads to CPU
in float32. The practical effect is a generator that silently runs minutes-per-image on CPU (or, for
a 12B-parameter model like FLUX.1-dev, may not fit in RAM at all) with nothing in the receipt or the
logs saying so.

This module makes that policy explicit instead of implicit: pick a device, pick a dtype appropriate
to it, and log the choice so a CPU fallback is loud rather than a silent multi-minute stall.

Both functions take the already-imported ``torch`` module as an argument rather than importing it
themselves. That is what keeps this testable without installing the ``[image]`` extra: a test can
hand in a minimal stand-in object (``cuda.is_available()`` + the three dtype attributes) instead of
a real torch install, so the branch logic is covered without the core suite ever requiring torch to
be importable. See ``tests/test_amend_image.py``.

Never verified against a real GPU -- this audit environment has neither torch nor diffusers
installed, so nothing here has run against real hardware. The branch logic is unit-tested; whether a
given dtype is actually the right call for a given card is not something this pass can confirm."""

from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)


def select_device(torch_module) -> str:
    """Return ``"cuda"`` if the given torch module reports a usable CUDA device, else ``"cpu"``.

    Logs the choice either way, so a CPU fallback shows up in the log instead of just being a
    generation that mysteriously takes minutes instead of seconds."""
    device = "cuda" if torch_module.cuda.is_available() else "cpu"
    if device == "cpu":
        _LOG.warning(
            "no CUDA device visible to torch -- loading the diffusion pipeline on CPU. This is "
            "documented diffusers default behaviour, not a bug, but it will run minutes-per-image "
            "instead of seconds-per-image, and a large model may not fit in system RAM."
        )
    else:
        _LOG.info("loading diffusion pipeline on device=%s", device)
    return device


def select_dtype(torch_module, device: str, *, prefer_bf16: bool = False):
    """Pick a dtype appropriate to ``device``.

    CPU always gets float32: float16 kernels are unreliable or outright unsupported on many CPU
    builds of torch. CUDA gets bfloat16 when ``prefer_bf16`` is set (large models such as
    FLUX.1-dev, whose official usage snippet loads bf16 specifically to roughly halve the ~48GB
    float32 footprint) and float16 otherwise (the common SDXL convention)."""
    if device != "cuda":
        return torch_module.float32
    return torch_module.bfloat16 if prefer_bf16 else torch_module.float16
