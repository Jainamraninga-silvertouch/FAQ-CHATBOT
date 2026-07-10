"""
LLM client service.

Isolates all network/vendor-specific code for talking to the LLM behind
one function: `generate_answer`. Uses Groq by default (fast + cheap for a
simple FAQ bot) but swapping providers only means editing this file.
"""
from __future__ import annotations

import logging
import os

from groq import Groq

logger = logging.getLogger(__name__)

_MODEL_NAME = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_client: Groq | None = None


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM client is misconfigured (missing API key)."""


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise LLMConfigurationError(
                "GROQ_API_KEY environment variable is not set. "
                "Set it before starting the server, e.g.\n"
                "  export GROQ_API_KEY=your_key_here   (macOS/Linux)\n"
                "  set GROQ_API_KEY=your_key_here      (Windows CMD)\n"
                "  $env:GROQ_API_KEY='your_key_here'   (Windows PowerShell)\n"
                "Or configure the Render Environment Variables for your service."
            )
        _client = Groq(api_key=api_key)
    return _client


def generate_answer(system_prompt: str, user_prompt: str) -> str:
    """Call the LLM with the strict FAQ system prompt and return its text reply."""
    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        logger.exception("LLM call failed")
        raise
