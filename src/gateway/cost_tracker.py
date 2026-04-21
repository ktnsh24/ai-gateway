"""
AI Gateway — Cost Tracker (PostgreSQL)

Logs every LLM request with token counts, cost estimates, latency, and provider info.
Enables cost dashboards and per-team/per-model cost allocation.

Schema:
    usage_logs table:
        id, request_id, api_key, model, provider, prompt_tokens, completion_tokens,
        total_tokens, estimated_cost_usd, latency_ms, cached, created_at

LiteLLM provides automatic cost estimation for most providers. This module
stores that data in PostgreSQL for querying and dashboards.

See docs/ai-engineering/cost-tracking-deep-dive.md for detailed explanation.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from loguru import logger

from src.config import Settings


class BaseCostTracker(ABC):
    """Abstract base class for cost tracking."""

    @abstractmethod
    async def log_request(
        self,
        request_id: str,
        api_key: str,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float,
        latency_ms: float,
        cached: bool = False,
    ) -> None:
        """Log a completed request."""

    @abstractmethod
    async def get_usage_summary(
        self,
        api_key: str | None = None,
        period: str = "today",
    ) -> dict:
        """Get usage summary for a period."""


class PostgresCostTracker(BaseCostTracker):
    """PostgreSQL-backed cost tracker using SQLAlchemy async.

    Stores every request in a `usage_logs` table. Supports aggregation
    queries for dashboards (total cost, cost per model, cache hit rate).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = None

    async def _get_engine(self):
        """Lazy-init SQLAlchemy async engine."""
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(
                self._settings.database_url,
                echo=self._settings.debug,
                pool_size=5,
                max_overflow=10,
            )
            await self._create_tables()
        return self._engine

    async def _create_tables(self) -> None:
        """Create the usage_logs table if it doesn't exist."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = self._engine
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    request_id VARCHAR(64) NOT NULL,
                    api_key VARCHAR(128) NOT NULL,
                    model VARCHAR(256) NOT NULL,
                    provider VARCHAR(32) NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    estimated_cost_usd NUMERIC(10, 6) DEFAULT 0,
                    latency_ms NUMERIC(10, 2) DEFAULT 0,
                    cached BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_usage_logs_api_key
                ON usage_logs (api_key, created_at)
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_usage_logs_created
                ON usage_logs (created_at)
            """))

    async def log_request(
        self,
        request_id: str,
        api_key: str,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float,
        latency_ms: float,
        cached: bool = False,
    ) -> None:
        """Log a completed request to PostgreSQL."""
        engine = await self._get_engine()
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO usage_logs
                        (request_id, api_key, model, provider, prompt_tokens,
                         completion_tokens, total_tokens, estimated_cost_usd,
                         latency_ms, cached)
                    VALUES
                        (:request_id, :api_key, :model, :provider, :prompt_tokens,
                         :completion_tokens, :total_tokens, :estimated_cost_usd,
                         :latency_ms, :cached)
                """),
                {
                    "request_id": request_id,
                    "api_key": api_key[:32],
                    "model": model,
                    "provider": provider,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "latency_ms": latency_ms,
                    "cached": cached,
                },
            )
        logger.debug(f"Logged usage: model={model}, cost=${estimated_cost_usd:.6f}")

    async def get_usage_summary(
        self,
        api_key: str | None = None,
        period: str = "today",
    ) -> dict:
        """Get usage summary from PostgreSQL."""
        engine = await self._get_engine()
        from sqlalchemy import text

        # Calculate time boundary
        now = datetime.now(timezone.utc)
        if period == "today":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            since = now - timedelta(days=7)
        elif period == "month":
            since = now - timedelta(days=30)
        else:
            since = now - timedelta(days=1)

        params = {"since": since}
        key_filter = ""
        if api_key:
            key_filter = "AND api_key = :api_key"
            params["api_key"] = api_key[:32]

        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT
                        COUNT(*) AS total_requests,
                        COALESCE(SUM(total_tokens), 0) AS total_tokens,
                        COALESCE(SUM(estimated_cost_usd), 0) AS total_cost,
                        COALESCE(AVG(latency_ms), 0) AS avg_latency,
                        COALESCE(
                            SUM(CASE WHEN cached THEN 1 ELSE 0 END)::float /
                            NULLIF(COUNT(*), 0), 0
                        ) AS cache_hit_rate
                    FROM usage_logs
                    WHERE created_at >= :since {key_filter}
                """),
                params,
            )
            row = result.fetchone()

            # Get breakdown by model
            model_result = await conn.execute(
                text(f"""
                    SELECT model, COUNT(*) AS count
                    FROM usage_logs
                    WHERE created_at >= :since {key_filter}
                    GROUP BY model
                    ORDER BY count DESC
                """),
                params,
            )
            models = {r[0]: r[1] for r in model_result.fetchall()}

            # Get breakdown by provider
            provider_result = await conn.execute(
                text(f"""
                    SELECT provider, COALESCE(SUM(estimated_cost_usd), 0) AS cost
                    FROM usage_logs
                    WHERE created_at >= :since {key_filter}
                    GROUP BY provider
                """),
                params,
            )
            providers = {r[0]: float(r[1]) for r in provider_result.fetchall()}

        return {
            "period": period,
            "total_requests": row[0],
            "total_tokens": int(row[1]),
            "total_cost_usd": round(float(row[2]), 6),
            "avg_latency_ms": round(float(row[3]), 2),
            "cache_hit_rate": round(float(row[4]), 4),
            "requests_by_model": models,
            "cost_by_provider": providers,
        }


class InMemoryCostTracker(BaseCostTracker):
    """Simple in-memory cost tracker for local development (no PostgreSQL needed).

    Stores records in a list. Not suitable for production.
    """

    def __init__(self) -> None:
        self._records: list[dict] = []

    async def log_request(
        self,
        request_id: str,
        api_key: str,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float,
        latency_ms: float,
        cached: bool = False,
    ) -> None:
        self._records.append({
            "request_id": request_id,
            "api_key": api_key[:32],
            "model": model,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "latency_ms": latency_ms,
            "cached": cached,
            "created_at": datetime.now(timezone.utc),
        })

    async def get_usage_summary(
        self,
        api_key: str | None = None,
        period: str = "today",
    ) -> dict:
        records = self._records
        if api_key:
            records = [r for r in records if r["api_key"] == api_key[:32]]

        now = datetime.now(timezone.utc)
        if period == "today":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            since = now - timedelta(days=7)
        else:
            since = now - timedelta(days=30)

        records = [r for r in records if r["created_at"] >= since]

        total = len(records)
        tokens = sum(r["total_tokens"] for r in records)
        cost = sum(r["estimated_cost_usd"] for r in records)
        latency = sum(r["latency_ms"] for r in records) / total if total else 0
        cached = sum(1 for r in records if r["cached"])

        models: dict[str, int] = {}
        providers: dict[str, float] = {}
        for r in records:
            models[r["model"]] = models.get(r["model"], 0) + 1
            providers[r["provider"]] = providers.get(r["provider"], 0) + r["estimated_cost_usd"]

        return {
            "period": period,
            "total_requests": total,
            "total_tokens": tokens,
            "total_cost_usd": round(cost, 6),
            "avg_latency_ms": round(latency, 2),
            "cache_hit_rate": round(cached / total, 4) if total else 0.0,
            "requests_by_model": models,
            "cost_by_provider": providers,
        }


class NoCostTracker(BaseCostTracker):
    """No-op cost tracker — used when cost tracking is disabled."""

    async def log_request(self, **kwargs) -> None:
        pass

    async def get_usage_summary(self, **kwargs) -> dict:
        return {"enabled": False}


def create_cost_tracker(settings: Settings) -> BaseCostTracker:
    """Factory method — creates the appropriate cost tracker implementation."""
    if not settings.cost_tracking_enabled:
        logger.info("Cost tracking disabled")
        return NoCostTracker()

    if "localhost" in settings.database_url or "127.0.0.1" in settings.database_url:
        # Try PostgreSQL, fall back to in-memory
        try:
            # Just check if asyncpg can parse the URL
            logger.info("Cost tracker: PostgreSQL (local)")
            return PostgresCostTracker(settings)
        except Exception:
            logger.warning("PostgreSQL not available, falling back to in-memory cost tracker")
            return InMemoryCostTracker()

    logger.info("Cost tracker: PostgreSQL")
    return PostgresCostTracker(settings)
