#!/usr/bin/env python
"""Run a lightweight alpha-capacity smoke against the cloud API in-process."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_app(data_dir: Path):
    os.environ.update(
        {
            "PUSHKEY_DATA_DIR": str(data_dir),
            "PUSHKEY_ADMIN_EMAIL": "admin@example.com",
            "PUSHKEY_ADMIN_PASSWORD": "admin-pass-123",
            "PUSHKEY_ADMIN_COOKIE_SECURE": "false",
            "PUSHKEY_JWT_SECRET": "alpha-capacity-jwt-secret",
            "AUTH_RATE_MAX": "10000",
            "PORTAL_RATE_MAX": "10000",
            "HEARTBEAT_RATE_MAX": "10000",
            "SMTP_HOST": "",
            "SMTP_USER": "",
            "SMTP_PASS": "",
            "FROM_EMAIL": "",
        }
    )
    sys.modules.pop("pushkey_cloud_api", None)
    return importlib.import_module("pushkey_cloud_api")


def _timed(label: str, fn) -> tuple[str, float, int]:
    start = time.perf_counter()
    response = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return label, elapsed_ms, response.status_code


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, round((percentile / 100) * (len(values) - 1)))
    return values[index]


def run_smoke(users: int, iterations: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="pushkey-alpha-capacity-") as tmp:
        app_module = _fresh_app(Path(tmp))
        admin = TestClient(app_module.app)
        login = admin.post(
            "/api/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin-pass-123"},
        )
        if login.status_code != 200:
            raise SystemExit(f"admin login failed: {login.status_code} {login.text}")
        admin_headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        issued_keys = []
        for index in range(users):
            issued = admin.post(
                "/api/admin/licenses/issue",
                headers=admin_headers,
                json={
                    "tier": "starter",
                    "email": f"alpha-{index}@example.com",
                    "send_email": False,
                },
            )
            if issued.status_code != 200:
                raise SystemExit(f"license issue failed: {issued.status_code} {issued.text}")
            issued_keys.append(issued.json()["key"])

        def exercise(index: int) -> list[tuple[str, float, int]]:
            client = TestClient(app_module.app)
            email = f"user-{index}@example.com"
            password = "correct horse battery staple"
            auth: dict[str, str] = {}
            results = []
            results.append(_timed("register", lambda: client.post("/api/v1/auth/register", json={"email": email, "password": password})))
            label, latency, status = _timed("login", lambda: client.post("/api/v1/auth/login", json={"email": email, "password": password}))
            results.append((label, latency, status))
            if status == 200:
                token_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
                if token_response.status_code == 200:
                    auth = {"Authorization": f"Bearer {token_response.json()['token']}"}
            for turn in range(iterations):
                blob = f"encrypted-alpha-blob-{index}-{turn}".encode("ascii")
                results.append(_timed("vault_put", lambda blob=blob: client.put("/api/v1/vault", headers=auth, content=blob)))
                results.append(_timed("vault_get", lambda: client.get("/api/v1/vault", headers=auth)))
                key = issued_keys[(index + turn) % len(issued_keys)]
                results.append(_timed("portal_lookup", lambda key=key: client.post("/api/v1/portal/lookup", json={"license_key": key})))
                results.append(_timed("admin_stats", lambda: admin.get("/api/admin/stats", headers=admin_headers)))
            return results

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=min(users, 8)) as pool:
            nested = list(pool.map(exercise, range(users)))
        elapsed = time.perf_counter() - started

        flat = [item for group in nested for item in group]
        failures = [
            {"operation": label, "status_code": status, "latency_ms": round(latency, 2)}
            for label, latency, status in flat
            if status >= 400
        ]
        latencies = [latency for _, latency, status in flat if status < 400]
        by_operation: dict[str, list[float]] = {}
        for label, latency, status in flat:
            if status < 400:
                by_operation.setdefault(label, []).append(latency)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "users": users,
            "iterations_per_user": iterations,
            "requests_total": len(flat),
            "duration_seconds": round(elapsed, 3),
            "throughput_requests_per_second": round(len(flat) / elapsed, 2),
            "failures": failures,
            "latency_ms": {
                "median": round(statistics.median(latencies), 2),
                "p95": round(_percentile(latencies, 95), 2),
                "max": round(max(latencies), 2),
            },
            "operations": {
                name: {
                    "count": len(values),
                    "p95_ms": round(_percentile(values, 95), 2),
                    "max_ms": round(max(values), 2),
                }
                for name, values in sorted(by_operation.items())
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "alpha-capacity-results.json")
    parser.add_argument("--max-p95-ms", type=float, default=750.0)
    args = parser.parse_args()

    result = run_smoke(args.users, args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if result["failures"]:
        raise SystemExit(f"alpha capacity smoke had failures: {result['failures']}")
    if result["latency_ms"]["p95"] > args.max_p95_ms:
        raise SystemExit(
            f"alpha capacity smoke p95 {result['latency_ms']['p95']}ms exceeds {args.max_p95_ms}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
