"""Concrete LLMTextProvider strategies: Gemini, Anthropic, Azure OpenAI.

Each wraps one SDK's call shape (Gemini: system_instruction; Anthropic: system=;
Azure: system+user messages) behind the same generate() contract, and returns None
on any failure so the fallback chain continues.
"""
from __future__ import annotations

import logging
from typing import Optional

from ...core.config import settings

log = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, model: str):
        self.model = model

    def generate(self, *, system: str, user: str, max_tokens: int = 9000, temperature: float = 0.6) -> Optional[str]:
        from app.services.ai import get_gemini_client
        client = get_gemini_client()
        if client is None:
            return None
        try:
            from google.genai import types as genai_types
            r = client.models.generate_content(
                model=self.model, contents=user,
                config=genai_types.GenerateContentConfig(
                    temperature=temperature, max_output_tokens=max_tokens, system_instruction=system))
            return (r.text or "").strip() or None
        except Exception as e:
            log.warning("[LLM] Gemini (%s) failed: %s", self.model, e)
            return None


class AnthropicProvider:
    def __init__(self, model: str):
        self.model = model

    def generate(self, *, system: str, user: str, max_tokens: int = 9000, temperature: float = 0.6) -> Optional[str]:
        if not settings.ANTHROPIC_API_KEY:
            return None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            r = client.messages.create(
                model=self.model, max_tokens=max_tokens, temperature=temperature,
                system=system, messages=[{"role": "user", "content": user}])
            return (r.content[0].text or "").strip() or None
        except Exception as e:
            log.warning("[LLM] Anthropic (%s) failed: %s", self.model, e)
            return None


class AzureProvider:
    def __init__(self, model: str):
        self.model = model

    def generate(self, *, system: str, user: str, max_tokens: int = 9000, temperature: float = 0.6) -> Optional[str]:
        from app.services.ai import get_client
        try:
            client = get_client()
            r = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature, max_tokens=max_tokens)
            return (r.choices[0].message.content or "").strip() or None
        except Exception as e:
            log.warning("[LLM] Azure (%s) failed: %s", self.model, e)
            return None
