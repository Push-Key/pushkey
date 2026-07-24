import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_API = ROOT / "web" / "src" / "lib" / "admin-api.ts"
CLOUD_API = ROOT / "pushkey_cloud_api.py"
ADMIN_LAYOUT = ROOT / "web" / "src" / "app" / "admin" / "layout.tsx"


def _normalize(path: str) -> str:
    path = re.sub(r"\$\{encodeURIComponent\([^}]+\)\}", "{param}", path)
    path = re.sub(r"\{[^}/]+\}", "{param}", path)
    path = re.sub(r"\?.*$", "", path)
    if path.endswith("/"):
        path += "{param}"
    return path


def test_admin_frontend_api_paths_are_implemented_by_cloud_api():
    client = ADMIN_API.read_text(encoding="utf-8")
    backend = CLOUD_API.read_text(encoding="utf-8")

    quoted_paths = re.findall(r'"(/api/admin[^"]+)"', client)
    template_paths = re.findall(r"`(/api/admin[^`$]+)", client)
    api_template_paths = re.findall(r"`\$\{API\}(/api/admin[^`$]+)", client)
    client_paths = {
        _normalize(path)
        for path in quoted_paths + template_paths + api_template_paths
    }
    backend_paths = {
        _normalize(path)
        for path in re.findall(r"@app\.(?:get|post|patch|delete)\(\"([^\"]+)\"", backend)
    }

    missing = {
        path
        for path in client_paths
        if path.startswith("/api/admin")
        and path not in backend_paths
        and not any(candidate.startswith(path + "/") for candidate in backend_paths)
    }
    assert missing == set()


def test_admin_navigation_points_to_existing_alpha_pages():
    layout = ADMIN_LAYOUT.read_text(encoding="utf-8")
    pages = {
        "/" + path.relative_to(ROOT / "web" / "src" / "app").parent.as_posix()
        for path in (ROOT / "web" / "src" / "app" / "admin").rglob("page.tsx")
    }
    nav_paths = set(re.findall(r'navItem\("([^"]+)"', layout))

    assert nav_paths - pages == set()
