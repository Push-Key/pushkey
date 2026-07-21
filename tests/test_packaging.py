"""Verify new modules are importable and declared in build surfaces."""

import importlib

import pytest

REQUIRED_MODULES = ["pushkey_locking", "pushkey_health"]


@pytest.mark.parametrize("module_name", REQUIRED_MODULES)
def test_module_importable(module_name):
    mod = importlib.import_module(module_name)
    assert mod.__name__ == module_name


def test_pyproject_declares_required_modules():
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    for name in REQUIRED_MODULES:
        assert f'"{name}"' in pyproject, f"{name} missing from pyproject.toml py-modules"


def test_build_exe_declares_required_modules():
    from pathlib import Path

    build_exe = (Path(__file__).resolve().parents[1] / "build_exe.py").read_text()
    for name in REQUIRED_MODULES:
        assert f'"{name}"' in build_exe, f"{name} missing from build_exe.py MODULES list"
