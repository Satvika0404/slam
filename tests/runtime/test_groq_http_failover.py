"""Key failover through the real ``openai`` SDK and HTTP stack, against a loopback server.

The fake-client tests prove the failover logic; this proves the SDK really maps a 401 / 429 /
400 response, and its ``retry-after`` header, to what that logic expects. No network beyond
127.0.0.1 and no real key is involved.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from pydantic import BaseModel
from slam.config import Settings
from slam.runtime.groq_provider import GroqModelProvider
from slam.runtime.provider import ModelProviderError, ModelQuotaError

DAY = {"retry-after": "86400"}

Plan = Callable[[str, int], tuple[int, dict[str, Any], dict[str, str]]]


class Proposal(BaseModel):
    value: str


def ok_body(call_number: int) -> dict[str, Any]:
    return {
        "id": f"local-{call_number}",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": '{"value": "fine"}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
    }


@contextmanager
def groq_like_server(plan: Plan) -> Iterator[tuple[str, list[str]]]:
    """Serve ``plan(key, nth_call_of_that_key) -> (status, json, headers)``."""

    seen: list[str] = []
    counts: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            key = self.headers.get("authorization", "").removeprefix("Bearer ").strip()
            self.rfile.read(int(self.headers["content-length"]))
            seen.append(key)
            counts[key] = counts.get(key, 0) + 1
            status, body, headers = plan(key, counts[key])
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/openai/v1", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def provider_for(base_url: str, keys: str) -> GroqModelProvider:
    settings = Settings(
        _env_file=None,
        SLAM_MODEL_PROVIDER="groq",
        SLAM_MODEL="local-model",
        GROQ_API_KEYS=keys,
        GROQ_BASE_URL=base_url,
        SLAM_API_MAX_CALLS="20",
        SLAM_API_MAX_RETRIES="0",
    )
    return GroqModelProvider(settings, sleep=lambda seconds: None)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def ask(provider: GroqModelProvider) -> str:
    result = provider.generate(prompt="p", prompt_version="v1", response_model=Proposal)
    return result.value.value


def test_rejected_then_daily_limited_then_working_key_over_real_http() -> None:
    def plan(key: str, nth: int) -> tuple[int, dict[str, Any], dict[str, str]]:
        if key == "key-one":
            return 401, {"error": {"message": "Invalid API Key", "type": "invalid_request"}}, {}
        if key == "key-two":
            return 429, {"error": {"message": "daily limit", "type": "tokens"}}, DAY
        return 200, ok_body(nth), {}

    with groq_like_server(plan) as (url, seen):
        provider = provider_for(url, "key-one,key-two,key-three,key-four")
        assert ask(provider) == "fine"
        assert ask(provider) == "fine"
    assert seen == ["key-one", "key-two", "key-three", "key-three"]
    assert [r.state for r in provider.key_reports()] == [
        "rejected",
        "exhausted",
        "active",
        "active",
    ]
    three = provider.key_reports()[2]
    assert (three.successes, three.input_tokens, three.output_tokens) == (2, 60, 20)


def test_a_key_that_runs_dry_midway_hands_over_to_the_next() -> None:
    def plan(key: str, nth: int) -> tuple[int, dict[str, Any], dict[str, str]]:
        if key == "key-one" and nth > 3:
            return 429, {"error": {"message": "daily limit"}}, DAY
        return 200, ok_body(nth), {}

    with groq_like_server(plan) as (url, seen):
        provider = provider_for(url, "key-one,key-two")
        answers = [ask(provider) for _ in range(5)]
    assert answers == ["fine"] * 5
    assert seen == ["key-one"] * 4 + ["key-two"] * 2  # 3 ok, the 4th hit the limit, then key-two
    assert [r.state for r in provider.key_reports()] == ["exhausted", "active"]


def test_a_short_retry_after_cools_the_key_instead_of_retiring_it() -> None:
    def plan(key: str, nth: int) -> tuple[int, dict[str, Any], dict[str, str]]:
        if key == "key-one" and nth == 1:
            return 429, {"error": {"message": "per-minute limit"}}, {"retry-after": "2"}
        return 200, ok_body(nth), {}

    with groq_like_server(plan) as (url, _):
        provider = provider_for(url, "key-one,key-two")
        assert ask(provider) == "fine"
    assert [r.state for r in provider.key_reports()] == ["cooling", "active"]


def test_all_keys_dry_is_a_clear_quota_error_not_a_hang() -> None:
    def plan(key: str, nth: int) -> tuple[int, dict[str, Any], dict[str, str]]:
        return 429, {"error": {"message": "daily limit"}}, DAY

    with groq_like_server(plan) as (url, seen):
        provider = provider_for(url, "key-one,key-two,key-three")
        with pytest.raises(ModelQuotaError) as caught:
            ask(provider)
    assert seen == ["key-one", "key-two", "key-three"]  # each key tried exactly once
    assert "key#3 exhausted" in str(caught.value)
    assert "key-one" not in str(caught.value)


def test_a_bad_request_stops_immediately_without_touching_the_other_keys() -> None:
    def plan(key: str, nth: int) -> tuple[int, dict[str, Any], dict[str, str]]:
        return 400, {"error": {"message": "model_not_found", "type": "invalid_request"}}, {}

    with groq_like_server(plan) as (url, seen):
        provider = provider_for(url, "key-one,key-two")
        with pytest.raises(ModelProviderError, match="HTTP 400"):
            ask(provider)
    assert seen == ["key-one"]
