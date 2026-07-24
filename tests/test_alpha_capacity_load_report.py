import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_alpha_capacity_load_report_records_heavier_concurrency_run():
    report = json.loads((ROOT / "docs" / "alpha-capacity-load-results.json").read_text(encoding="utf-8"))

    datetime.fromisoformat(report["generated_at"])
    assert report["users"] == 16
    assert report["iterations_per_user"] == 8
    assert report["requests_total"] == 544
    assert report["throughput_requests_per_second"] > 0
    assert report["failures"] == []
    assert report["latency_ms"]["p95"] <= 1000
    assert report["operations"]["register"]["count"] == 16
    assert report["operations"]["login"]["count"] == 16
    for operation in ("vault_put", "vault_get", "portal_lookup", "admin_stats"):
        assert report["operations"][operation]["count"] == 128
