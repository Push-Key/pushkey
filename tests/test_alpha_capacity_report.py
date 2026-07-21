import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_alpha_capacity_report_records_passing_load_smoke():
    report = json.loads((ROOT / "docs" / "alpha-capacity-results.json").read_text(encoding="utf-8"))

    assert report["users"] >= 8
    assert report["iterations_per_user"] >= 4
    assert report["requests_total"] >= 100
    assert report["throughput_requests_per_second"] > 0
    assert report["failures"] == []
    assert report["latency_ms"]["p95"] <= 750
    for operation in ("register", "login", "vault_put", "vault_get", "portal_lookup", "admin_stats"):
        assert operation in report["operations"]
        assert report["operations"][operation]["count"] > 0
