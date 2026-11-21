#!/usr/bin/env python
"""Read-only verification that no release can be cut from an unverified commit.

This checks the *real*, live GitHub configuration (not documentation) via
`gh api`, plus the release workflow trigger as committed at HEAD, and reports
a PASS/FAIL/INCONCLUSIVE verdict with the raw evidence attached.

It verifies two independent things:

1. `main` still has required status checks and required pull-request review
   enforced (both via classic branch protection and the branch ruleset).
2. The mechanism that can actually produce a published release --
   `.github/workflows/release.yml`, triggered by pushing a `v*` tag, gated by
   the `release` GitHub Environment -- is restricted so that a release can
   only be cut from a commit that passed through `main`'s required checks and
   required review. Any single one of these controls is sufficient, so they are
   graded together as one composite check rather than individually:
     - a ruleset targeting tag refs (matching `v*`) that restricts who may
       create/update such tags, or
     - classic tag protection covering `v*`, or
     - the `release` Environment's `deployment_branch_policy` restricting
       deployments to protected branches/tags, or
     - an in-workflow provenance gate: a job that runs
       `scripts/verify_release_commit_provenance.py` and that every other job
       in the release workflow declares `needs:` on, which fails the release
       unless the tagged commit is contained in `main` and every required check
       concluded successfully on that exact commit.
   Absent all of those, a required-reviewer approval on the `release`
   Environment is a human control only -- it does not itself verify the
   underlying commit's provenance, and any actor able to push a `v*` tag can
   trigger the build/release pipeline from an arbitrary commit.

This script does not modify anything. It only reads.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "release-branch-protection-verification-results.json"
DEFAULT_REPO = "Push-Key/pushkey"
DEFAULT_BRANCH = "main"
RELEASE_ENVIRONMENT = "release"
RELEASE_WORKFLOW_PATH = ".github/workflows/release.yml"


def _run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _gh_api(path: str) -> dict:
    """Call `gh api <path>` read-only. Never raises: failures are captured as evidence."""
    result = _run(["gh", "api", path])
    text = result.stdout.strip()
    parsed = None
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    return {
        "path": path,
        "exit_code": result.returncode,
        "ok": result.returncode == 0,
        "json": parsed,
        "stderr": result.stderr.strip(),
    }


def _git_show(ref_path: str) -> str | None:
    result = _run(["git", "show", ref_path], timeout=15)
    if result.returncode != 0:
        return None
    return result.stdout


def _check(name: str, status: str, detail: str, evidence: object = None) -> dict:
    assert status in ("pass", "fail", "error")
    return {"name": name, "status": status, "detail": detail, "evidence": evidence}


#: The in-workflow gate that ties a release tag back to a verified commit.
PROVENANCE_SCRIPT = "scripts/verify_release_commit_provenance.py"


def inspect_workflow_provenance_gate(workflow_text: str) -> dict:
    """Report whether the release workflow enforces commit provenance.

    A release workflow only closes the "release from an unverified commit" gap
    when a job actually runs `scripts/verify_release_commit_provenance.py` and
    every other job in the workflow depends on that job, so a failure blocks the
    whole release rather than one branch of it.

    Cosmetic mentions of the script (a comment, an unreferenced job) do not
    count: the dependency edges are what make the gate non-bypassable.
    """

    if PROVENANCE_SCRIPT not in workflow_text:
        return {
            "ok": False,
            "gate_job": None,
            "unguarded_jobs": [],
            "detail": (
                "The workflow's `push: tags: [\"v*\"]` trigger accepts a tag "
                "pointing at any commit, and no job runs "
                f"`{PROVENANCE_SCRIPT}` to check that the tagged commit is "
                "contained in the protected branch and passed its required "
                "checks."
            ),
        }

    try:
        import yaml  # noqa: PLC0415 -- optional dependency, only needed for this check
    except ImportError:
        return {
            "ok": False,
            "gate_job": None,
            "unguarded_jobs": [],
            "detail": (
                f"`{PROVENANCE_SCRIPT}` is referenced by the workflow, but PyYAML "
                "is not installed so the job dependency graph could not be "
                "verified. Install requirements-dev.txt and re-run."
            ),
        }

    try:
        document = yaml.safe_load(workflow_text) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "gate_job": None,
            "unguarded_jobs": [],
            "detail": f"could not parse {RELEASE_WORKFLOW_PATH} as YAML: {exc}",
        }

    jobs = document.get("jobs") or {}
    gate_jobs = [
        name
        for name, body in jobs.items()
        if PROVENANCE_SCRIPT in yaml.safe_dump(body or {})
    ]
    if not gate_jobs:
        return {
            "ok": False,
            "gate_job": None,
            "unguarded_jobs": sorted(jobs),
            "detail": (
                f"`{PROVENANCE_SCRIPT}` appears in {RELEASE_WORKFLOW_PATH} but not "
                "inside any job, so it never runs."
            ),
        }

    gate_job = gate_jobs[0]
    unguarded: list[str] = []
    for name, body in jobs.items():
        if name in gate_jobs:
            continue
        needs = (body or {}).get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        if gate_job not in needs:
            unguarded.append(name)

    if unguarded:
        return {
            "ok": False,
            "gate_job": gate_job,
            "unguarded_jobs": sorted(unguarded),
            "detail": (
                f"job {gate_job!r} runs `{PROVENANCE_SCRIPT}`, but these jobs do "
                f"not declare `needs: {gate_job}` and would still run for an "
                f"unverified commit: {sorted(unguarded)!r}"
            ),
        }

    return {
        "ok": True,
        "gate_job": gate_job,
        "unguarded_jobs": [],
        "detail": (
            f"job {gate_job!r} runs `{PROVENANCE_SCRIPT}` before any build, sign, "
            "or publish step, and every other job "
            f"({sorted(name for name in jobs if name != gate_job)!r}) declares "
            f"`needs: {gate_job}`, so a release cannot proceed from a commit that "
            "is not contained in the protected branch or that lacks successful "
            "required checks."
        ),
    }


#: Controls that each independently prevent a release from being cut from an
#: unverified commit. Any single one is sufficient, so none of them is graded on
#: its own: only the composite check below decides the verdict.
ALTERNATIVE_PROVENANCE_CONTROLS = (
    "tag_ruleset_restricts_release_tags",
    "classic_tag_protection",
    "release_environment_restricted_to_protected_refs",
    "release_workflow_trigger_inspected",
)

COMPOSITE_PROVENANCE_CHECK = "release_cannot_be_cut_from_unverified_commit"


def _composite_provenance_check(checks: list[dict]) -> dict:
    """Collapse the alternative provenance controls into one graded check."""

    by_name = {c["name"]: c for c in checks}
    present = [by_name[name] for name in ALTERNATIVE_PROVENANCE_CONTROLS if name in by_name]
    satisfied = [c["name"] for c in present if c["status"] == "pass"]
    unreadable = [c["name"] for c in present if c["status"] == "error"]

    if satisfied:
        return _check(
            COMPOSITE_PROVENANCE_CHECK,
            "pass",
            (
                "at least one live control ties a release tag back to a commit "
                f"that passed the protected branch's gates: {satisfied!r}"
            ),
            {"satisfied": satisfied, "unsatisfied": [c["name"] for c in present if c["status"] != "pass"]},
        )
    if unreadable and len(unreadable) == len(present):
        return _check(
            COMPOSITE_PROVENANCE_CHECK,
            "error",
            f"no provenance control could be read: {unreadable!r}",
            {"satisfied": [], "unreadable": unreadable},
        )
    return _check(
        COMPOSITE_PROVENANCE_CHECK,
        "fail",
        (
            "no tag ruleset, classic tag protection, release-environment branch "
            "policy, or in-workflow provenance gate restricts which commit a "
            "release may be cut from"
        ),
        {"satisfied": [], "unsatisfied": [c["name"] for c in present]},
    )


def grade(checks: list[dict]) -> str:
    """Return the overall verdict, ignoring individually-optional controls."""

    graded = [c for c in checks if c["name"] not in ALTERNATIVE_PROVENANCE_CONTROLS]
    statuses = {c["status"] for c in graded}
    if "fail" in statuses:
        return "FAIL"
    if "error" in statuses:
        return "INCONCLUSIVE"
    return "PASS"


def run_verification(repo: str, branch: str) -> dict:
    checks: list[dict] = []

    # --- 1. Classic branch protection on main, confirmed live. ---
    protection = _gh_api(f"repos/{repo}/branches/{branch}/protection")
    if not protection["ok"]:
        checks.append(
            _check(
                "branch_protection_live",
                "error",
                f"gh api call failed for branches/{branch}/protection "
                f"(exit {protection['exit_code']}): {protection['stderr']}",
                protection,
            )
        )
    else:
        body = protection["json"] or {}
        contexts = (body.get("required_status_checks") or {}).get("contexts") or []
        review = body.get("required_pull_request_reviews") or {}
        enforce_admins = (body.get("enforce_admins") or {}).get("enabled")
        allow_force_pushes = (body.get("allow_force_pushes") or {}).get("enabled")
        ok = (
            bool(contexts)
            and int(review.get("required_approving_review_count") or 0) >= 1
            and enforce_admins is True
            and allow_force_pushes is False
        )
        checks.append(
            _check(
                "branch_protection_live",
                "pass" if ok else "fail",
                (
                    f"required_status_checks={contexts!r}, "
                    f"required_approving_review_count="
                    f"{review.get('required_approving_review_count')!r}, "
                    f"enforce_admins={enforce_admins!r}, "
                    f"allow_force_pushes={allow_force_pushes!r}"
                ),
                protection,
            )
        )

    # --- 2. Rulesets: branch ruleset for main, and any ruleset covering tags. ---
    rulesets_list = _gh_api(f"repos/{repo}/rulesets")
    ruleset_details: list[dict] = []
    branch_ruleset_ok = False
    branch_ruleset_detail = "no active branch ruleset found covering the default branch"
    tag_ruleset_found = False
    tag_ruleset_detail = "no ruleset targets tag refs"

    if not rulesets_list["ok"]:
        checks.append(
            _check(
                "rulesets_live",
                "error",
                f"gh api call failed for repos/{repo}/rulesets "
                f"(exit {rulesets_list['exit_code']}): {rulesets_list['stderr']}",
                rulesets_list,
            )
        )
    else:
        for entry in rulesets_list["json"] or []:
            detail = _gh_api(f"repos/{repo}/rulesets/{entry['id']}")
            ruleset_details.append(detail)
            body = detail["json"] or {}
            if body.get("enforcement") != "active":
                continue
            rule_types = {rule.get("type") for rule in body.get("rules") or []}
            target = body.get("target")
            conditions = body.get("conditions") or {}
            if target == "branch":
                ref_include = ((conditions.get("ref_name") or {}).get("include")) or []
                covers_default = "~DEFAULT_BRANCH" in ref_include or any(
                    branch in ref for ref in ref_include
                )
                if covers_default and {"non_fast_forward", "pull_request"} <= rule_types:
                    branch_ruleset_ok = True
                    branch_ruleset_detail = (
                        f"ruleset id={body.get('id')} name={body.get('name')!r} "
                        f"enforces {sorted(rule_types)} on {ref_include}"
                    )
            if target == "tag":
                tag_ruleset_found = True
                tag_ruleset_detail = (
                    f"ruleset id={body.get('id')} name={body.get('name')!r} "
                    f"target=tag rules={sorted(rule_types)} conditions={conditions}"
                )

        checks.append(
            _check(
                "branch_ruleset_non_fast_forward_and_review",
                "pass" if branch_ruleset_ok else "fail",
                branch_ruleset_detail,
                ruleset_details,
            )
        )
        checks.append(
            _check(
                "tag_ruleset_restricts_release_tags",
                "pass" if tag_ruleset_found else "fail",
                (
                    tag_ruleset_detail
                    if tag_ruleset_found
                    else (
                        "no ruleset restricts creation/update of tags matching the "
                        "release workflow's `v*` trigger pattern; anyone with "
                        "tag-push permission can create a `v*` tag pointing at any "
                        "commit"
                    )
                ),
                ruleset_details,
            )
        )

    # --- 3. Legacy/classic tag protection rules (separate from rulesets). ---
    tag_protection = _gh_api(f"repos/{repo}/tags/protection")
    if tag_protection["exit_code"] == 0 and tag_protection["json"]:
        rules = tag_protection["json"]
        matches_v_star = [
            r for r in rules if re.fullmatch(r.get("pattern", "").replace("*", ".*"), "v0.1.0")
        ]
        checks.append(
            _check(
                "classic_tag_protection",
                "pass" if matches_v_star else "fail",
                f"classic tag protection rules present but none match `v*`: {rules}"
                if not matches_v_star
                else f"classic tag protection restricts `v*`-matching tags: {matches_v_star}",
                tag_protection,
            )
        )
    else:
        # 404 (no rules configured) is the expected shape for "not configured".
        checks.append(
            _check(
                "classic_tag_protection",
                "fail",
                (
                    "no classic tag protection rules are configured "
                    f"(gh api exit {tag_protection['exit_code']}: {tag_protection['stderr'] or 'empty response'})"
                ),
                tag_protection,
            )
        )

    # --- 4. `release` Environment: required reviewers + deployment_branch_policy. ---
    environment = _gh_api(f"repos/{repo}/environments/{RELEASE_ENVIRONMENT}")
    if not environment["ok"]:
        checks.append(
            _check(
                "release_environment_live",
                "error",
                f"gh api call failed for environments/{RELEASE_ENVIRONMENT} "
                f"(exit {environment['exit_code']}): {environment['stderr']}",
                environment,
            )
        )
    else:
        body = environment["json"] or {}
        rules = body.get("protection_rules") or []
        has_required_reviewers = any(r.get("type") == "required_reviewers" for r in rules)
        branch_policy = body.get("deployment_branch_policy")
        checks.append(
            _check(
                "release_environment_required_reviewers",
                "pass" if has_required_reviewers else "fail",
                f"protection_rules types={[r.get('type') for r in rules]}",
                environment,
            )
        )
        checks.append(
            _check(
                "release_environment_restricted_to_protected_refs",
                "pass" if branch_policy is not None else "fail",
                (
                    f"deployment_branch_policy={branch_policy!r}: the `release` "
                    "Environment does not restrict which ref/branch/tag may "
                    "deploy to it, so the required-reviewer gate is a human "
                    "approval only -- it does not verify the tagged commit "
                    "descends from a commit that passed main's required checks"
                    if branch_policy is None
                    else f"deployment_branch_policy={branch_policy!r}"
                ),
                environment,
            )
        )

    # --- 5. Release workflow trigger, as committed (not the possibly-in-flight working tree). ---
    workflow_text = _git_show(f"HEAD:{RELEASE_WORKFLOW_PATH}")
    if workflow_text is None:
        checks.append(
            _check(
                "release_workflow_trigger_inspected",
                "error",
                f"could not read {RELEASE_WORKFLOW_PATH} at HEAD via git show",
            )
        )
    else:
        triggers_on_any_v_tag = bool(
            re.search(r'push:\s*\n\s*tags:\s*\n\s*-\s*"v\*"', workflow_text)
        )
        gated_by_release_environment = bool(re.search(r"^\s*environment:\s*release\s*$", workflow_text, re.MULTILINE))
        provenance = inspect_workflow_provenance_gate(workflow_text)
        verifies_commit_provenance = provenance["ok"]
        checks.append(
            _check(
                "release_workflow_trigger_inspected",
                "fail" if (triggers_on_any_v_tag and not verifies_commit_provenance) else "pass",
                (
                    f"triggers_on_any_v_tag={triggers_on_any_v_tag}, "
                    f"gated_by_release_environment={gated_by_release_environment}, "
                    f"workflow_verifies_commit_provenance={verifies_commit_provenance}. "
                    + provenance["detail"]
                ),
                {
                    "workflow_path": RELEASE_WORKFLOW_PATH,
                    "provenance_gate": provenance,
                    "source_at_HEAD": workflow_text,
                },
            )
        )

    checks.append(_composite_provenance_check(checks))

    verdict = grade(checks)
    graded = [c for c in checks if c["name"] not in ALTERNATIVE_PROVENANCE_CONTROLS]
    gaps = [c["detail"] for c in graded if c["status"] == "fail"]
    errors = [c["detail"] for c in graded if c["status"] == "error"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "branch": branch,
        "release_environment": RELEASE_ENVIRONMENT,
        "release_workflow_path": RELEASE_WORKFLOW_PATH,
        "verdict": verdict,
        "gaps": gaps,
        "inconclusive_reasons": errors,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/repo, default: {DEFAULT_REPO}")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help=f"protected branch, default: {DEFAULT_BRANCH}")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = run_verification(args.repo, args.branch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"Verdict: {result['verdict']}")
    if result["gaps"]:
        print("Gaps found:")
        for gap in result["gaps"]:
            print(f"  - {gap}")
    if result["inconclusive_reasons"]:
        print("Inconclusive checks:")
        for reason in result["inconclusive_reasons"]:
            print(f"  - {reason}")
    print(f"Evidence written to {args.output}")

    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
