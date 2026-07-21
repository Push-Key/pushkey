import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_TS = ROOT / "web-app" / "src" / "lib" / "api.ts"
LOCAL_API = ROOT / "pushkey_local_api.py"
PUSHKEY_PY = ROOT / "pushkey.py"
LOCAL_API_DOC = ROOT / "docs" / "local-api-v1.md"
HEALTH_DOC = ROOT / "docs" / "health-sidecar-v1.md"
PRODUCTION_ENTRYPOINTS = (
    ROOT / "Dockerfile",
    ROOT / "fly.toml",
    ROOT / "railway.toml",
    ROOT / "DEPLOY.md",
)


def _normalise_client_path(path: str) -> str:
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{encodeURIComponent\(([^)]+)\)\}", r"{\1}", path)
    return path


def _client_paths() -> set[str]:
    source = API_TS.read_text(encoding="utf-8")
    paths = set()
    for match in re.finditer(r"request(?:<[^>]+>)?\(\s*([\"`])(.+?)\1", source):
        paths.add(_normalise_client_path(match.group(2)))
    return paths


def _local_api_routes() -> set[str]:
    source = LOCAL_API.read_text(encoding="utf-8")
    tree = ast.parse(source)
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"get", "post", "patch", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                routes.add(decorator.args[0].value)
    return routes


def test_local_web_client_paths_have_local_api_routes():
    missing = _client_paths() - _local_api_routes()
    assert missing == set()


def test_local_api_contract_doc_lists_every_client_path():
    doc = LOCAL_API_DOC.read_text(encoding="utf-8")
    missing = [path for path in sorted(_client_paths()) if path not in doc]
    assert missing == []


def test_health_sidecar_contract_matches_written_fields():
    pushkey_source = PUSHKEY_PY.read_text(encoding="utf-8")
    doc = HEALTH_DOC.read_text(encoding="utf-8")
    fields = {
        "status",
        "days_old",
        "provider",
        "category",
        "first_used",
        "last_used",
        "created",
        "rotated",
        "rotation_count",
    }

    for field in fields:
        assert f'"{field}"' in pushkey_source
        assert f"`{field}`" in doc


def test_health_sidecar_contract_forbids_secret_fields():
    doc = HEALTH_DOC.read_text(encoding="utf-8")
    for forbidden in ("secret values", "backup secret values", "recovery codes"):
        assert forbidden in doc


def test_production_deployment_entrypoints_use_canonical_cloud_api():
    for path in PRODUCTION_ENTRYPOINTS:
        text = path.read_text(encoding="utf-8")
        assert "server/main.py" not in text, path
        assert "server.main" not in text, path
        assert "main:app" not in text, path

    for path in (ROOT / "Dockerfile", ROOT / "railway.toml", ROOT / "DEPLOY.md"):
        assert "pushkey_cloud_api" in path.read_text(encoding="utf-8"), path


def test_legacy_server_is_not_deployable():
    server_dir = ROOT / "server"
    forbidden = ("main.py", "Dockerfile", "railway.toml", "requirements.txt")
    for name in forbidden:
        assert not (server_dir / name).exists()
