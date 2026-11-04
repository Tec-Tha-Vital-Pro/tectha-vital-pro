"""Claude API access for Tec Tha AI.

AI is OFF unless TT_AI=on AND an SDK credential (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN)
is set. Every failure is raised as AIError; callers decide what staff see (never a silent fallback).
"""
import os
import sys

import anthropic
from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept the server-side refusal fallback (`fallbacks: "default"`) on the Claude API.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.Anthropic | None = None
_warned = False


class AIError(Exception):
    """The model could not produce a usable answer (API error, refusal, truncation, bad output)."""


def enabled() -> bool:
    global _warned
    if os.environ.get("TT_AI", "off") != "on":
        return False
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        if not _warned:
            print("Tec Tha AI: TT_AI=on but no ANTHROPIC_API_KEY is set, so AI stays off.", file=sys.stderr)
            _warned = True
        return False
    return True


def model() -> str:
    return os.environ.get("TT_AI_MODEL", DEFAULT_MODEL)


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=2, timeout=30.0)
    return _client


def structured(*, system: str, user: str, output: type[BaseModel], effort: str, max_tokens: int,
               client=None) -> BaseModel:
    """One Claude call returning a validated Pydantic object.

    The stable system prompt goes first with cache_control (cached prefix); the volatile
    context and conversation go in the user turn after it.
    """
    c = client or get_client()
    m = model()
    kwargs = dict(
        model=m,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=output,
        output_config={"effort": effort},
    )
    if m in _FALLBACK_MODELS:
        kwargs["betas"] = [_FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    try:
        resp = c.beta.messages.parse(**kwargs)
    except anthropic.BadRequestError as e:
        raise AIError(f"Bad request to Claude API: {e.message}") from e
    except anthropic.AuthenticationError as e:
        raise AIError("Claude API key is invalid (check ANTHROPIC_API_KEY)") from e
    except anthropic.PermissionDeniedError as e:
        raise AIError(f"Claude API key lacks permission: {e.message}") from e
    except anthropic.NotFoundError as e:
        raise AIError(f"Model {m!r} not found (check TT_AI_MODEL)") from e
    except anthropic.RateLimitError as e:
        raise AIError("Claude API rate limit reached; try again shortly") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Could not reach the Claude API (network)") from e

    if resp.stop_reason == "refusal":
        cat = getattr(getattr(resp, "stop_details", None), "category", None)
        raise AIError(f"Claude declined this request (category: {cat})")
    if resp.stop_reason == "max_tokens":
        raise AIError("Claude's answer was cut off (max_tokens)")
    parsed = getattr(resp, "parsed_output", None)
    if parsed is None:
        raise AIError("Claude returned no structured output")
    return parsed
