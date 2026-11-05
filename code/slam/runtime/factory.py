"""Build the configured model provider, metered and capped, or ``None`` for the offline default."""

from __future__ import annotations

from slam.config import ProviderName, Settings
from slam.runtime.metering import MeteredProvider, ModelPrice, UsageLedger
from slam.runtime.provider import ModelProvider


def build_provider(settings: Settings, ledger: UsageLedger) -> MeteredProvider | None:
    """Return a metered provider for a real API, ``None`` for the fake (offline) provider.

    A real provider is never returned without a call ceiling: it is the one limit that holds
    exactly, whatever the pricing or free-tier rules of the API are.
    """

    if settings.model_provider is ProviderName.FAKE:
        return None
    if settings.api_max_calls <= 0:
        raise ValueError("a positive SLAM_API_MAX_CALLS is required for API calls")

    inner: ModelProvider
    if settings.model_provider is ProviderName.GROQ:
        from slam.runtime.groq_provider import GroqModelProvider

        inner = GroqModelProvider(settings)
    else:
        from slam.runtime.openai_provider import OpenAIModelProvider

        inner = OpenAIModelProvider(settings)
    return MeteredProvider(
        inner,
        ledger,
        max_calls=settings.api_max_calls,
        max_tokens=settings.api_max_tokens,
        budget_usd=settings.api_budget_usd,
        price=ModelPrice(settings.price_input_per_mtok_usd, settings.price_output_per_mtok_usd),
    )
