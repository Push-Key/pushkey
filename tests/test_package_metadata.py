import pathlib
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _project_metadata():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_package_dependencies_are_index_installable():
    metadata = _project_metadata()
    dependencies = metadata["dependencies"]
    optional = metadata["optional-dependencies"]

    all_requirements = dependencies + [
        requirement for group in optional.values() for requirement in group
    ]

    assert all(" @ git+" not in requirement for requirement in all_requirements)
    assert optional["api"]
    assert optional["mcp"]
    assert optional["cloud"]
    assert optional["dev"]


def test_public_package_identity_and_entry_points_are_explicit():
    metadata = _project_metadata()

    assert metadata["authors"] == [
        {"name": "pushkeydev", "email": "pushkeydev@gmail.com"}
    ]
    assert metadata["requires-python"] == ">=3.12"
    assert metadata["scripts"] == {
        "pushkey": "pushkey_cli:main",
        "pushkey-gui": "pushkey:main",
    }
