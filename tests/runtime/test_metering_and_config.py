"""Hard ceilings, usage accounting, the provider factory and real-provider configuration."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError
from slam.config import ProviderName, Settings
from slam.runtime.factory import build_provider
from slam.runtime.fake_provider import FakeModelProvider
from slam.runtime.groq_provider import GroqModelProvider
from slam.runtime.metering import MeteredProvider, ModelPrice, UsageLedger
from slam.runtime.provider import (
    ModelBudgetError,
    ModelCallMetadata,
    ModelImageInput,
    ModelProviderError,
    ModelQuotaError,
    ModelResult,
    ModelUsage,
    StructuredT,
)

SECRET = "never-print-this-" + "k" * 16


class Proposal(BaseModel):
    value: str


class Tokens:
    """A provider reporting fixed token counts, or failing on demand."""

    name = "stub"
    model = "stub-model"

    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.usage = ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        self.fail_with: Exception | None = None

    def generate(
        self,
        *,
        prompt: str,
        prompt_version: str,
        response_model: type[StructuredT],
        images: Sequence[ModelImageInput] = (),
    ) -> ModelResult[StructuredT]:
        del prompt, images
        if self.fail_with is not None:
            raise self.fail_with
        metadata = ModelCallMetadata(
            provider=self.name,
            model=self.model,
            request_id=None,
            prompt_version=prompt_version,
            schema_name=response_model.__name__,
            latency_ms=1,
            retries=0,
            cache_hit=False,
            usage=self.usage,
        )
        return ModelResult(response_model.model_validate({"value": "x"}), metadata)


def call(provider: MeteredProvider) -> None:
    provider.generate(prompt="p", prompt_version="v1", response_model=Proposal)


def test_call_ceiling_is_exact_and_stops_before_the_extra_call() -> None:
    inner = Tokens()
    metered = MeteredProvider(inner, UsageLedger(), max_calls=3)
    for _ in range(3):
        call(metered)
    with pytest.raises(ModelBudgetError, match="call ceiling"):
        call(metered)
    assert metered.attempted_calls == 3
    assert metered.fatal == "ModelBudgetError"
    assert len(metered.ledger.calls) == 3


def test_failed_attempts_count_against_the_ceiling_and_are_recorded() -> None:
    inner = Tokens()
    inner.fail_with = ModelProviderError("down")
    metered = MeteredProvider(inner, UsageLedger(), max_calls=2)
    for _ in range(2):
        with pytest.raises(ModelProviderError):
            call(metered)
    with pytest.raises(ModelBudgetError):
        call(metered)
    assert (metered.attempted_calls, metered.failed_calls) == (2, 2)
    assert metered.ledger.calls == []


def test_quota_errors_mark_the_provider_fatal_so_callers_stop() -> None:
    inner = Tokens()
    inner.fail_with = ModelQuotaError("all keys used up")
    metered = MeteredProvider(inner, UsageLedger(), max_calls=10)
    with pytest.raises(ModelQuotaError):
        call(metered)
    assert metered.fatal == "ModelQuotaError"


def test_token_ceiling_blocks_the_next_call_once_reached() -> None:
    metered = MeteredProvider(Tokens(100, 50), UsageLedger(), max_calls=50, max_tokens=300)
    call(metered)
    call(metered)  # 300 used
    with pytest.raises(ModelBudgetError, match="token ceiling"):
        call(metered)
    assert metered.total_tokens == 300


def test_cost_is_estimated_only_when_a_price_exists_and_can_cap_spend() -> None:
    free = MeteredProvider(Tokens(), UsageLedger(), max_calls=5)
    call(free)
    assert free.cost_usd is None  # no price supplied: never invent a dollar figure

    price = ModelPrice(Decimal("2"), Decimal("4"))  # per million tokens
    priced = MeteredProvider(
        Tokens(500_000, 250_000), UsageLedger(), max_calls=5, budget_usd=Decimal("1.5"), price=price
    )
    call(priced)
    assert priced.cost_usd == Decimal("2.0")  # 0.5M*2 + 0.25M*4
    with pytest.raises(ModelBudgetError, match="budget ceiling"):
        call(priced)


def test_missing_token_counts_are_flagged_instead_of_guessed() -> None:
    inner = Tokens()
    inner.usage = ModelUsage(input_tokens=None, output_tokens=None)
    metered = MeteredProvider(inner, UsageLedger(), max_calls=5)
    call(metered)
    assert metered.unknown_usage_calls == 1
    assert metered.total_tokens == 0


def test_fake_provider_can_be_metered_too() -> None:
    metered = MeteredProvider(FakeModelProvider([{"value": "a"}]), UsageLedger(), max_calls=1)
    call(metered)
    assert metered.key_reports() == ()  # no key pool behind a fake provider
    assert metered.ledger.summary()["actual_calls"] == 1


def groq_settings(**overrides: str) -> Settings:
    values = {
        "SLAM_MODEL_PROVIDER": "groq",
        "SLAM_MODEL": "some-model",
        "GROQ_API_KEYS": f"{SECRET}1, {SECRET}2\n{SECRET}3;{SECRET}1",
        "SLAM_API_MAX_CALLS": "25",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_groq_keys_are_split_deduplicated_and_kept_in_order() -> None:
    settings = groq_settings()
    assert settings.groq_key_list == (f"{SECRET}1", f"{SECRET}2", f"{SECRET}3")


def test_secrets_never_appear_in_settings_repr() -> None:
    settings = groq_settings()
    assert SECRET not in repr(settings) + str(settings) + repr(settings.model_dump())


@pytest.mark.parametrize(
    "overrides",
    [
        {"GROQ_API_KEYS": " , "},  # no key
        {"SLAM_API_MAX_CALLS": "0"},  # no hard call ceiling
        {"SLAM_MODEL": "fake-structured-v1"},  # no explicit model
        {"GROQ_BASE_URL": "http://api.example.invalid/v1"},  # not https
        {"SLAM_API_BUDGET_USD": "1"},  # a dollar cap with no price cannot be enforced
    ],
)
def test_groq_configuration_rejects_unsafe_or_unenforceable_settings(
    overrides: dict[str, str],
) -> None:
    with pytest.raises(ValidationError) as caught:
        groq_settings(**overrides)
    assert SECRET not in str(caught.value)


def test_loopback_http_is_allowed_for_local_test_servers_only() -> None:
    assert groq_settings(GROQ_BASE_URL="http://127.0.0.1:8099/openai/v1")
    with pytest.raises(ValidationError):
        groq_settings(GROQ_BASE_URL="http://127.0.0.1.evil.example/openai/v1")


def test_a_dollar_cap_is_accepted_when_a_price_is_given() -> None:
    settings = groq_settings(SLAM_API_BUDGET_USD="1", SLAM_PRICE_INPUT_PER_MTOK_USD="0.1")
    assert settings.api_budget_usd == Decimal(1)


def test_factory_builds_a_capped_groq_provider_and_nothing_for_the_fake() -> None:
    assert build_provider(Settings(_env_file=None), UsageLedger()) is None

    settings = groq_settings(SLAM_API_MAX_TOKENS="9000", SLAM_PRICE_OUTPUT_PER_MTOK_USD="0.5")
    ledger = UsageLedger()
    metered = build_provider(settings, ledger)
    assert isinstance(metered, MeteredProvider)
    assert (metered.name, metered.model) == ("groq", "some-model")
    assert (metered.max_calls, metered.max_tokens) == (25, 9000)
    assert metered.price.known and metered.ledger is ledger
    assert len(metered.key_reports()) == 3
    assert settings.model_provider is ProviderName.GROQ
    assert isinstance(GroqModelProvider(settings), GroqModelProvider)
