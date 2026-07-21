import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "local-api-v1.md"
API_TS = ROOT / "web-app" / "src" / "lib" / "api.ts"
AUTH_TS = ROOT / "web-app" / "src" / "lib" / "auth.ts"
BACKEND = ROOT / "pushkey_local_api.py"


def _normalize(path: str) -> str:
    path = re.sub(r"\$\{encodeURIComponent\([^}]+\)\}", "{param}", path)
    path = re.sub(r"\{[^}/]+\}", "{param}", path)
    path = re.sub(r"\?.*$", "", path)
    return path


def _frontend_paths() -> set[str]:
    text = API_TS.read_text(encoding="utf-8") + "\n" + AUTH_TS.read_text(encoding="utf-8")
    paths = set()
    for match in re.finditer(r"request<[^>]+>\(([`\"])(/api/[^`\"]+)\1", text):
        paths.add(_normalize(match.group(2)))
    for match in re.finditer(r"fetch\(([`\"])(/api/[^`\"]+)\1", text):
        paths.add(_normalize(match.group(2)))
    return paths


def _documented_paths() -> set[str]:
    text = DOC.read_text(encoding="utf-8")
    return {
        _normalize(path)
        for path in re.findall(r"\|\s*(?:GET|POST|PATCH|DELETE)\s*\|\s*`([^`]+)`", text)
    }


def _backend_paths() -> set[str]:
    text = BACKEND.read_text(encoding="utf-8")
    return {
        _normalize(path)
        for path in re.findall(r"@app\.(?:get|post|patch|delete)\(\"([^\"]+)\"", text)
    }


def test_local_web_client_paths_are_documented_and_implemented():
    frontend = _frontend_paths()
    documented = _documented_paths()
    backend = _backend_paths()

    assert frontend - documented == set()
    assert frontend - backend == set()
