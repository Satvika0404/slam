"""Environment-only runtime configuration with safe offline defaults."""

import re
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_KEY_SEPARATORS = re.compile(r"[,;\s]+")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_safe_base_url(url: str) -> bool:
    """Keys travel to this URL, so require TLS; plain http only for a real loopback host."""

    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme == "https":
        return bool(host)
    return parts.scheme == "http" and host in _LOOPBACK_HOSTS


class ProviderName(StrEnum):
    FAKE = "fake"
    OPENAI = "openai"
    GROQ = "groq"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        # A validation error would otherwise print the raw environment values, API keys included.
        hide_input_in_errors=True,
    )

    model_provider: ProviderName = Field(
        default=ProviderName.FAKE, validation_alias="SLAM_MODEL_PROVIDER"
    )
    model: str = Field(default="fake-structured-v1", validation_alias="SLAM_MODEL")
    api_timeout_seconds: int = Field(
        default=60, ge=1, le=600, validation_alias="SLAM_API_TIMEOUT_SECONDS"
    )
    api_max_retries: int = Field(
        default=2, ge=0, le=2, validation_alias="SLAM_API_MAX_RETRIES"
    )
    api_max_concurrency: int = Field(
        default=4, ge=1, le=32, validation_alias="SLAM_API_MAX_CONCURRENCY"
    )
    api_budget_usd: Decimal = Field(
        default=Decimal("0"), ge=0, validation_alias="SLAM_API_BUDGET_USD"
    )
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    # Groq speaks the OpenAI wire format. Several keys may be listed (comma, semicolon or
    # whitespace separated); they are tried strictly in order, see ``runtime.key_pool``.
    groq_api_keys: SecretStr | None = Field(default=None, validation_alias="GROQ_API_KEYS")
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1", validation_alias="GROQ_BASE_URL"
    )
    # Hard ceilings enforced by ``runtime.metering.MeteredProvider`` (0 = not set).
    api_max_calls: int = Field(default=0, ge=0, le=100_000, validation_alias="SLAM_API_MAX_CALLS")
    api_max_tokens: int = Field(
        default=0, ge=0, le=100_000_000, validation_alias="SLAM_API_MAX_TOKENS"
    )
    api_max_output_tokens: int = Field(
        default=4096, ge=64, le=32_768, validation_alias="SLAM_API_MAX_OUTPUT_TOKENS"
    )
    # Per million tokens, only used to estimate cost (0 = free tier or price not supplied).
    price_input_per_mtok_usd: Decimal = Field(
        default=Decimal("0"), ge=0, validation_alias="SLAM_PRICE_INPUT_PER_MTOK_USD"
    )
    price_output_per_mtok_usd: Decimal = Field(
        default=Decimal("0"), ge=0, validation_alias="SLAM_PRICE_OUTPUT_PER_MTOK_USD"
    )

    @property
    def groq_key_list(self) -> tuple[str, ...]:
        """The configured Groq keys in order, without blanks or duplicates."""

        if self.groq_api_keys is None:
            return ()
        raw = _KEY_SEPARATORS.split(self.groq_api_keys.get_secret_value())
        return tuple(dict.fromkeys(key for key in raw if key))

    @model_validator(mode="after")
    def validate_real_provider_controls(self) -> "Settings":
        if self.model_provider is ProviderName.OPENAI:
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value():
                raise ValueError("OPENAI_API_KEY is required when SLAM_MODEL_PROVIDER=openai")
            if self.api_budget_usd <= 0:
                raise ValueError("a positive SLAM_API_BUDGET_USD is required for API calls")
            if self.model.startswith("fake-"):
                raise ValueError("an explicit non-fake model is required for API calls")
        if self.model_provider is ProviderName.GROQ:
            if not self.groq_key_list:
                raise ValueError("GROQ_API_KEYS is required when SLAM_MODEL_PROVIDER=groq")
            if self.api_max_calls <= 0:
                raise ValueError("a positive SLAM_API_MAX_CALLS is required for API calls")
            if self.model.startswith("fake-"):
                raise ValueError("an explicit non-fake model is required for API calls")
            if not _is_safe_base_url(self.groq_base_url):
                raise ValueError("GROQ_BASE_URL must use https (loopback http is for local tests)")
            if self.api_budget_usd > 0 and not (
                self.price_input_per_mtok_usd > 0 or self.price_output_per_mtok_usd > 0
            ):
                raise ValueError(
                    "SLAM_API_BUDGET_USD can only be enforced when a SLAM_PRICE_*_PER_MTOK_USD "
                    "is set; use SLAM_API_MAX_CALLS or SLAM_API_MAX_TOKENS otherwise"
                )
        return self
