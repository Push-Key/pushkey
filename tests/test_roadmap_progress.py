import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.roadmap_progress import RoadmapProgressError, calculate_progress


EMPTY = {"done": 0, "total": 0, "percent": 0.0}


def test_progress_separates_alpha_beta_and_postlaunch_tasks():
    text = """
# Phase 0
- [x] baseline
# Phase 1
- [ ] contract
<!-- public-beta-gate:start -->
- [ ] buy a signing certificate
- [ ] run a hosted restore drill
<!-- public-beta-gate:end -->
<!-- agentic-postlaunch:start -->
- [ ] provider brokers
<!-- agentic-postlaunch:end -->
"""
    result = calculate_progress(text)

    assert result["alpha_launch"] == {"done": 1, "total": 2, "percent": 50.0}
    assert result["public_beta_gate"] == {"done": 0, "total": 2, "percent": 0.0}
    assert result["agentic_postlaunch"] == {"done": 0, "total": 1, "percent": 0.0}


def test_deferred_items_do_not_count_against_alpha_readiness():
    # The point of the split: work that cannot start until money or a third
    # party is involved must not make alpha look further away than it is.
    without = calculate_progress("- [x] shipped\n- [x] also shipped\n")
    with_deferred = calculate_progress(
        """
- [x] shipped
- [x] also shipped
<!-- public-beta-gate:start -->
- [ ] penetration test
<!-- public-beta-gate:end -->
"""
    )

    assert without["alpha_launch"] == with_deferred["alpha_launch"]
    assert with_deferred["alpha_launch"]["percent"] == 100.0


def test_deferred_items_are_still_counted_in_their_own_bucket():
    # Deferring is a scheduling decision, not a way to make work vanish.
    result = calculate_progress(
        """
<!-- public-beta-gate:start -->
- [x] one done
- [ ] one open
<!-- public-beta-gate:end -->
"""
    )

    assert result["public_beta_gate"] == {"done": 1, "total": 2, "percent": 50.0}
    assert result["alpha_launch"] == EMPTY


def test_progress_without_markers_counts_everything_as_alpha_launch():
    result = calculate_progress(
        """
- [x] one
- [X] two
- [ ] three
"""
    )
    assert result["alpha_launch"] == {"done": 2, "total": 3, "percent": 66.7}
    assert result["public_beta_gate"] == EMPTY
    assert result["agentic_postlaunch"] == EMPTY


@pytest.mark.parametrize("bucket", ["agentic-postlaunch", "public-beta-gate"])
def test_progress_rejects_unclosed_marker(bucket):
    with pytest.raises(RoadmapProgressError, match="Unclosed"):
        calculate_progress(f"<!-- {bucket}:start -->\n- [ ] unfinished\n")


@pytest.mark.parametrize("bucket", ["agentic-postlaunch", "public-beta-gate"])
def test_progress_rejects_end_without_start(bucket):
    with pytest.raises(RoadmapProgressError, match="Unexpected"):
        calculate_progress(f"<!-- {bucket}:end -->")


@pytest.mark.parametrize("bucket", ["agentic-postlaunch", "public-beta-gate"])
def test_progress_rejects_nested_markers(bucket):
    with pytest.raises(RoadmapProgressError, match="may not nest"):
        calculate_progress(
            f"<!-- {bucket}:start -->\n<!-- {bucket}:start -->\n- [ ] nested\n"
        )


def test_progress_rejects_overlapping_buckets():
    # Interleaved regions would make a checkbox's bucket depend on marker order.
    with pytest.raises(RoadmapProgressError, match="may not nest"):
        calculate_progress(
            """
<!-- public-beta-gate:start -->
- [ ] deferred
<!-- agentic-postlaunch:start -->
- [ ] review
<!-- public-beta-gate:end -->
<!-- agentic-postlaunch:end -->
"""
        )


def test_every_checkbox_lands_in_exactly_one_bucket():
    text = Path("docs/PRODUCTION_READINESS_PLAN.md").read_text(encoding="utf-8")
    result = calculate_progress(text)

    bucketed = sum(bucket["total"] for bucket in result.values())
    raw = sum(1 for line in text.splitlines() if line.startswith("- ["))

    assert bucketed == raw, "a checkbox was double counted or dropped"


def test_cli_json_output(tmp_path):
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text("- [x] done\n- [ ] todo\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/roadmap_progress.py", "--json", str(roadmap)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(completed.stdout) == {
        "alpha_launch": {"done": 1, "total": 2, "percent": 50.0},
        "public_beta_gate": EMPTY,
        "agentic_postlaunch": EMPTY,
    }


def test_cli_human_output_labels_each_bucket(tmp_path):
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text("- [x] done\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/roadmap_progress.py", str(roadmap)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Alpha launch: 1/1 = 100.0%" in completed.stdout
    assert "Public beta / GA gates (deferred)" in completed.stdout


def test_cli_exits_nonzero_for_missing_file(tmp_path):
    missing = tmp_path / "missing.md"
    completed = subprocess.run(
        [sys.executable, "scripts/roadmap_progress.py", str(missing)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 1
    assert "roadmap_progress:" in completed.stderr
