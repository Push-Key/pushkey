from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "production-monitoring-alert-rules.yaml"

REQUIRED_SIGNALS = {
    "health",
    "auth",
    "sync",
    "activation",
    "email",
    "storage",
    "rate-limits",
}

REQUIRED_RULE_FIELDS = {
    "name",
    "signal",
    "condition",
    "severity",
    "notify",
    "evidence_required",
}


def _load_spec():
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_spec_file_exists_and_is_marked_not_yet_deployed():
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "ready-to-apply" in text
    assert "not deployed" in text.lower() or "not-deployed" in text.lower()


def test_spec_declares_all_seven_required_signals():
    spec = _load_spec()
    rules = spec["rules"]

    signals = {rule["signal"] for rule in rules}

    assert signals == REQUIRED_SIGNALS


def test_each_rule_has_required_fields_and_non_empty_values():
    spec = _load_spec()
    rules = spec["rules"]

    assert len(rules) == len(REQUIRED_SIGNALS)

    for rule in rules:
        missing = REQUIRED_RULE_FIELDS - rule.keys()
        assert not missing, f"rule {rule.get('name')} missing fields: {missing}"

        assert rule["name"]
        assert rule["signal"] in REQUIRED_SIGNALS
        assert rule["condition"].strip()
        assert rule["severity"] in {"critical", "high", "medium", "low"}
        assert rule["evidence_required"]
        assert isinstance(rule["evidence_required"], list)


def test_each_rule_notifies_the_documented_accountable_operator_channels():
    spec = _load_spec()

    for rule in spec["rules"]:
        notify = rule["notify"]
        assert notify["primary"] == "live accountable-operator mailbox"
        assert notify["secondary"] == "backup accountable-operator mailbox"


def test_ops_readiness_references_the_alert_rule_spec_without_claiming_it_is_deployed():
    text = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8")

    assert "production-monitoring-alert-rules.yaml" in text
    lowered = text.lower()
    assert "not yet deployed" in lowered or "not deployed" in lowered
