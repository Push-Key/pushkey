"""Tests for the release commit provenance gate.

These cover the executable control that stops a release from being cut from a
commit that never passed through the protected branch, plus the wiring that
makes the control non-bypassable inside `.github/workflows/release.yml`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".github" / "required-release-checks.json"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PROVENANCE_SCRIPT_PATH = ROOT / "scripts" / "verify_release_commit_provenance.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


provenance = _load("verify_release_commit_provenance", PROVENANCE_SCRIPT_PATH)
protection = _load(
    "verify_release_branch_protection",
    ROOT / "scripts" / "verify_release_branch_protection.py",
)


REQUIRED_CONTEXTS = [
    "CI / Python tests",
    "CI / Web build",
]


def _fake_api(responses: dict[str, dict]):
    """Build an ApiFetch that serves canned responses keyed by path prefix."""

    def fetch(path: str) -> dict:
        for prefix, body in responses.items():
            if path.startswith(prefix):
                return {"path": path, "exit_code": 0, "ok": True, "json": body, "stderr": ""}
        return {"path": path, "exit_code": 1, "ok": False, "json": None, "stderr": "not found"}

    return fetch


def _check_runs(*names: str, conclusion: str = "success") -> dict:
    return {
        "check_runs": [
            {"name": name, "status": "completed", "conclusion": conclusion} for name in names
        ]
    }


def _all_green(compare_status: str = "behind") -> dict:
    return {
        "repos/o/r/compare/": {"status": compare_status, "ahead_by": 0, "behind_by": 3},
        "repos/o/r/commits/abc/check-runs": _check_runs(*REQUIRED_CONTEXTS),
        "repos/o/r/commits/abc/status": {"statuses": []},
    }


# --- config -----------------------------------------------------------------


def test_required_checks_config_is_valid_and_matches_ci_job_names():
    branch, contexts = provenance.load_config(CONFIG_PATH)

    assert branch == "main"
    assert contexts, "required_contexts must not be empty"

    ci = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    workflow_name = ci["name"]
    job_names = {job["name"] for job in ci["jobs"].values()}

    for context in contexts:
        assert context.startswith(f"{workflow_name} / "), (
            f"required context {context!r} is not produced by the {workflow_name} workflow"
        )
        job_name = context[len(workflow_name) + 3 :].split(" (")[0]
        assert job_name in job_names, (
            f"required context {context!r} references unknown job {job_name!r}; "
            f"known jobs: {sorted(job_names)}"
        )


def test_load_config_rejects_malformed_documents(tmp_path):
    bad = tmp_path / "bad.json"

    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(provenance.ProvenanceConfigError):
        provenance.load_config(bad)

    bad.write_text(json.dumps({"protected_branch": "main", "required_contexts": []}), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceConfigError):
        provenance.load_config(bad)

    bad.write_text(json.dumps({"required_contexts": ["a"]}), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceConfigError):
        provenance.load_config(bad)

    with pytest.raises(provenance.ProvenanceConfigError):
        provenance.load_config(tmp_path / "missing.json")


# --- containment ------------------------------------------------------------


@pytest.mark.parametrize("status", ["identical", "behind"])
def test_commit_contained_in_protected_branch_passes(status):
    result = provenance.check_containment("o/r", "main", "abc", _fake_api(_all_green(status)))

    assert result["status"] == "pass"


@pytest.mark.parametrize("status", ["ahead", "diverged"])
def test_commit_outside_protected_branch_fails(status):
    result = provenance.check_containment("o/r", "main", "abc", _fake_api(_all_green(status)))

    assert result["status"] == "fail"
    assert "NOT" in result["detail"]


def test_unreadable_compare_is_inconclusive_not_a_pass():
    result = provenance.check_containment("o/r", "main", "abc", _fake_api({}))

    assert result["status"] == "error"


# --- required checks --------------------------------------------------------


def test_all_required_checks_green_passes():
    result = provenance.check_required_checks("o/r", "abc", REQUIRED_CONTEXTS, _fake_api(_all_green()))

    assert result["status"] == "pass"


def test_missing_required_check_fails_and_names_it():
    responses = _all_green()
    responses["repos/o/r/commits/abc/check-runs"] = _check_runs("CI / Python tests")

    result = provenance.check_required_checks("o/r", "abc", REQUIRED_CONTEXTS, _fake_api(responses))

    assert result["status"] == "fail"
    assert "CI / Web build" in result["detail"]


def test_failed_required_check_is_not_treated_as_success():
    responses = _all_green()
    responses["repos/o/r/commits/abc/check-runs"] = _check_runs(*REQUIRED_CONTEXTS, conclusion="failure")

    result = provenance.check_required_checks("o/r", "abc", REQUIRED_CONTEXTS, _fake_api(responses))

    assert result["status"] == "fail"


def test_commit_statuses_can_satisfy_required_contexts():
    responses = _all_green()
    responses["repos/o/r/commits/abc/check-runs"] = _check_runs("CI / Python tests")
    responses["repos/o/r/commits/abc/status"] = {
        "statuses": [{"context": "CI / Web build", "state": "success"}]
    }

    result = provenance.check_required_checks("o/r", "abc", REQUIRED_CONTEXTS, _fake_api(responses))

    assert result["status"] == "pass"


def test_bare_job_name_is_qualified_with_the_workflow_app_name():
    responses = _all_green()
    responses["repos/o/r/commits/abc/check-runs"] = {
        "check_runs": [
            {
                "name": name.split(" / ", 1)[1],
                "status": "completed",
                "conclusion": "success",
                "app": {"name": "CI"},
            }
            for name in REQUIRED_CONTEXTS
        ]
    }

    result = provenance.check_required_checks("o/r", "abc", REQUIRED_CONTEXTS, _fake_api(responses))

    assert result["status"] == "pass"


# --- verdict ----------------------------------------------------------------


def test_verdict_passes_only_when_both_controls_pass():
    result = provenance.run_verification("o/r", "abc", "main", REQUIRED_CONTEXTS, _fake_api(_all_green()))

    assert result["verdict"] == "PASS"
    assert result["gaps"] == []


def test_verdict_fails_when_commit_is_not_on_the_protected_branch():
    result = provenance.run_verification(
        "o/r", "abc", "main", REQUIRED_CONTEXTS, _fake_api(_all_green("diverged"))
    )

    assert result["verdict"] == "FAIL"
    assert result["gaps"]


def test_verdict_is_inconclusive_when_the_api_cannot_be_read():
    result = provenance.run_verification("o/r", "abc", "main", REQUIRED_CONTEXTS, _fake_api({}))

    assert result["verdict"] == "INCONCLUSIVE"


def test_main_exits_nonzero_without_a_commit_sha():
    assert provenance.main(["--sha", ""]) == 2


# --- workflow wiring --------------------------------------------------------


def test_release_workflow_runs_the_provenance_gate_before_every_other_job():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    verdict = protection.inspect_workflow_provenance_gate(text)

    assert verdict["ok"], verdict["detail"]
    assert verdict["unguarded_jobs"] == []


def test_provenance_gate_runs_before_build_sign_and_publish_steps():
    document = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    gate_job = protection.inspect_workflow_provenance_gate(
        RELEASE_WORKFLOW.read_text(encoding="utf-8")
    )["gate_job"]

    gate_steps = yaml.safe_dump(document["jobs"][gate_job])

    assert "build_exe.py" not in gate_steps
    assert "action-gh-release" not in gate_steps
    assert "signtool" not in gate_steps


def test_workflow_gate_detection_rejects_a_job_nothing_depends_on():
    text = yaml.safe_dump(
        {
            "on": {"push": {"tags": ["v*"]}},
            "jobs": {
                "verify-provenance": {
                    "steps": [{"run": "python scripts/verify_release_commit_provenance.py"}]
                },
                "release": {"steps": [{"run": "python -m build"}]},
            },
        }
    )

    verdict = protection.inspect_workflow_provenance_gate(text)

    assert verdict["ok"] is False
    assert verdict["unguarded_jobs"] == ["release"]


def test_workflow_gate_detection_rejects_a_workflow_without_the_script():
    text = yaml.safe_dump({"jobs": {"release": {"steps": [{"run": "python -m build"}]}}})

    verdict = protection.inspect_workflow_provenance_gate(text)

    assert verdict["ok"] is False
    assert verdict["gate_job"] is None


def test_workflow_gate_detection_accepts_a_string_needs_value():
    text = yaml.safe_dump(
        {
            "jobs": {
                "verify-provenance": {
                    "steps": [{"run": "python scripts/verify_release_commit_provenance.py"}]
                },
                "release": {"needs": "verify-provenance", "steps": [{"run": "python -m build"}]},
            },
        }
    )

    verdict = protection.inspect_workflow_provenance_gate(text)

    assert verdict["ok"] is True


# --- composite grading ------------------------------------------------------


def _c(name: str, status: str) -> dict:
    return {"name": name, "status": status, "detail": name, "evidence": None}


def test_any_single_provenance_control_satisfies_the_composite_check():
    for control in protection.ALTERNATIVE_PROVENANCE_CONTROLS:
        checks = [_c(name, "pass" if name == control else "fail") for name in protection.ALTERNATIVE_PROVENANCE_CONTROLS]

        composite = protection._composite_provenance_check(checks)

        assert composite["status"] == "pass", control


def test_composite_check_fails_when_no_control_is_in_place():
    checks = [_c(name, "fail") for name in protection.ALTERNATIVE_PROVENANCE_CONTROLS]

    assert protection._composite_provenance_check(checks)["status"] == "fail"


def test_grade_ignores_individually_optional_controls():
    checks = [
        _c("branch_protection_live", "pass"),
        _c("tag_ruleset_restricts_release_tags", "fail"),
        _c(protection.COMPOSITE_PROVENANCE_CHECK, "pass"),
    ]

    assert protection.grade(checks) == "PASS"


def test_grade_still_fails_on_a_required_control():
    checks = [
        _c("branch_protection_live", "fail"),
        _c(protection.COMPOSITE_PROVENANCE_CHECK, "pass"),
    ]

    assert protection.grade(checks) == "FAIL"


# --- drafted tag ruleset (defense in depth, needs operator approval) ---------


ruleset = _load("apply_release_tag_ruleset", ROOT / "scripts" / "apply_release_tag_ruleset.py")


def test_drafted_tag_ruleset_payload_is_valid():
    payload = ruleset.load_payload(ROOT / "docs" / "release-tag-ruleset.json")

    assert payload["target"] == "tag"
    assert payload["enforcement"] == "active"
    assert "refs/tags/v*" in payload["conditions"]["ref_name"]["include"]
    assert {"creation", "update", "deletion", "non_fast_forward"} <= {
        rule["type"] for rule in payload["rules"]
    }


def test_drafted_tag_ruleset_keeps_an_admin_bypass_so_releases_remain_possible():
    payload = ruleset.load_payload(ROOT / "docs" / "release-tag-ruleset.json")

    assert payload["bypass_actors"], (
        "a creation rule with no bypass actor would block every release tag, "
        "including legitimate ones"
    )


def test_ruleset_payload_validation_rejects_an_ineffective_draft(tmp_path):
    bad = tmp_path / "ruleset.json"

    bad.write_text(json.dumps({"target": "branch"}), encoding="utf-8")
    with pytest.raises(ValueError):
        ruleset.load_payload(bad)

    bad.write_text(
        json.dumps({"target": "tag", "enforcement": "evaluate"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        ruleset.load_payload(bad)

    bad.write_text(
        json.dumps(
            {
                "target": "tag",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/tags/release-*"]}},
                "rules": [{"type": "creation"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        ruleset.load_payload(bad)


def test_applying_the_ruleset_requires_an_explicit_flag(capsys):
    exit_code = ruleset.main([])

    assert exit_code == 0
    assert "DRY RUN" in capsys.readouterr().out
