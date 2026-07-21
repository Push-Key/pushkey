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


def test_packaged_modules_include_cli_runtime_imports():
    import ast

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packaged = set(metadata["tool"]["setuptools"]["py-modules"])
    cli_imports = set()
    tree = ast.parse((ROOT / "pushkey_cli.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            cli_imports.update(
                alias.name for alias in node.names if alias.name.startswith("pushkey_")
            )
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pushkey_"):
            cli_imports.add(node.module)

    assert cli_imports - packaged == set()


def test_pyinstaller_hidden_imports_include_packaged_runtime_modules():
    import ast

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packaged = {
        module
        for module in metadata["tool"]["setuptools"]["py-modules"]
        if module.startswith("pushkey_")
    }
    tree = ast.parse((ROOT / "build_exe.py").read_text(encoding="utf-8"))
    submodules = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SUBMODULES":
                    submodules = set(ast.literal_eval(node.value))

    assert submodules
    assert packaged - submodules == {"pushkey_cli"}


def test_pyinstaller_build_includes_windows_version_resources():
    source = (ROOT / "build_exe.py").read_text(encoding="utf-8")

    assert "--version-file" in source
    assert "FileVersion" in source
    assert "ProductVersion" in source
    assert "pyproject.toml" in source


def test_pyinstaller_build_uses_clean_cache_free_invocations():
    source = (ROOT / "build_exe.py").read_text(encoding="utf-8")

    assert "--noconfirm" in source
    assert "--clean" in source
    assert "Pushkey.spec" not in source
    assert "pushkey-cli.spec" not in source
