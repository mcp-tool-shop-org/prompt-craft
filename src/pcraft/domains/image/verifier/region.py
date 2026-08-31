"""Where an atom must hold, honoured at score time. GPU-free, no model, no temp files.

F-2c77d698. ``Atom.spatial`` with ``kind=region`` is described by ``core/contract/schema.py`` as
"a named image region (torso, head, hands, chest-center)" and as "a CHECKABLE image region", and
``compile_questions`` copies it onto every compiled ``Question``. MEASURED across ``src/`` before
this module existed, no verifier read it: ``loader`` used it for the no-relaxation comparison and
``orchestrate`` used it to pick an INPAINT region, and that was the whole readership. So the
shipped ``sigil`` atom -- ``spatial.kind=region``, ``ref='chest-center'`` -- was answered from
anywhere in the frame, and a sigil rendered on the shoulder satisfied it.

THE WINDOW IS NOT DERIVED HERE. ``conditioning.region_box`` already returns the exact pixel box
for a named region and is the same function the inpaint repair calls, so the window the gate
checks is the window the repair paints. A second copy of that geometry would be free to drift
from the first, and a gate that checks a different rectangle than the repair paints is worse than
one that checks nothing.

SCOPE, stated rather than implied. Only the deterministic histogram (``palette_verifier``) crops
today. The three model-backed verifiers keep scoring the FULL FRAME and say so on the receipt via
``full_frame_note`` -- see that function for why partial support in silence would be the worse
outcome.
"""

from __future__ import annotations

from ....core.contract.compile_questions import Question
from ....errors import PromptCraftError
from ..generator.conditioning import SUPPORTED_REGIONS, is_supported_region, region_box


def declared_region(question: Question) -> str | None:
    """The region name this atom declares, or None when it declares no checkable window.

    ``kind=pose`` returns None on purpose and is NOT an error: that ``ref`` is a path to an
    openpose guide image, which is geometry handed to the GENERATOR, not a window a verifier could
    crop to. The shipped ``weapon`` atom carries one, so this is the common case, not a corner.
    """
    spatial = question.spatial
    if spatial is None or spatial.kind.value != "region":
        return None
    name = (spatial.ref or "").strip()
    return name or None


def region_window(width: int, height: int, region: str, *, atom_id: str) -> tuple[int, int, int, int]:
    """``conditioning.region_box`` for a name that is actually recognised. Refuses by name.

    ``region_box`` is total -- an unknown name silently gets its centre box -- which is right for
    the inpaint repair (it must paint somewhere, and ``inpaint_region`` defaults to ``"center"``)
    and wrong for a gate. A verdict scored on a guessed window is indistinguishable on the receipt
    from a measured one, so a name nobody wired is refused BY NAME, exactly as
    ``refuse_unimplemented_identity`` refuses an ``identity_ref.method`` nobody wired rather than
    dropping the lock.
    """
    if not is_supported_region(region):
        raise PromptCraftError(
            "CONTRACT_SPATIAL_REGION_UNKNOWN",
            f"atom {atom_id!r} declares spatial region {region!r}, which names no known window",
            hint="A region must be one of: " + ", ".join(sorted(SUPPORTED_REGIONS)) + ". An "
            "unrecognised name would be scored on a guessed centre box and the verdict would read "
            "like a measured one. Fix the name in the contract, or drop `spatial` to check the "
            "whole frame.",
        )
    return region_box(width, height, region)


def crop_pixels(
    pixels: list[tuple[int, int, int]],
    width: int,
    height: int,
    box: tuple[int, int, int, int],
) -> list[tuple[int, int, int]]:
    """The pixels inside ``box``, from a flat row-major list. Pure index arithmetic.

    Cropping the PIXELS rather than writing a cropped image is what keeps this GPU-free and
    Pillow-free: ``palette_verifier.load_rgb`` already produced the list, both of its branches
    produce the same one, and a temp file would add an irreversible filesystem action to a read-only
    measurement.
    """
    if len(pixels) != width * height:
        raise PromptCraftError(
            "RUNTIME_VERIFIER_CALL_FAILED",
            f"cannot crop {width}x{height} from {len(pixels)} pixels",
            hint="The decoded pixel count disagrees with the image's own declared size, so no "
            "window can be located inside it. This is the same completeness failure the PNG "
            "readers refuse -- a score over the wrong rectangle is not a measurement.",
        )
    left, top, right, bottom = box
    left = max(0, min(left, width))
    right = max(left, min(right, width))
    top = max(0, min(top, height))
    bottom = max(top, min(bottom, height))
    out: list[tuple[int, int, int]] = []
    for y in range(top, bottom):
        row = y * width
        out.extend(pixels[row + left : row + right])
    return out


def describe_window(region: str, box: tuple[int, int, int, int], width: int, height: int) -> str:
    """The sentence a region-scored verdict carries on the receipt.

    Routed through the harness's existing ``detail`` seam (``_detail_for``) rather than smuggled
    into ``verifier_id``: the id answers "who measured this", and "which rectangle" is a second
    fact. Both are needed, because a cropped number is not on the full-frame scale and a reader
    who cannot see the box cannot know that.
    """
    return f"scored over region {region!r} box={box} of {width}x{height}"


def full_frame_note(question: Question, verifier_id: str) -> str | None:
    """What a model-backed verifier owes an atom whose declared region it did not honour.

    REFUSAL OF SCOPE, on the receipt rather than only in a comment. Cropping before a VQAScore /
    SigLIP2 / DSG call is mechanically easy and would be dishonest today: those scores are graded
    against bands (``vqa`` 0.80/0.40, ``siglip2`` 0.10/0.01) derived from full-frame images, a
    crop changes the model's input distribution, and nothing here has measured what those bands
    become on a 35%-of-frame head crop. Shipping the crop anyway would re-decide every region atom
    under a threshold table whose ``fingerprint()`` hashes only band values and would therefore
    report no drift -- precisely the silence STATE_REPLAY_DRIFT exists to break.

    So the model tiers keep scoring the whole frame, and every verdict that cost something says
    which atom it cost it on. Returns None when the atom declares no region: there is nothing to
    disclose, and inventing a detail line for the ordinary case would bury the ones that matter.
    """
    region = declared_region(question)
    if region is None:
        return None
    return (
        f"atom declares region {region!r}; {verifier_id} scored the FULL FRAME "
        "(region scoring is not calibrated for this instrument)"
    )
