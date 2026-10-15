"""Shared OpenAI client creation and Responses API calls."""

from __future__ import annotations

import os

from openai import BadRequestError, OpenAI, OpenAIError

WEB_SEARCH_TOOL = {"type": "web_search"}


def create_openai_client(error_type: type[Exception]) -> OpenAI:
    try:
        return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    except OpenAIError as exc:
        raise error_type(f"Could not initialize OpenAI client: {exc}") from exc


def create_response_text(
    client: OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    error_type: type[Exception],
    web_search: bool = False,
) -> str:
    """Run a Responses API call and return its text, raising error_type on failure.

    With web_search=True the call is retried without the tool only when the model
    rejects the tool itself; other errors (auth, rate limits, ...) are raised as-is.
    """
    payload: dict = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if web_search:
        payload["tools"] = [WEB_SEARCH_TOOL]

    try:
        try:
            response = client.responses.create(**payload)
        except BadRequestError as exc:
            if not web_search or not _is_tool_rejection(exc):
                raise
            payload.pop("tools")
            response = client.responses.create(**payload)
    except OpenAIError as exc:
        raise error_type(f"OpenAI request failed: {exc}") from exc

    text = getattr(response, "output_text", "")
    if not text or not text.strip():
        raise error_type("OpenAI returned no text.")
    return text.strip()


def _is_tool_rejection(exc: BadRequestError) -> bool:
    message = str(exc).lower()
    return "web_search" in message or "tool" in message
