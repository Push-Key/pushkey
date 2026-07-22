from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
        "Pushkey Alpha",
        "Developer Preview",
        "Windows code signing, macOS signing and notarization",
        "mandatory before Public Beta",
    ):
        assert required in text


def test_external_gate_handoff_checklist_records_repo_local_completion_and_external_gates():
    text = (ROOT / "docs" / "production-external-gate-handoff-checklist.md").read_text(encoding="utf-8")

    for completed in (
        "Re-ran `scripts/alpha_capacity_smoke.py --users 16 --iterations 8 --output docs/alpha-capacity-load-results.json --max-p95-ms 1000` and preserved the JSON result.",
        "Updated `docs/90_PERCENT_EXECUTION_CHECKLIST.md` to `307/337` and closed the last local Track A load-test slice.",
        "Updated `docs/90_PERCENT_LOCAL_EXECUTION_QUEUE.md` to point at this handoff checklist.",
        "Added this handoff checklist with evidence fields for every external production gate.",
        "Linked this checklist from `docs/release-readiness.md` and `docs/ops-readiness.md`.",
        "Refreshed the stale progress snapshots in `docs/100_PERCENT_COMPLETION_TASKLIST.md`, `docs/REMAINING_TO_100_PERCENT_TASKLIST.md`, and `docs/alpha-launch-boundary-note.md`.",
        "Verified `scripts/roadmap_progress.py --json` still reports `307/337`.",
    ):
        assert f"- [x] {completed}" in text

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
        assert f"| [ ] | {gate} |" in text

    assert "Deferred. Accepted risk for invite-only Alpha. Required before Public Beta or commercial launch." in text
    assert "Signed-artifact install confirmation" in text
    assert "Critical/high findings resolved" in text
