"""In-memory usage ledger and a metering wrapper that enforces hard ceilings.

Nothing here logs a secret or prompt content.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from slam.runtime.key_pool import KeyReport
from slam.runtime.provider import (
    ModelAuthenticationError,
    ModelBudgetError,
    ModelCallMetadata,
    ModelImageInput,
    ModelProvider,
    ModelProviderError,
    ModelQuotaError,
    ModelResult,
    StructuredT,
)


@dataclass(slots=True)
class UsageLedger:
    calls: list[ModelCallMetadata] = field(default_factory=list)

    def record(self, metadata: ModelCallMetadata) -> None:
        self.calls.append(metadata)

    def summary(self) -> dict[str, int | None]:
        actual = [call for call in self.calls if not call.cache_hit]
        cache_hits = len(self.calls) - len(actual)

        def total(name: str) -> int | None:
            values = [getattr(call.usage, name) for call in actual]
            known = [value for value in values if value is not None]
            return sum(known) if len(known) == len(values) else None

        return {
            "actual_calls": len(actual),
            "cache_hits": cache_hits,
            "retries": sum(call.retries for call in actual),
            "latency_ms": sum(call.latency_ms for call in actual),
            "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"),
            "cached_input_tokens": total("cached_input_tokens"),
            "reasoning_tokens": total("reasoning_tokens"),
        }


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per million tokens. Zero means free tier or a price nobody supplied."""

    input_per_mtok: Decimal = Decimal(0)
    output_per_mtok: Decimal = Decimal(0)

    @property
    def known(self) -> bool:
        return self.input_per_mtok > 0 or self.output_per_mtok > 0

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        total = Decimal(input_tokens) * self.input_per_mtok
        total += Decimal(output_tokens) * self.output_per_mtok
        return total / Decimal(1_000_000)


class MeteredProvider:
    """Wrap a provider: record every call and refuse to start one past a hard ceiling.

    Ceilings are checked before a call, so the last call can overshoot a token or cost ceiling by
    its own size (bounded by ``SLAM_API_MAX_OUTPUT_TOKENS`` plus the prompt). The call ceiling is
    exact and counts logical calls, one per ``generate()``, failed ones included since a failed
    call can still be billed. The HTTP requests a single call makes while failing over between
    keys (rate-limited ones, retries) are bounded per call and shown per key in the usage report;
    they do not count against this ceiling.
    """

    def __init__(
        self,
        inner: ModelProvider,
        ledger: UsageLedger,
        *,
        max_calls: int = 0,
        max_tokens: int = 0,
        budget_usd: Decimal = Decimal(0),
        price: ModelPrice | None = None,
    ) -> None:
        self._inner = inner
        self.ledger = ledger
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.budget_usd = budget_usd
        self.price = price or ModelPrice()
        self.attempted_calls = 0
        self.failed_calls = 0
        self.unknown_usage_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.fatal: str | None = None  # set once no further call can succeed

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> Decimal | None:
        """Estimated spend, or ``None`` when no price was supplied (free tier or unknown)."""

        if not self.price.known:
            return None
        return self.price.cost(self.input_tokens, self.output_tokens)

    def key_reports(self) -> tuple[KeyReport, ...]:
        reports = getattr(self._inner, "key_reports", None)
        return tuple(reports()) if callable(reports) else ()

    def _ceiling_reached(self) -> str | None:
        if self.max_calls > 0 and self.attempted_calls >= self.max_calls:
            return f"call ceiling reached ({self.max_calls})"
        if self.max_tokens > 0 and self.total_tokens >= self.max_tokens:
            return f"token ceiling reached ({self.max_tokens})"
        cost = self.cost_usd
        if self.budget_usd > 0 and cost is not None and cost >= self.budget_usd:
            return f"budget ceiling reached (${self.budget_usd})"
        return None

    def generate(
        self,
        *,
        prompt: str,
        prompt_version: str,
        response_model: type[StructuredT],
        images: Sequence[ModelImageInput] = (),
    ) -> ModelResult[StructuredT]:
        reason = self._ceiling_reached()
        if reason is not None:
            self.fatal = "ModelBudgetError"
            raise ModelBudgetError(reason)
        self.attempted_calls += 1
        try:
            result = self._inner.generate(
                prompt=prompt,
                prompt_version=prompt_version,
                response_model=response_model,
                images=images,
            )
        except ModelProviderError as exc:
            self.failed_calls += 1
            if isinstance(exc, ModelQuotaError | ModelAuthenticationError):
                self.fatal = type(exc).__name__
            raise
        self.ledger.record(result.metadata)
        usage = result.metadata.usage
        if usage.input_tokens is None or usage.output_tokens is None:
            self.unknown_usage_calls += 1
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        return result
