#!/usr/bin/env python
"""Refuse to release a commit that did not pass through the protected branch.

This is the executable half of the "no release can be cut from an unverified
commit" control. Repository settings alone cannot close that gap: the `Release`
workflow triggers on any `v*` tag push, and a required-reviewer gate on the
`release` Environment is a human approval, not a provenance check.

This script runs inside the release pipeline, before anything is built,
signed, or published, and fails the run unless BOTH hold for the tagged commit:

1. Containment -- the tagged commit is contained in the protected branch
   (`main`). Verified with the GitHub compare API: comparing
   `main...<sha>` must report status `identical` or `behind`, which means
   `<sha>` is an ancestor of (or equal to) the branch head. `ahead` or
   `diverged` means the commit never merged through `main`, so it never passed
   `main`'s required pull-request review.
2. Checks -- every required check context listed in
   `.github/required-release-checks.json` has a successful conclusion on that
   exact commit. Those contexts mirror `main`'s required status checks, so a
   commit that satisfies them demonstrably passed CI, tests, and scans.

Because this check lives in the workflow file on a protected branch, it cannot
be removed without a reviewed pull request, and it cannot be skipped by
choosing a different tag: the tag's commit is what gets verified.

The script is read-only. It never modifies the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".github" / "required-release-checks.json"
DEFAULT_REPO = "Push-Key/pushkey"

#: Comparison statuses that prove the compared commit is contained in the base
#: branch. GitHub returns these from `GET /repos/{repo}/compare/{base}...{head}`.
CONTAINED_STATUSES = frozenset({"identical", "behind"})

#: Check-run conclusions and commit-status states that count as a pass.
SUCCESS_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
SUCCESS_STATES = frozenset({"success"})


class ProvenanceConfigError(ValueError):
    """Raised when the required-release-checks configuration is unusable."""


ApiFetch = Callable[[str], dict]


def load_config(path: Path) -> tuple[str, list[str]]:
    """Return `(protected_branch, required_contexts)` from the config file."""

    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProvenanceConfigError(f"missing required-release-checks config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProvenanceConfigError(f"invalid JSON in {path}: {exc}") from exc

    branch = body.get("protected_branch")
    contexts = body.get("required_contexts")
    if not isinstance(branch, str) or not branch.strip():
        raise ProvenanceConfigError(f"{path}: `protected_branch` must be a non-empty string")
    if not isinstance(contexts, list) or not contexts:
        raise ProvenanceConfigError(f"{path}: `required_contexts` must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in contexts):
        raise ProvenanceConfigError(f"{path}: every `required_contexts` entry must be a non-empty string")

    return branch.strip(), [item.strip() for item in contexts]


def _run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def gh_api(path: str) -> dict:
    """Call `gh api <path>` read-only. Never raises: failures become evidence."""

    # No `--paginate`: these endpoints return objects, and gh concatenates raw
    # JSON documents when paginating an object response, which is unparseable.
    # `per_page=100` covers every realistic check count for a single commit.
    separator = "&" if "?" in path else "?"
    result = _run(["gh", "api", f"{path}{separator}per_page=100"])
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


def _check(name: str, status: str, detail: str, evidence: object = None) -> dict:
    assert status in ("pass", "fail", "error")
    return {"name": name, "status": status, "detail": detail, "evidence": evidence}


def _summarize_evidence(payload: dict) -> dict:
    """Drop the raw API body so evidence files stay reviewable."""

    return {
        "path": payload.get("path"),
        "exit_code": payload.get("exit_code"),
        "ok": payload.get("ok"),
        "stderr": payload.get("stderr"),
    }


def check_containment(repo: str, branch: str, sha: str, fetch: ApiFetch) -> dict:
    """Check that `sha` is contained in `branch` via the GitHub compare API."""

    payload = fetch(f"repos/{repo}/compare/{branch}...{sha}")
    if not payload["ok"] or not isinstance(payload["json"], dict):
        return _check(
            "commit_contained_in_protected_branch",
            "error",
            (
                f"could not compare {branch}...{sha} (exit {payload['exit_code']}): "
                f"{payload['stderr'] or 'no response body'}"
            ),
            _summarize_evidence(payload),
        )

    body = payload["json"]
    status = body.get("status")
    evidence = _summarize_evidence(payload) | {
        "status": status,
        "ahead_by": body.get("ahead_by"),
        "behind_by": body.get("behind_by"),
    }
    if status in CONTAINED_STATUSES:
        return _check(
            "commit_contained_in_protected_branch",
            "pass",
            f"compare {branch}...{sha} status={status!r}: the tagged commit is contained in {branch}",
            evidence,
        )
    return _check(
        "commit_contained_in_protected_branch",
        "fail",
        (
            f"compare {branch}...{sha} status={status!r}: the tagged commit is NOT "
            f"contained in the protected branch {branch}, so it never passed that "
            "branch's required pull-request review"
        ),
        evidence,
    )


def _collect_successful_contexts(repo: str, sha: str, fetch: ApiFetch) -> tuple[set[str], list[dict], list[str]]:
    """Return successful context names on `sha`, evidence, and any fetch errors."""

    successful: set[str] = set()
    evidence: list[dict] = []
    errors: list[str] = []

    runs = fetch(f"repos/{repo}/commits/{sha}/check-runs")
    evidence.append(_summarize_evidence(runs))
    if runs["ok"] and isinstance(runs["json"], dict):
        for run in runs["json"].get("check_runs") or []:
            if run.get("status") == "completed" and run.get("conclusion") in SUCCESS_CONCLUSIONS:
                name = run.get("name")
                app = ((run.get("app") or {}).get("name")) or ""
                if not name:
                    continue
                successful.add(name)
                # GitHub reports required contexts for workflow jobs as
                # "<workflow name> / <job name>"; check-runs expose only the job
                # name, so register both spellings.
                if app and "/" not in name:
                    successful.add(f"{app} / {name}")
    else:
        errors.append(
            f"could not read check-runs for {sha} (exit {runs['exit_code']}): "
            f"{runs['stderr'] or 'no response body'}"
        )

    statuses = fetch(f"repos/{repo}/commits/{sha}/status")
    evidence.append(_summarize_evidence(statuses))
    if statuses["ok"] and isinstance(statuses["json"], dict):
        for status in statuses["json"].get("statuses") or []:
            if status.get("state") in SUCCESS_STATES and status.get("context"):
                successful.add(status["context"])
    else:
        errors.append(
            f"could not read commit statuses for {sha} (exit {statuses['exit_code']}): "
            f"{statuses['stderr'] or 'no response body'}"
        )

    return successful, evidence, errors


def check_required_checks(repo: str, sha: str, contexts: list[str], fetch: ApiFetch) -> dict:
    """Check that every required context concluded successfully on `sha`."""

    successful, evidence, errors = _collect_successful_contexts(repo, sha, fetch)
    missing = [context for context in contexts if context not in successful]

    if errors and missing:
        return _check(
            "required_checks_passed_on_commit",
            "error",
            "; ".join(errors),
            {"evidence": evidence, "successful_contexts": sorted(successful)},
        )
    if missing:
        return _check(
            "required_checks_passed_on_commit",
            "fail",
            (
                f"required check contexts without a successful conclusion on {sha}: "
                f"{missing!r}. Observed successful contexts: {sorted(successful)!r}"
            ),
            {"evidence": evidence, "successful_contexts": sorted(successful)},
        )
    return _check(
        "required_checks_passed_on_commit",
        "pass",
        f"all {len(contexts)} required check contexts concluded successfully on {sha}",
        {"evidence": evidence, "successful_contexts": sorted(successful)},
    )


def run_verification(
    repo: str,
    sha: str,
    branch: str,
    contexts: list[str],
    fetch: ApiFetch,
    *,
    ref: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Run both provenance checks and return a verdict document."""

    checks = [
        check_containment(repo, branch, sha, fetch),
        check_required_checks(repo, sha, contexts, fetch),
    ]

    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        verdict = "FAIL"
    elif "error" in statuses:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"

    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "repo": repo,
        "ref": ref,
        "commit": sha,
        "protected_branch": branch,
        "required_contexts": contexts,
        "verdict": verdict,
        "gaps": [check["detail"] for check in checks if check["status"] == "fail"],
        "inconclusive_reasons": [check["detail"] for check in checks if check["status"] == "error"],
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=None, help="Optional evidence JSON path")
    parser.add_argument(
        "--allow-inconclusive",
        action="store_true",
        help="Exit 0 when checks could not be read at all (default: treat as failure)",
    )
    args = parser.parse_args(argv)

    if not args.sha:
        print("::error::no commit SHA supplied (--sha or GITHUB_SHA)", file=sys.stderr)
        return 2

    try:
        branch, contexts = load_config(args.config)
    except ProvenanceConfigError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    result = run_verification(args.repo, args.sha, branch, contexts, gh_api, ref=args.ref)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"Release provenance verdict: {result['verdict']}")
    for check in result["checks"]:
        print(f"  [{check['status']}] {check['name']}: {check['detail']}")

    if result["verdict"] == "PASS":
        return 0
    if result["verdict"] == "INCONCLUSIVE" and args.allow_inconclusive:
        print("::warning::provenance verification inconclusive, continuing by explicit request")
        return 0
    for gap in result["gaps"] + result["inconclusive_reasons"]:
        print(f"::error::{gap}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
