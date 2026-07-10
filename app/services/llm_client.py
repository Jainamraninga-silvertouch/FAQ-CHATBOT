"""
LLM client service.

Isolates all network/vendor-specific code for talking to the LLM behind
one function: `generate_answer`. Uses Groq by default (fast + cheap for a
simple FAQ bot) but swapping providers only means editing this file.
"""
from __future__ import annotations

import logging
import os

from groq import APIStatusError, Groq

logger = logging.getLogger(__name__)

_MODEL_NAME = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_client: Groq | None = None


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM client is misconfigured (missing API key)."""


class LLMRequestTooLargeError(RuntimeError):
    """Raised when the request exceeds the model's token limits."""


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
    except APIStatusError as exc:
        message = str(exc)
        if "Request too large" in message or "tokens per minute" in message or "rate_limit_exceeded" in message:
            logger.error("LLM request too large: %s", message)
            raise LLMRequestTooLargeError(
                "The request is too large for the current model. "
                "Try a shorter question or reduce the document context."
            ) from exc
        logger.exception("LLM call failed")
        raise
    except Exception:
        logger.exception("LLM call failed")
        raise
