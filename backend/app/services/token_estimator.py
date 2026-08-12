"""Tokenizer-independent estimates used for context budgeting and diagnostics."""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    """Return a stable estimate for diagnostics and compression policies.

    This is not a hard safety bound. Provider-reported usage remains the source
    of truth for cost metrics.
    """
    cjk_count = sum(
        1
        for char in text
        if "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
    )
    other_count = sum(
        1
        for char in text
        if not char.isspace()
        and not (
            "\u3400" <= char <= "\u9fff"
            or "\uf900" <= char <= "\ufaff"
        )
    )
    return cjk_count + math.ceil(other_count / 4)


def token_upper_bound(text: str) -> int:
    """Return a tokenizer-independent upper bound for hard input budgets."""
    return len(text.encode("utf-8"))
