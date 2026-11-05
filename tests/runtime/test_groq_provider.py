"""Groq adapter with ordered key failover, driven entirely by fake clients (no network)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel
from slam.config import Settings
from slam.runtime.groq_provider import GroqModelProvider, parse_structured
from slam.runtime.key_pool import KeyPool
from slam.runtime.provider import (
    ModelAuthenticationError,
    ModelImageInput,
    ModelMalformedResponseError,
    ModelProviderError,
    ModelQuotaError,
    ModelTruncationError,
)

KEYS = [f"fake-secret-{n}-" + "q" * 14 for n in range(1, 5)]


class Proposal(BaseModel):
    value: str


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def reply(
    text: str = '{"value": "ok"}',
    *,
    finish: str = "stop",
    tokens: tuple[int, int] = (11, 4),
) -> Any:
    message = SimpleNamespace(content=text, refusal=None)
    return SimpleNamespace(
        id="req-1",
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(
            prompt_tokens=tokens[0],
            completion_tokens=tokens[1],
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


def status_error(cls: type[openai.APIStatusError], status: int, **headers: str) -> Exception:
    request = httpx.Request("POST", "https://groq.invalid/openai/v1/chat/completions")
    response = httpx.Response(status, request=request, headers=headers)
    return cls("provider said no", response=response, body=None)


class FakeClient:
    """Plays a script of replies / exceptions, one per ``create`` call."""

    def __init__(self, *script: Any, models: list[str] | Exception | None = None) -> None:
        self.script = list(script)
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}
        self._models = models
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=self._list)

    def _create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.last_kwargs = kwargs
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item

    def _list(self) -> Any:
        if isinstance(self._models, Exception):
            raise self._models
        return SimpleNamespace(data=[SimpleNamespace(id=m) for m in (self._models or [])])


def make(
    clients: list[FakeClient],
    *,
    retries: int = 2,
    clock: Clock | None = None,
) -> tuple[GroqModelProvider, list[float], Clock]:
    settings = Settings(
        _env_file=None,
        SLAM_MODEL_PROVIDER="groq",
        SLAM_MODEL="test-model",
        GROQ_API_KEYS=",".join(KEYS[: len(clients)]),
        SLAM_API_MAX_CALLS="50",
        SLAM_API_MAX_RETRIES=str(retries),
    )
    clock = clock or Clock()
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    by_secret = dict(zip(KEYS, clients, strict=False))
    provider = GroqModelProvider(
        settings,
        pool=KeyPool(settings.groq_key_list, clock=clock),
        client_factory=lambda secret: by_secret[secret],
        sleep=sleep,
    )
    return provider, sleeps, clock


def ask(provider: GroqModelProvider, **kwargs: Any) -> Proposal:
    result = provider.generate(
        prompt="Say ok", prompt_version="v1", response_model=Proposal, **kwargs
    )
    return result.value


def test_first_key_answers_and_the_rest_are_untouched() -> None:
    clients = [FakeClient(reply()), FakeClient(reply()), FakeClient(reply())]
    provider, _, _ = make(clients)
    result = provider.generate(prompt="p", prompt_version="v1", response_model=Proposal)
    assert result.value == Proposal(value="ok")
    assert (clients[0].calls, clients[1].calls, clients[2].calls) == (1, 0, 0)
    assert result.metadata.provider == "groq"
    assert (result.metadata.usage.input_tokens, result.metadata.usage.output_tokens) == (11, 4)
    assert clients[0].last_kwargs["response_format"] == {"type": "json_object"}
    assert clients[0].last_kwargs["temperature"] == 0


def test_a_rejected_key_rolls_over_to_the_second_then_stays_there() -> None:
    clients = [
        FakeClient(status_error(openai.AuthenticationError, 401)),
        FakeClient(reply()),
    ]
    provider, _, _ = make(clients)
    assert ask(provider) == Proposal(value="ok")
    assert ask(provider) == Proposal(value="ok")
    assert (clients[0].calls, clients[1].calls) == (1, 2)  # key#1 is never retried
    assert [r.state for r in provider.key_reports()] == ["rejected", "active"]


def test_a_key_that_finishes_its_quota_rolls_to_the_next_and_so_on() -> None:
    daily = status_error(openai.RateLimitError, 429, **{"retry-after": "86400"})
    clients = [FakeClient(daily), FakeClient(daily), FakeClient(daily), FakeClient(reply())]
    provider, sleeps, _ = make(clients)
    assert ask(provider) == Proposal(value="ok")
    assert [c.calls for c in clients] == [1, 1, 1, 1]
    assert [r.state for r in provider.key_reports()] == [
        "exhausted",
        "exhausted",
        "exhausted",
        "active",
    ]
    assert sleeps == []  # nothing was waited for


def test_a_short_rate_limit_moves_on_without_waiting_and_returns_after_the_cooldown() -> None:
    brief = status_error(openai.RateLimitError, 429, **{"retry-after": "5"})
    clients = [FakeClient(brief, reply()), FakeClient(reply())]
    provider, sleeps, clock = make(clients)
    assert ask(provider) == Proposal(value="ok")  # key#1 limited -> key#2 answered
    assert (clients[0].calls, clients[1].calls) == (1, 1)
    clock.now += 6
    assert ask(provider) == Proposal(value="ok")  # key#1 is preferred again
    assert (clients[0].calls, clients[1].calls) == (2, 1)
    assert sleeps == []


def test_when_every_key_is_cooling_it_waits_for_the_shortest_cooldown() -> None:
    clients = [
        FakeClient(status_error(openai.RateLimitError, 429, **{"retry-after": "9"}), reply()),
        FakeClient(status_error(openai.RateLimitError, 429, **{"retry-after": "4"}), reply()),
    ]
    provider, sleeps, _ = make(clients)
    assert ask(provider) == Proposal(value="ok")
    assert sleeps == [pytest.approx(4)]  # waited for key#2, the sooner of the two
    assert (clients[0].calls, clients[1].calls) == (1, 2)


def test_every_key_exhausted_is_an_explicit_quota_error_without_leaking_keys() -> None:
    daily = status_error(openai.RateLimitError, 429, **{"retry-after": "86400"})
    provider, _, _ = make([FakeClient(daily), FakeClient(daily)])
    with pytest.raises(ModelQuotaError) as caught:
        ask(provider)
    text = str(caught.value) + repr(provider.key_reports())
    assert "key#1 exhausted" in text and "key#2 exhausted" in text
    assert not any(key in text for key in KEYS)


def test_every_key_rejected_is_an_authentication_error() -> None:
    bad = status_error(openai.AuthenticationError, 401)
    provider, _, _ = make([FakeClient(bad), FakeClient(bad)])
    with pytest.raises(ModelAuthenticationError):
        ask(provider)


def test_timeouts_are_retried_on_the_same_key_then_the_next_key_takes_over() -> None:
    request = httpx.Request("POST", "https://groq.invalid/openai/v1/chat/completions")
    timeout = openai.APITimeoutError(request=request)
    clients = [FakeClient(timeout), FakeClient(reply())]
    provider, sleeps, _ = make(clients, retries=2)
    assert ask(provider) == Proposal(value="ok")
    assert clients[0].calls == 3  # first try + 2 retries
    assert clients[1].calls == 1
    assert sleeps == [2, 4]  # bounded backoff between the same-key retries


def test_server_errors_on_every_key_surface_as_a_provider_error() -> None:
    boom = status_error(openai.InternalServerError, 503)
    provider, _, _ = make([FakeClient(boom), FakeClient(boom)], retries=0)
    with pytest.raises(ModelProviderError) as caught:
        ask(provider)
    assert not isinstance(caught.value, ModelQuotaError)


def test_a_bad_request_is_not_failed_over_because_it_would_fail_everywhere() -> None:
    clients = [FakeClient(status_error(openai.BadRequestError, 400)), FakeClient(reply())]
    provider, _, _ = make(clients)
    with pytest.raises(ModelProviderError, match="HTTP 400"):
        ask(provider)
    assert clients[1].calls == 0
    assert [r.state for r in provider.key_reports()] == ["active", "active"]


def test_malformed_and_truncated_replies_are_not_failed_over() -> None:
    clients = [FakeClient(reply("not json at all")), FakeClient(reply())]
    provider, _, _ = make(clients)
    with pytest.raises(ModelMalformedResponseError):
        ask(provider)
    assert clients[1].calls == 0

    clients = [FakeClient(reply('{"value": "cut', finish="length")), FakeClient(reply())]
    provider, _, _ = make(clients)
    with pytest.raises(ModelTruncationError):
        ask(provider)
    assert clients[1].calls == 0


def test_reasoning_blocks_and_code_fences_are_tolerated() -> None:
    assert parse_structured('<think>hmm {"x":1}</think>{"value": "a"}', Proposal).value == "a"
    assert parse_structured('```json\n{"value": "b"}\n```', Proposal).value == "b"
    with pytest.raises(ModelMalformedResponseError):
        parse_structured('{"value": 3, "extra": true}', Proposal)


def test_images_are_sent_as_data_urls_and_the_schema_is_in_the_system_prompt() -> None:
    client = FakeClient(reply())
    provider, _, _ = make([client])
    image = ModelImageInput(content=b"\x89PNG-bytes", mime_type="image/png", sha256="a" * 64)
    ask(provider, images=[image])
    system, user = client.last_kwargs["messages"]
    assert '"value"' in system["content"] and "JSON" in system["content"]
    parts = user["content"]
    assert parts[0] == {"type": "text", "text": "Say ok"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_per_key_usage_is_tracked_for_the_report() -> None:
    clients = [
        FakeClient(status_error(openai.AuthenticationError, 401)),
        FakeClient(reply(tokens=(20, 6))),
    ]
    provider, _, _ = make(clients)
    ask(provider)
    first, second = provider.key_reports()
    assert (first.state, first.successes) == ("rejected", 0)
    assert (second.successes, second.input_tokens, second.output_tokens) == (1, 20, 6)


def test_check_keys_reports_each_key_and_whether_the_model_exists() -> None:
    clients = [
        FakeClient(models=["other", "test-model"]),
        FakeClient(models=status_error(openai.AuthenticationError, 401)),
        FakeClient(models=status_error(openai.RateLimitError, 429, **{"retry-after": "3"})),
        FakeClient(models=["other"]),
    ]
    provider, _, _ = make(clients)
    checks = provider.check_keys()
    assert [(c.label, c.status, c.model_available) for c in checks] == [
        ("key#1", "ok", True),
        ("key#2", "rejected", None),
        ("key#3", "rate_limited", None),
        ("key#4", "ok", False),
    ]


def test_provider_refuses_a_non_groq_configuration() -> None:
    with pytest.raises(ValueError):
        GroqModelProvider(Settings(_env_file=None))
