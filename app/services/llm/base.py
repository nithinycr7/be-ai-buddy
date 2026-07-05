"""LLMTextProvider Protocol + fallback chain.

Not speculative: 6 services already do a runtime Gemini→Anthropic→Azure fallback
for HTML/text generation, each re-implementing the same try/except ladder. These
are three real, interchangeable implementations selected at runtime — a Strategy.
Programming to this Protocol lets a caller pass an ordered list of providers and
get the first non-empty result, instead of copy-pasting the ladder.

Sync by design: the underlying SDK calls (google-genai / anthropic / openai) are
blocking and are already invoked synchronously inside the async service methods.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Protocol

log = logging.getLogger(__name__)


class LLMTextProvider(Protocol):
    def generate(self, *, system: str, user: str,
                 max_tokens: int = 9000, temperature: float = 0.6) -> Optional[str]:
        """Return generated text, or None if this provider is unavailable/failed
        (so the fallback chain can move on). Must not raise."""
        ...


def generate_text(providers: List[LLMTextProvider], *, system: str, user: str,
                  max_tokens: int = 9000, temperature: float = 0.6) -> Optional[str]:
    """Strategy chain: try each provider in order; return the first non-empty result."""
    for p in providers:
        out = p.generate(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        if out:
            return out
    return None
