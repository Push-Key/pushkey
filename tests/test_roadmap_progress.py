import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.roadmap_progress import RoadmapProgressError, calculate_progress


def test_progress_separates_launch_and_postlaunch_tasks():
    text = """
# Phase 0
- [x] baseline
# Phase 1
- [ ] contract
<!-- agentic-postlaunch:start -->
- [ ] provider brokers
<!-- agentic-postlaunch:end -->
"""
    result = calculate_progress(text)
    assert result["production"] == {"done": 1, "total": 2, "percent": 50.0}
    assert result["agentic_postlaunch"] == {
        "done": 0,
        "total": 1,
        "percent": 0.0,
    }


def test_progress_without_markers_counts_everything_as_production():
    result = calculate_progress(
        """
- [x] one
- [X] two
- [ ] three
"""
    )
    assert result["production"] == {"done": 2, "total": 3, "percent": 66.7}
    assert result["agentic_postlaunch"] == {"done": 0, "total": 0, "percent": 0.0}


def test_progress_rejects_unclosed_agentic_marker():
    with pytest.raises(RoadmapProgressError, match="Unclosed"):
        calculate_progress(
            """
<!-- agentic-postlaunch:start -->
- [ ] unfinished
"""
        )


def test_progress_rejects_end_without_start():
    with pytest.raises(RoadmapProgressError, match="Unexpected"):
        calculate_progress("<!-- agentic-postlaunch:end -->")


def test_progress_rejects_nested_markers():
    with pytest.raises(RoadmapProgressError, match="Nested"):
        calculate_progress(
            """
<!-- agentic-postlaunch:start -->
<!-- agentic-postlaunch:start -->
- [ ] nested
<!-- agentic-postlaunch:end -->
"""
        )


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
        "production": {"done": 1, "total": 2, "percent": 50.0},
        "agentic_postlaunch": {"done": 0, "total": 0, "percent": 0.0},
    }


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
