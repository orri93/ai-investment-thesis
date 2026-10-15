import httpx
import openai
import pytest

import openai_support

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


class FakeResponses:
    def __init__(self, errors):
        self.errors = list(errors)
        self.sent_tools: list[bool] = []

    def create(self, **payload):
        self.sent_tools.append("tools" in payload)
        if self.errors:
            raise self.errors.pop(0)
        return type("Response", (), {"output_text": " ok "})()


class FakeClient:
    def __init__(self, errors=()):
        self.responses = FakeResponses(errors)


def _call(client, web_search=True):
    return openai_support.create_response_text(
        client,
        model="m",
        system_prompt="s",
        user_prompt="u",
        error_type=RuntimeError,
        web_search=web_search,
    )


def test_tool_rejection_retries_without_web_search():
    error = openai.BadRequestError(
        "Invalid value: 'web_search'", response=httpx.Response(400, request=REQUEST), body=None
    )
    client = FakeClient([error])
    assert _call(client) == "ok"
    assert client.responses.sent_tools == [True, False]


def test_auth_errors_are_not_retried():
    error = openai.AuthenticationError(
        "Incorrect API key", response=httpx.Response(401, request=REQUEST), body=None
    )
    client = FakeClient([error])
    with pytest.raises(RuntimeError, match="Incorrect API key"):
        _call(client)
    assert client.responses.sent_tools == [True]


def test_web_search_disabled_sends_no_tools():
    client = FakeClient()
    _call(client, web_search=False)
    assert client.responses.sent_tools == [False]


def test_create_openai_client_wraps_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Could not initialize OpenAI client"):
        openai_support.create_openai_client(RuntimeError)
