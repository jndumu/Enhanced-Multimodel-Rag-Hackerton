"""Token counting and text truncation utilities using tiktoken."""

from __future__ import annotations

import functools

import tiktoken

_ENCODING_NAME = "cl100k_base"


@functools.lru_cache(maxsize=1)
def _get_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_get_encoding().encode(text, disallowed_special=()))


def truncate_to_tokens(text: str, max_tokens: int, from_end: bool = False) -> str:
    """Return text truncated to at most max_tokens tokens.

    If from_end=True, take the last max_tokens tokens instead of the first.
    """
    enc = _get_encoding()
    tokens = enc.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    if from_end:
        tokens = tokens[-max_tokens:]
    else:
        tokens = tokens[:max_tokens]
    return enc.decode(tokens)
