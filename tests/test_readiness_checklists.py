import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_handoff_checklist_progress_matches_the_live_script():
    """The checklist's stated alpha ratio must equal what the script computes.

    The other checks in this file assert that readiness claims exist as text,
    which lets a claim rot into a lie while its test still passes -- the stale
    `313/337` was exactly that. This test reads the ratio the handoff checklist
    claims and compares it to the live `roadmap_progress.py` output, so if the
    roadmap moves and the doc is not updated, the suite fails instead of
    guarding a false number.
    """
    checklist = (
        ROOT / "docs" / "production-external-gate-handoff-checklist.md"
    ).read_text(encoding="utf-8")
    match = re.search(r"roadmap_progress\.py[^\n]*?`(\d+)/(\d+)`", checklist)
    assert match, "handoff checklist must state the roadmap_progress alpha ratio"
    claimed = (int(match.group(1)), int(match.group(2)))

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "roadmap_progress.py"), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    alpha = json.loads(result.stdout)["alpha_launch"]
    assert (alpha["done"], alpha["total"]) == claimed, (
        f"handoff checklist claims {claimed[0]}/{claimed[1]} but roadmap_progress.py "
        f"reports {alpha['done']}/{alpha['total']}"
    )


def test_90_percent_checklist_records_capacity_and_rollback_evidence():
    checklist = (ROOT / "docs" / "90_PERCENT_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8")

    assert "- [x] Add capacity-test and rollback-drill scripts or runbooks." in checklist
    assert "scripts\\alpha_capacity_smoke.py --users 8 --iterations 4 --max-p95-ms 750" in checklist
    assert "scripts\\alpha_capacity_smoke.py --users 16 --iterations 8 --output docs\\alpha-capacity-load-results.json --max-p95-ms 1000" in checklist
    assert "scripts\\alpha_rollback_drill.py" in checklist
    assert (ROOT / "scripts" / "alpha_capacity_smoke.py").is_file()
    assert (ROOT / "scripts" / "alpha_rollback_drill.py").is_file()
    assert (ROOT / "docs" / "alpha-capacity-results.json").is_file()
    assert (ROOT / "docs" / "alpha-capacity-load-results.json").is_file()
    assert (ROOT / "docs" / "alpha-rollback-drill-results.json").is_file()


def test_90_percent_checklist_records_dashboard_alert_runbook_evidence():
    checklist = (ROOT / "docs" / "90_PERCENT_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8")
    ops = (ROOT / "docs" / "ops-readiness.md").read_text(encoding="utf-8").lower()

    assert "- [x] Add dashboard and alert configuration documents." in checklist
    for required in ("alpha dashboard targets", "alpha alert routing", "primary operator", "secondary operator"):
        assert required in ops


def test_90_percent_checklist_records_packaging_evidence_without_signing_claims():
    checklist = (ROOT / "docs" / "90_PERCENT_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8")

    for completed in (
        "Verify icons and version resources.",
        "Produce supported OS/architecture artifacts.",
        "Fail with a nonzero exit code on unsuccessful installation.",
        "Handle unsupported OS/architecture explicitly.",
        "Add arm64 support or document it as unsupported.",
        "Prevent Windows shim self-resolution loops.",
        "Fresh-machine smoke tests run `pushkey --help`, `pushkey init`, and `pushkey app`.",
        "Release assets exactly match the npm download map.",
    ):
        assert f"- [x] {completed}" in checklist

    assert "- [x] Verify checksums before installation." in checklist
    assert "Verify artifact signatures before installation. Deferred to Public Beta." in checklist
    assert "Sign Windows and macOS artifacts. Deferred to Public Beta; requires" in checklist
    assert "Confirm signed artifacts install successfully (Public Beta gate)." in checklist


def test_release_readiness_alpha_section_documents_unsigned_policy():
    text = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")

    for required in (
        "## Alpha Release",
        "unsigned builds are permitted",
        "every tester must be explicitly told the build is unsigned before download or",
        "every distributed artifact must include a SHA-256 checksum",
        "every artifact must identify the version, release tag, and commit SHA",
        "production-external-gate-handoff-checklist.md",
        "branch-protection and release-gate API evidence",
        "Pushkey Alpha",
        "Developer Preview",
        "Windows code signing, macOS signing and notarization",
        "mandatory before Public Beta",
    ):
        assert required in text


def test_remaining_tasklist_splits_alpha_blocker_from_post_alpha_work():
    text = (ROOT / "docs" / "REMAINING_TO_100_PERCENT_TASKLIST.md").read_text(encoding="utf-8")

    for required in (
        "## Current Ownership",
        "GitHub `main` has an active ruleset with pull-request review and",
        "classic branch protection with required CI",
        "checks and required pull-request review.",
        "The public `v0.1.0-alpha` release tag is published.",
        "The protected `release` environment is configured with required reviewers.",
        "### Agent-Executable Next Slices",
        "[Agent] Capture the GitHub ruleset and release-gate evidence",
        "### External Credential / Service Gates",
        "### Deferred To Public Beta / GA",
        "## Remaining Split",
        "### 1. Alpha Blocker",
        "Confirm alert routing reaches the accountable operator and record the",
        "### 2. Post-Alpha / Public Beta Blockers",
        "Production backup, restore, rollback, monitoring, and alert-delivery",
        "Signing credentials, artifact signing, signed-install verification, and",
        "Independent security review, penetration testing, and final sign-off.",
        "## Detailed Post-Alpha / Public Beta Blockers",
    ):
        assert required in text


def test_alpha_sellable_checklist_separates_alpha_and_post_alpha_work():
    text = (ROOT / "docs" / "ALPHA_SELLABLE_READINESS_CHECKLIST.md").read_text(encoding="utf-8")

    for required in (
        "Status date: 2026-07-22",
        "Alpha-to-market progress: 31/31 alpha blockers complete (100.0%).",
        "### Alpha Blocker",
        "- [x] Confirm alerts reach the accountable operator.",
        "Delivery proof was captured in the accountable operator inbox via SMTP",
        "## Post-Alpha / Public Beta Blockers",
        "post-Alpha / Public Beta work",
        "Sign Windows and macOS artifacts.",
        "[x] Configure branch protection and required release gates in GitHub settings.",
        "Complete production monitoring, backup, restore, and rollback drills.",
        "Alpha can start now because the Alpha Blocker above is checked.",
    ):
        assert required in text


def test_production_readiness_plan_marks_alert_delivery_complete():
    text = (ROOT / "docs" / "PRODUCTION_READINESS_PLAN.md").read_text(encoding="utf-8")

    assert "- [x] Alerts reach an accountable operator" in text
    assert "Alert-delivery proof was captured via SMTP acceptance and IMAP receipt" in text


def test_external_gate_handoff_checklist_records_repo_local_completion_and_external_gates():
    text = (ROOT / "docs" / "production-external-gate-handoff-checklist.md").read_text(encoding="utf-8")

    for completed in (
        "Re-ran `scripts/alpha_capacity_smoke.py --users 16 --iterations 8 --output docs/alpha-capacity-load-results.json --max-p95-ms 1000` and preserved the JSON result.",
        "Updated `docs/90_PERCENT_EXECUTION_CHECKLIST.md` to `323/323` and closed the last local Track A load-test slice.",
        "Updated `docs/90_PERCENT_LOCAL_EXECUTION_QUEUE.md` to point at this handoff checklist.",
        "Added this handoff checklist with evidence fields for every external production gate.",
        "Linked this checklist from `docs/release-readiness.md` and `docs/ops-readiness.md`.",
        "Refreshed the stale progress snapshots in `docs/100_PERCENT_COMPLETION_TASKLIST.md`, `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`, and `docs/alpha-launch-boundary-note.md`.",
        "Verified `scripts/roadmap_progress.py --json` reports `323/323` for the alpha-launch bucket.",
    ):
        assert f"- [x] {completed}" in text

    assert "Live operator mailbox delivery proof has been captured and cross-referenced" in text
    assert "in the alpha sellable readiness checklist." in text
    assert "GitHub `main` has an active ruleset with pull-request review and" in text
    assert "classic branch protection with required CI" in text
    assert "checks and required pull-request review." in text
    assert "The protected `release` environment is configured with required reviewers." in text
    assert "The public `v0.1.0-alpha` release tag is published." in text
    assert "## Remaining Production / Public Beta Gates" in text

    for gate in (
        "Encrypted PostgreSQL backups and restore strategy",
        "Object-storage backup/versioning strategy",
        "Production monitoring and alert delivery",
        "Destructive restore drill",
        "Production rollback drill",
        "Main-branch protection and release gates",
        "Alpha packaging and checksum publication",
        "Independent security review",
        "Penetration testing before Public Beta",
        "Code signing before Public Beta",
    ):
        if gate in ("Production monitoring and alert delivery", "Alpha packaging and checksum publication"):
            assert f"| [x] | {gate} |" in text
        elif gate == "Main-branch protection and release gates":
            assert f"| [x] | {gate} |" in text
        else:
            assert f"| [ ] | {gate} |" in text

    assert "Deferred. Accepted risk for invite-only Alpha. Required before Public Beta or commercial launch." in text
    assert "Signed-artifact install confirmation" in text
    assert "Critical/high findings resolved" in text


def test_alpha_launch_boundary_note_records_published_release_bundle():
    text = (ROOT / "docs" / "alpha-launch-boundary-note.md").read_text(encoding="utf-8")

    assert "GitHub release v0.1.0-alpha" in text
    assert "official alpha bundle published" in text


def test_launch_tasklist_records_deployment_guard_and_extension_scope_decision():
    deploy = (ROOT / "DEPLOY.md").read_text(encoding="utf-8")
    text = (ROOT / "docs" / "LAUNCH_TASKLIST.md").read_text(encoding="utf-8")
    chain = (ROOT / "docs" / "CONSECUTIVE_LAUNCH_TASKS.md").read_text(encoding="utf-8")

    assert "Exactly one API worker and one machine must remain running until Phase 4 database migration" in deploy
    assert "- [x] Inventory extension launch claims and decide defer/remove/ship." in text
    assert "defer browser and VS Code extensions until their package/store gates pass" in text
    assert "- [x] Decide extension scope: ship, beta, or defer." in chain
    assert "defer browser and VS Code extensions until their package/store gates pass" in chain


def test_public_extension_docs_mark_beta_deferred_scope():
    index = (ROOT / "web" / "content" / "docs" / "index.mdx").read_text(encoding="utf-8")
    integrations = (ROOT / "web" / "content" / "docs" / "integrations.mdx").read_text(encoding="utf-8")
    mcp = (ROOT / "web" / "content" / "docs" / "mcp.mdx").read_text(encoding="utf-8")
    browser = (ROOT / "browser-pushkey" / "README.md").read_text(encoding="utf-8")
    vscode = (ROOT / "vscode-pushkey" / "README.md").read_text(encoding="utf-8")

    assert "VS Code extension" in index
    assert "beta/deferred" in index
    assert "beta/deferred until the package/store gates pass" in integrations
    assert "For local testing, load the `.vsix` manually" in integrations
    assert "This page covers the shipped MCP integration." in mcp
    assert "beta/deferred and documented separately" in mcp
    assert "VS Code Copilot and other MCP clients with SSE support" in mcp
    assert "Status: beta/deferred until the package/store gates pass." in browser
    assert "Status: beta/deferred until the package/store gates pass." in vscode


def test_external_gate_runbook_maps_execution_order_and_evidence_fields():
    runbook = (ROOT / "docs" / "production-external-gate-operator-runbook.md").read_text(encoding="utf-8")
    handoff = (ROOT / "docs" / "production-external-gate-handoff-checklist.md").read_text(encoding="utf-8")
    backup = (ROOT / "docs" / "production-rollback-backup-infrastructure-checklist.md").read_text(encoding="utf-8")

    assert "Production External Gate Operator Runbook" in runbook
    assert "Evidence Matrix" in runbook
    assert "Step-By-Step Sequence" in runbook
    assert "production-rollback-backup-infrastructure-checklist.md" in runbook
    assert "production-rollback-drill-results.template.json" in runbook
    assert "release-readiness.md" in runbook
    assert "REMAINING_TO_100_PERCENT_TASKLIST.md" in runbook
    assert "ops-readiness.md" in runbook
    assert "local alpha rollback and capacity results" in runbook
    assert "documentation without hosted provider, backup, or restore records" in runbook
    assert "production-external-gate-operator-runbook.md" in handoff
    assert "production-external-gate-operator-runbook.md" in backup
