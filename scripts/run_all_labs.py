#!/usr/bin/env python3
"""
🧪 AI Gateway — Hands-On Labs Automation Runner

Runs ALL hands-on lab experiments (Phase 1–2) programmatically against the
ai-gateway API server and generates updated markdown documentation with
real results for each environment (local, aws, azure).

Usage:
    # Run against local server (default):
    python scripts/run_all_labs.py

    # Run against AWS-deployed server:
    python scripts/run_all_labs.py --env aws --base-url https://your-aws-api.com

    # Dry-run (show what would be executed, no API calls):
    python scripts/run_all_labs.py --dry-run

    # Only run a specific experiment:
    python scripts/run_all_labs.py --only 1a,2b,3a

What it does:
    1. Hits the chat/completions, embeddings, usage, health, and models endpoints
    2. Captures all scores, latencies, answers, cache behaviour, and metadata
    3. Generates 2 markdown files (one per phase) with results filled in
    4. Creates a summary JSON file with all raw results

Note: This script does NOT modify the original hands-on lab docs in-place.
      It generates new files in scripts/lab_results/<env>/ so you can review first.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8100"
DEFAULT_TIMEOUT = 120  # seconds (LLM calls can be slow on local)
SERVER_RECOVERY_MAX_WAIT = 120  # seconds to wait for server to come back after crash
SERVER_RECOVERY_INTERVAL = 5   # seconds between health check retries


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExperimentResult:
    """Result of a single experiment."""

    experiment_id: str
    phase: int
    lab: int
    description: str
    status: str = "not_run"  # "success", "failed", "error", "skipped", "not_run"
    # API response data
    question: str | None = None
    answer: str | None = None
    model: str | None = None
    cache_hit: bool | None = None
    latency_ms: float | None = None
    status_code: int | None = None
    tokens_total: int | None = None
    embedding_dimensions: int | None = None
    # Rate limiting
    rate_limited: bool | None = None
    # Usage / cost tracking
    total_requests: int | None = None
    total_tokens: int | None = None
    cache_hit_rate: float | None = None
    # Health check
    health_status: str | None = None
    components: dict | None = None
    # Metadata
    request_id: str | None = None
    cloud_provider: str | None = None
    error_message: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class LabSuite:
    """Collection of all experiment results."""

    environment: str
    base_url: str
    started_at: str = ""
    finished_at: str = ""
    results: list[ExperimentResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _wait_for_server(base_url: str, context: str = "") -> bool:
    """Wait for the server to become healthy again after a crash."""
    label = f" (after {context})" if context else ""
    print(f"\n    🔄 Server unreachable{label} — waiting for recovery...", flush=True)
    elapsed = 0
    while elapsed < SERVER_RECOVERY_MAX_WAIT:
        time.sleep(SERVER_RECOVERY_INTERVAL)
        elapsed += SERVER_RECOVERY_INTERVAL
        try:
            resp = httpx.get(f"{base_url}/health", timeout=5)
            if resp.status_code == 200:
                print(f"    ✅ Server recovered after {elapsed}s", flush=True)
                return True
        except Exception:
            pass
        print(f"    ⏳ Still waiting... ({elapsed}s / {SERVER_RECOVERY_MAX_WAIT}s)", flush=True)
    print(f"    ❌ Server did not recover within {SERVER_RECOVERY_MAX_WAIT}s", flush=True)
    return False


def _is_connection_error(e: Exception) -> bool:
    """Check if an exception is a server connection/crash error."""
    msg = str(e).lower()
    return any(pattern in msg for pattern in [
        "connection refused", "server disconnected", "connection reset",
        "connection closed", "remotedisconnected", "broken pipe", "eof occurred",
    ])


def chat_completion(
    client: httpx.Client,
    message: str,
    *,
    bypass_cache: bool = False,
    request_id: str | None = None,
    _base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Send a chat completion request."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if request_id:
        headers["X-Request-ID"] = request_id

    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": message}],
    }
    if bypass_cache:
        body["bypass_cache"] = True

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            start = time.monotonic()
            resp = client.post("/v1/chat/completions", json=body, headers=headers)
            elapsed_ms = (time.monotonic() - start) * 1000

            data = resp.json() if resp.status_code == 200 else {}
            data["_status_code"] = resp.status_code
            data["_elapsed_ms"] = elapsed_ms
            data["_request_id"] = resp.headers.get("X-Request-ID", "")
            data["_latency_header"] = resp.headers.get("X-Gateway-Latency-Ms", "")
            return data
        except Exception as e:
            if _is_connection_error(e) and attempt < max_retries:
                if _wait_for_server(_base_url, context=f"chat_completion attempt {attempt + 1}"):
                    continue
            raise


def get_embeddings(
    client: httpx.Client,
    texts: str | list[str],
    _base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Send an embeddings request."""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            start = time.monotonic()
            resp = client.post(
                "/v1/embeddings",
                json={"input": texts},
                headers={"Content-Type": "application/json"},
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            data = resp.json() if resp.status_code == 200 else {}
            data["_status_code"] = resp.status_code
            data["_elapsed_ms"] = elapsed_ms
            return data
        except Exception as e:
            if _is_connection_error(e) and attempt < max_retries:
                if _wait_for_server(_base_url, context=f"get_embeddings attempt {attempt + 1}"):
                    continue
            raise


def get_health(
    client: httpx.Client,
    _base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Check health endpoint."""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = client.get("/health")
            return resp.json() if resp.status_code == 200 else {"status": "unreachable"}
        except Exception as e:
            if _is_connection_error(e) and attempt < max_retries:
                if _wait_for_server(_base_url, context=f"get_health attempt {attempt + 1}"):
                    continue
            raise


def get_usage(
    client: httpx.Client,
    period: str = "today",
    _base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Query usage dashboard."""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = client.get(f"/v1/usage?period={period}")
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            if _is_connection_error(e) and attempt < max_retries:
                if _wait_for_server(_base_url, context=f"get_usage attempt {attempt + 1}"):
                    continue
            raise


def get_models(
    client: httpx.Client,
    _base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """List available models."""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = client.get("/v1/models")
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            if _is_connection_error(e) and attempt < max_retries:
                if _wait_for_server(_base_url, context=f"get_models attempt {attempt + 1}"):
                    continue
            raise


# ---------------------------------------------------------------------------
# Experiment definitions
# ---------------------------------------------------------------------------


def run_lab1_first_request(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 1: First Request Through the Gateway."""
    results = []

    # 1a — Basic chat completion
    r = ExperimentResult("1a", phase=1, lab=1, description="First chat completion request")
    try:
        data = chat_completion(client, "What is the capital of the Netherlands?")
        r.status_code = data["_status_code"]
        r.latency_ms = round(data["_elapsed_ms"], 1)
        r.request_id = data.get("_request_id")
        if r.status_code == 200:
            r.status = "success"
            r.model = data.get("model", "")
            r.answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            r.cache_hit = data.get("cache_hit", False)
            usage = data.get("usage", {})
            r.tokens_total = usage.get("total_tokens", 0)
            r.notes.append(f"Model: {r.model}")
            r.notes.append(f"Cache hit: {r.cache_hit}")
        else:
            r.status = "failed"
            r.error_message = str(data)
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    # 1b — Verify health endpoint loads
    r2 = ExperimentResult("1b", phase=1, lab=1, description="Health endpoint accessible")
    try:
        health = get_health(client)
        r2.health_status = health.get("status", "unknown")
        r2.status = "success" if r2.health_status in ("healthy", "degraded") else "failed"
        r2.notes.append(f"Status: {r2.health_status}")
    except Exception as e:
        r2.status = "error"
        r2.error_message = str(e)
    results.append(r2)

    # 1c — Verify models endpoint
    r3 = ExperimentResult("1c", phase=1, lab=1, description="Models endpoint returns available models")
    try:
        models = get_models(client)
        model_ids = [m.get("id", "") for m in models.get("data", [])]
        r3.status = "success" if len(model_ids) > 0 else "failed"
        r3.notes.append(f"Models available: {model_ids}")
    except Exception as e:
        r3.status = "error"
        r3.error_message = str(e)
    results.append(r3)

    return results


def run_lab2_cache(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 2: Semantic Cache in Action."""
    results = []
    question = "What is machine learning?"

    # 2a — First request (cache miss)
    r = ExperimentResult("2a", phase=1, lab=2, description="First request — cache MISS")
    try:
        data = chat_completion(client, question)
        r.status_code = data["_status_code"]
        r.latency_ms = round(data["_elapsed_ms"], 1)
        r.cache_hit = data.get("cache_hit", False)
        r.status = "success" if not r.cache_hit else "failed"
        r.notes.append(f"Expected cache_hit=false, got {r.cache_hit}")
        r.notes.append(f"Latency: {r.latency_ms}ms")
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    # 2b — Identical request (exact cache hit)
    r2 = ExperimentResult("2b", phase=1, lab=2, description="Identical request — exact cache HIT")
    try:
        data = chat_completion(client, question)
        r2.status_code = data["_status_code"]
        r2.latency_ms = round(data["_elapsed_ms"], 1)
        r2.cache_hit = data.get("cache_hit", False)
        r2.status = "success" if r2.cache_hit else "failed"
        r2.notes.append(f"Expected cache_hit=true, got {r2.cache_hit}")
        r2.notes.append(f"Latency: {r2.latency_ms}ms (should be <50ms)")
    except Exception as e:
        r2.status = "error"
        r2.error_message = str(e)
    results.append(r2)

    # 2c — Similar request (semantic cache hit)
    r3 = ExperimentResult("2c", phase=1, lab=2, description="Similar request — semantic cache HIT")
    try:
        data = chat_completion(client, "Explain machine learning to me")
        r3.status_code = data["_status_code"]
        r3.latency_ms = round(data["_elapsed_ms"], 1)
        r3.cache_hit = data.get("cache_hit", False)
        r3.status = "success" if r3.cache_hit else "failed"
        r3.notes.append(f"Expected cache_hit=true (semantic), got {r3.cache_hit}")
    except Exception as e:
        r3.status = "error"
        r3.error_message = str(e)
    results.append(r3)

    # 2d — Different request (cache miss)
    r4 = ExperimentResult("2d", phase=1, lab=2, description="Different request — cache MISS")
    try:
        data = chat_completion(client, "What is quantum computing?")
        r4.status_code = data["_status_code"]
        r4.latency_ms = round(data["_elapsed_ms"], 1)
        r4.cache_hit = data.get("cache_hit", False)
        r4.status = "success" if not r4.cache_hit else "failed"
        r4.notes.append(f"Expected cache_hit=false, got {r4.cache_hit}")
    except Exception as e:
        r4.status = "error"
        r4.error_message = str(e)
    results.append(r4)

    # 2e — Bypass cache
    r5 = ExperimentResult("2e", phase=1, lab=2, description="Bypass cache flag")
    try:
        data = chat_completion(client, question, bypass_cache=True)
        r5.status_code = data["_status_code"]
        r5.latency_ms = round(data["_elapsed_ms"], 1)
        r5.cache_hit = data.get("cache_hit", False)
        r5.status = "success" if not r5.cache_hit else "failed"
        r5.notes.append(f"bypass_cache=true → cache_hit={r5.cache_hit}")
    except Exception as e:
        r5.status = "error"
        r5.error_message = str(e)
    results.append(r5)

    return results


def run_lab3_rate_limiting(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 3: Rate Limiting."""
    results = []

    # 3a — Send rapid requests, expect 429 eventually
    r = ExperimentResult("3a", phase=1, lab=3, description="Rate limiting — expect 429 after limit")
    try:
        statuses = []
        for i in range(7):
            data = chat_completion(client, f"Count to {i + 1}")
            statuses.append(data["_status_code"])
            time.sleep(0.3)

        has_429 = 429 in statuses
        r.status = "success" if has_429 else "failed"
        r.rate_limited = has_429
        r.notes.append(f"Status codes: {statuses}")
        r.notes.append(f"Rate limited: {has_429}")
        if not has_429:
            r.notes.append("Rate limit may be set higher than 7 req/min. Try RATE_LIMIT_REQUESTS_PER_MINUTE=5")
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    return results


def run_lab4_embeddings(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 4: Embeddings Endpoint."""
    results = []

    # 4a — Single embedding
    r = ExperimentResult("4a", phase=1, lab=4, description="Single text embedding")
    try:
        data = get_embeddings(client, "Machine learning is a subset of artificial intelligence.")
        r.status_code = data["_status_code"]
        r.latency_ms = round(data["_elapsed_ms"], 1)
        if r.status_code == 200 and data.get("data"):
            embedding = data["data"][0].get("embedding", [])
            r.embedding_dimensions = len(embedding)
            r.model = data.get("model", "")
            r.status = "success"
            r.notes.append(f"Dimensions: {r.embedding_dimensions}")
            r.notes.append(f"Model: {r.model}")
        else:
            r.status = "failed"
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    # 4b — Multiple embeddings (batch)
    r2 = ExperimentResult("4b", phase=1, lab=4, description="Batch embedding (3 texts)")
    try:
        data = get_embeddings(client, ["Hello world", "Machine learning", "Cloud computing"])
        r2.status_code = data["_status_code"]
        if r2.status_code == 200:
            count = len(data.get("data", []))
            r2.status = "success" if count == 3 else "failed"
            r2.notes.append(f"Returned {count} embeddings (expected 3)")
        else:
            r2.status = "failed"
    except Exception as e:
        r2.status = "error"
        r2.error_message = str(e)
    results.append(r2)

    return results


def run_lab5_cost_tracking(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 5: Cost Tracking Dashboard."""
    results = []

    # 5a — Generate usage data then query dashboard
    r = ExperimentResult("5a", phase=2, lab=5, description="Usage dashboard after requests")
    try:
        # Send a few diverse requests first
        for i in range(3):
            chat_completion(client, f"Tell me fact number {i + 1} about AI")
            time.sleep(0.5)
        get_embeddings(client, f"Embedding text for cost tracking")

        data = get_usage(client)
        r.total_requests = data.get("total_requests", 0)
        r.total_tokens = data.get("total_tokens", 0)
        r.cache_hit_rate = data.get("cache_hit_rate", 0.0)
        r.status = "success" if r.total_requests and r.total_requests > 0 else "failed"
        r.notes.append(f"Total requests: {r.total_requests}")
        r.notes.append(f"Total tokens: {r.total_tokens}")
        r.notes.append(f"Cache hit rate: {r.cache_hit_rate}")
        by_model = data.get("by_model", {})
        r.notes.append(f"Models used: {list(by_model.keys())}")
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    return results


def run_lab6_health(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 6: Health Check and Monitoring."""
    results = []

    r = ExperimentResult("6a", phase=2, lab=6, description="Health check — all components")
    try:
        health = get_health(client)
        r.health_status = health.get("status", "unknown")
        r.components = health.get("components", {})
        r.status = "success" if r.health_status in ("healthy", "degraded") else "failed"
        r.notes.append(f"Status: {r.health_status}")
        for comp, state in (r.components or {}).items():
            r.notes.append(f"  {comp}: {state}")
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    return results


def run_lab7_tracing(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 7: Request Tracing and Observability."""
    results = []

    # 7a — Custom request ID echoed back
    r = ExperimentResult("7a", phase=2, lab=7, description="Custom X-Request-ID is echoed back")
    try:
        data = chat_completion(client, "What is Docker?", request_id="test-trace-001")
        r.request_id = data.get("_request_id", "")
        r.latency_ms = round(data["_elapsed_ms"], 1)
        r.status = "success" if r.request_id == "test-trace-001" else "failed"
        r.notes.append(f"Sent: test-trace-001, Got: {r.request_id}")
        r.notes.append(f"Latency header: {data.get('_latency_header', 'missing')}")
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    # 7b — Auto-generated request ID
    r2 = ExperimentResult("7b", phase=2, lab=7, description="Auto-generated request ID")
    try:
        data = chat_completion(client, "What is Kubernetes?")
        r2.request_id = data.get("_request_id", "")
        r2.status = "success" if r2.request_id and len(r2.request_id) > 0 else "failed"
        r2.notes.append(f"Auto-generated ID: {r2.request_id}")
    except Exception as e:
        r2.status = "error"
        r2.error_message = str(e)
    results.append(r2)

    return results


def run_lab8_docker_compose(client: httpx.Client) -> list[ExperimentResult]:
    """Lab 8: Full Docker Compose Stack — integration verification."""
    results = []

    r = ExperimentResult("8a", phase=2, lab=8, description="Full stack integration — health + chat + embed + usage")
    try:
        health = get_health(client)
        chat = chat_completion(client, "Explain Docker Compose briefly")
        embed = get_embeddings(client, "Docker Compose orchestrates containers")
        usage = get_usage(client)

        checks = [
            health.get("status") in ("healthy", "degraded"),
            chat.get("_status_code") == 200,
            embed.get("_status_code") == 200,
        ]
        r.status = "success" if all(checks) else "failed"
        r.health_status = health.get("status")
        r.cache_hit = chat.get("cache_hit")
        r.total_requests = usage.get("total_requests", 0)
        r.notes.append(f"Health: {health.get('status')}")
        r.notes.append(f"Chat: HTTP {chat.get('_status_code')}, cache_hit={chat.get('cache_hit')}")
        r.notes.append(f"Embed: HTTP {embed.get('_status_code')}")
        r.notes.append(f"Usage total requests: {usage.get('total_requests', 'N/A')}")
    except Exception as e:
        r.status = "error"
        r.error_message = str(e)
    results.append(r)

    return results


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ALL_LABS: dict[str, Any] = {
    "1": ("Lab 1: First Request", run_lab1_first_request),
    "2": ("Lab 2: Semantic Cache", run_lab2_cache),
    "3": ("Lab 3: Rate Limiting", run_lab3_rate_limiting),
    "4": ("Lab 4: Embeddings", run_lab4_embeddings),
    "5": ("Lab 5: Cost Tracking", run_lab5_cost_tracking),
    "6": ("Lab 6: Health Check", run_lab6_health),
    "7": ("Lab 7: Request Tracing", run_lab7_tracing),
    "8": ("Lab 8: Docker Compose Stack", run_lab8_docker_compose),
}


def run_all(
    base_url: str,
    environment: str,
    *,
    dry_run: bool = False,
    only: list[str] | None = None,
    output_dir: Path | None = None,
) -> LabSuite:
    """Run all experiments and return results."""
    suite = LabSuite(
        environment=environment,
        base_url=base_url,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    client = httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    for lab_id, (lab_name, lab_fn) in ALL_LABS.items():
        if only and lab_id not in only:
            continue

        print(f"\n{'='*60}")
        print(f"  {lab_name}")
        print(f"{'='*60}")

        if dry_run:
            print(f"  [DRY RUN] Would run {lab_name}")
            continue

        try:
            lab_results = lab_fn(client)
            for r in lab_results:
                icon = "✅" if r.status == "success" else "❌" if r.status == "failed" else "⚠️"
                print(f"  {icon} {r.experiment_id}: {r.description} → {r.status}")
                for note in r.notes:
                    print(f"     {note}")
            suite.results.extend(lab_results)
            # Incremental save — per-lab JSON files survive crashes
            if output_dir is not None:
                for r in lab_results:
                    lab_file = output_dir / f"lab-{r.experiment_id}.json"
                    lab_data = {
                        "experiment_id": r.experiment_id,
                        "lab": r.lab,
                        "status": r.status,
                        "passed": r.status == "success",
                        "description": r.description,
                        "latency_ms": r.latency_ms,
                    }
                    lab_file.write_text(json.dumps(lab_data, indent=2))
        except Exception as e:
            print(f"  ❌ {lab_name} crashed: {e}")

    client.close()
    suite.finished_at = datetime.now(timezone.utc).isoformat()
    return suite


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------


def generate_results_markdown(suite: LabSuite) -> str:
    """Generate a markdown summary of all results."""
    lines = [
        f"# AI Gateway — Lab Results ({suite.environment})",
        "",
        f"> **Environment:** {suite.environment}",
        f"> **Base URL:** {suite.base_url}",
        f"> **Run started:** {suite.started_at}",
        f"> **Run finished:** {suite.finished_at}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Experiment | Description | Status | Latency | Notes |",
        "|-----------|-------------|--------|---------|-------|",
    ]

    passed = 0
    failed = 0
    for r in suite.results:
        icon = "✅" if r.status == "success" else "❌" if r.status == "failed" else "⚠️"
        latency = f"{r.latency_ms}ms" if r.latency_ms else "—"
        notes_str = "; ".join(r.notes[:2]) if r.notes else "—"
        lines.append(f"| {r.experiment_id} | {r.description} | {icon} {r.status} | {latency} | {notes_str} |")
        if r.status == "success":
            passed += 1
        else:
            failed += 1

    lines.extend([
        "",
        f"**Total: {passed} passed, {failed} failed out of {len(suite.results)} experiments**",
        "",
    ])

    return "\n".join(lines)


def save_results(suite: LabSuite, output_dir: Path) -> None:
    """Save results to markdown and JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Markdown summary
    md = generate_results_markdown(suite)
    (output_dir / "full-summary.md").write_text(md)
    print(f"\n📄 Markdown summary: {output_dir / 'full-summary.md'}")

    # Raw JSON
    raw = json.dumps([asdict(r) for r in suite.results], indent=2, default=str)
    (output_dir / "raw-results.json").write_text(raw)
    print(f"📄 Raw JSON: {output_dir / 'raw-results.json'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Gateway — Lab Runner")
    parser.add_argument("--env", default="local", choices=["local", "aws", "azure"])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="Comma-separated lab numbers, e.g. 1,2,4")
    args = parser.parse_args()

    only = args.only.split(",") if args.only else None

    print(f"🧪 AI Gateway Lab Runner")
    print(f"   Environment: {args.env}")
    print(f"   Base URL:    {args.base_url}")
    print(f"   Dry run:     {args.dry_run}")
    if only:
        print(f"   Only labs:   {only}")

    if not args.dry_run:
        output_dir = Path(__file__).parent / "lab_results" / args.env
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = None

    suite = run_all(args.base_url, args.env, dry_run=args.dry_run, only=only, output_dir=output_dir)

    if not args.dry_run:
        save_results(suite, output_dir)

        passed = sum(1 for r in suite.results if r.status == "success")
        total = len(suite.results)
        print(f"\n🏁 Done: {passed}/{total} passed")
        sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
