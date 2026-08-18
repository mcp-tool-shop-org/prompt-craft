"""Surfaces that existed and nothing called. The armature-index transfer.

Each test is the first caller. What it looks like if wrong: the helper
drifts, or a fail-closed path is never entered.
"""

from __future__ import annotations

import pytest

from pcraft.core.loop.retry_policy import OutcomeClass, classify_failure
from pcraft.core.plugin import detect
from pcraft.errors import PromptCraftError, wrap_error


def test_detect_refuses_a_missing_name():
    with pytest.raises(PromptCraftError) as exc:
        detect(None)
    assert exc.value.code == "INPUT_NO_DOMAIN"


def test_detect_refuses_an_unknown_domain():
    import pcraft.domains.image  # noqa: F401

    with pytest.raises(PromptCraftError) as exc:
        detect("video")
    assert exc.value.code == "INPUT_UNKNOWN_DOMAIN"
    assert "image" in exc.value.message


def test_classify_failure_splits_semantic_from_transient():
    assert classify_failure("GATE_FAIL") is OutcomeClass.SEMANTIC
    assert classify_failure("CONTRACT_RELAXATION") is OutcomeClass.SEMANTIC
    assert classify_failure("RUNTIME_BOOM") is OutcomeClass.TRANSIENT


def test_wrap_error_passes_through_a_structured_error():
    err = PromptCraftError("IO_GATE_INPUT", "x")
    assert wrap_error(err, "RUNTIME_X") is err


def test_wrap_error_wraps_a_bare_exception():
    wrapped = wrap_error(ValueError("nope"), "RUNTIME_WRAP")
    assert wrapped.code == "RUNTIME_WRAP"
    assert wrapped.cause is not None
