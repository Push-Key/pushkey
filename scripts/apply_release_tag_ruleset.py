#!/usr/bin/env python
"""Draft (and, only on explicit approval, apply) the release tag ruleset.

Defense in depth for the "no release from an unverified commit" control.

The primary control is executable and already in the repository: the
`verify-provenance` job in `.github/workflows/release.yml` refuses to build,
sign, or publish unless the tagged commit is contained in the protected branch
and every required check passed on it. That control needs no repository-admin
action.

This script adds the *second* layer -- restricting who may create a `v*` tag at
all -- which is a repository-admin change to shared state. It therefore
defaults to a dry run: it prints the exact payload and the exact `gh api` call
it would make, and changes nothing. Applying requires `--apply`, which is the
operator's explicit approval step.

Payload: docs/release-tag-ruleset.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAYLOAD = ROOT / "docs" / "release-tag-ruleset.json"
DEFAULT_REPO = "Push-Key/pushkey"


def load_payload(path: Path) -> dict:
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("target") != "tag":
        raise ValueError(f"{path}: ruleset target must be 'tag', got {body.get('target')!r}")
    if body.get("enforcement") != "active":
        raise ValueError(f"{path}: ruleset enforcement must be 'active' to have any effect")
    includes = ((body.get("conditions") or {}).get("ref_name") or {}).get("include") or []
    if not any(pattern.startswith("refs/tags/v") for pattern in includes):
        raise ValueError(f"{path}: ruleset must cover the release tag pattern refs/tags/v*, got {includes!r}")
    rule_types = {rule.get("type") for rule in body.get("rules") or []}
    if "creation" not in rule_types:
        raise ValueError(f"{path}: ruleset must include a 'creation' rule, got {sorted(rule_types)}")
    return body


def existing_tag_rulesets(repo: str) -> list[dict]:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/rulesets"],
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    try:
        rulesets = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [r for r in rulesets if r.get("target") == "tag"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually create the ruleset. Without this flag nothing is changed.",
    )
    args = parser.parse_args(argv)

    try:
        payload = load_payload(args.payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Repository: {args.repo}")
    print(f"Payload:    {args.payload}")
    print(json.dumps(payload, indent=2))
    print()
    print("Effect: only actors matching bypass_actors may create, update, or")
    print("delete tags matching refs/tags/v*. Everyone else is blocked, so a")
    print("release tag cannot be pushed by an unprivileged actor.")
    print()

    if not args.apply:
        print("DRY RUN -- nothing changed. This is a repository-admin change to")
        print("shared state and needs an operator's explicit approval.")
        print("To apply, re-run with --apply, or run the equivalent by hand:")
        print(f"  gh api --method POST repos/{args.repo}/rulesets --input {args.payload}")
        return 0

    existing = existing_tag_rulesets(args.repo)
    if existing:
        names = [r.get("name") for r in existing]
        print(f"refusing to apply: repository already has tag ruleset(s) {names!r}.")
        print("Review and update the existing ruleset instead of creating a duplicate.")
        return 1

    result = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{args.repo}/rulesets", "--input", str(args.payload)],
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return 1

    print("Applied. Re-run scripts/verify_release_branch_protection.py to record the new evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
