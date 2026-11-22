"""The desktop's project functions use the shared project store (pushkey.py).

No Tk root: AppFrame methods are bound onto a small fake with `types.MethodType` (the
pattern of tests/test_ui_helpers.py and tests/test_desktop_save.py) and the module's own
`messagebox` name is patched with a recorder. The vault is a V2 password vault and the
config the real encrypted config.json, both under tmp_path (the vault directory), so a
project folder is always a subfolder. Keys carry dummy values.
"""
import hashlib
import inspect
import json
import re
import subprocess
import types
from pathlib import Path

import pytest

import pushkey
import pushkey_connect
import pushkey_crypto
import pushkey_shared
import pushkey_tiers
import pushkey_vault
from pushkey_vault import load_config, load_vault, save_config, save_vault

PASSWORD = "pw"
STRIPE = "STRIPE_SECRET_KEY"
OPENAI = "OPENAI_API_KEY"
OLD = "dummy-old-value-1111"
NEW = "dummy-new-value-2222"
OTHER = "dummy-other-value-3333"


def _entry(value=OLD, **extra):
    entry = {
        "value": value, "created": "2026-01-01", "rotated": None,
        "provider": "Unknown", "env": "dev", "projects": [], "connections": [], "notes": "",
    }
    entry.update(extra)
    return entry


def _ok(call):
    """The result of `call`; an exception is a failed assertion, not a test error."""
    try:
        return call()
    except Exception as exc:
        raise AssertionError(f"unexpected {exc!r}") from exc


def _raised(call):
    """The exception `call` raises, or None."""
    try:
        call()
    except (Exception, SystemExit) as exc:
        return exc
    return None


@pytest.fixture(autouse=True)
def cheap_key_derivation(monkeypatch):
    monkeypatch.setattr(
        pushkey_crypto, "_derive_key_argon2",
        lambda password, salt: hashlib.sha256(salt + password.encode()).digest(),
    )


@pytest.fixture(autouse=True)
def pro_tier(monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")


class FakeBox:
    """Stands in for tkinter.messagebox: records every call, never shows a dialog."""

    def __init__(self, answer=True):
        self.calls = []
        self.answer = answer

    def _record(self, kind, args):
        self.calls.append((kind, *args))

    def showwarning(self, *args, **kwargs):
        self._record("warning", args)

    def showinfo(self, *args, **kwargs):
        self._record("info", args)

    def showerror(self, *args, **kwargs):
        self._record("error", args)

    def askyesno(self, *args, **kwargs):
        self._record("askyesno", args)
        return self.answer

    def of(self, kind):
        return [call for call in self.calls if call[0] == kind]

    def text(self):
        return "\n".join(str(part) for call in self.calls for part in call)


@pytest.fixture
def box(monkeypatch):
    fake = FakeBox()
    monkeypatch.setattr(pushkey, "messagebox", fake)
    return fake


class FakeText:
    """An entry / string variable: get, set, delete."""

    def __init__(self, text=""):
        self.text = text

    def get(self):
        return self.text

    def set(self, text):
        self.text = text

    def delete(self, *args):
        self.text = ""


_BOUND = (
    "save", "_save_config", "_reload_after_conflict", "_reload_config", "_core_args", "_run_sync",
    "_auto_inject_key", "_auto_inject_keys_bulk", "_stamp_keys_used", "add_key", "add_project",
    "remove_project", "sync_project", "_apply_project_assignment", "_save_ci_fields",
    "_update_project_record", "import_vault", "_inline_inject",
    "_run_scan", "_run_git_scan",
)


class FakeApp:
    """The attributes the bound AppFrame methods read."""

    SCAN_EXTENSIONS = pushkey.AppFrame.SCAN_EXTENSIONS
    SCAN_SKIP_DIRS = pushkey.AppFrame.SCAN_SKIP_DIRS

    def __init__(self, vault, key, config):
        self.password = PASSWORD
        self.vault = vault
        self.vault_key = key
        self.config = config
        self.invalidated = []
        self.rendered = 0
        self.gate_calls = []
        self.add_name = FakeText()
        self.add_value = FakeText()
        self.add_cat = FakeText("General")
        self.add_env = FakeText("dev")
        self.proj_name = FakeText()
        self.proj_path_var = FakeText()
        self.proj_env = FakeText("dev")
        for name in _BOUND:
            setattr(self, name, types.MethodType(getattr(pushkey.AppFrame, name), self))

    def _invalidate_tabs(self, *tabs):
        self.invalidated.extend(tabs)

    def render_projects(self):
        self.rendered += 1

    def _gate(self, feature, current_count=0):
        self.gate_calls.append((feature, current_count))
        return feature != "max_projects"


class World:
    """A seeded vault (two dummy keys), the real config and a FakeApp loaded the way
    AppFrame.__init__ loads them."""

    def __init__(self, root):
        self.root = root
        save_vault({STRIPE: _entry(provider="Stripe"), OPENAI: _entry(OTHER, provider="OpenAI")}, PASSWORD)
        save_config({"projects": {}, "theme": "dark"})
        vault, key = load_vault(PASSWORD)
        self.app = FakeApp(vault, key, load_config())

    def folder(self, name):
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        return folder

    def register(self, name="acme", **kw):
        canonical, _ = pushkey_connect.register_project(str(self.folder(name)), **kw)
        self.app.config = load_config()
        return canonical

    def connect(self, key, project, write=True, **kw):
        """Connect from another tool: the desktop's copy is reloaded, as after a conflict."""
        result = pushkey_connect.connect(
            key_name=key, project=project, write=write, vault_key=None, password=PASSWORD,
            actor="test", **kw,
        )
        self.reload_app()
        return result

    def reload_app(self):
        vault, key = load_vault(PASSWORD)
        self.app.vault.clear()
        self.app.vault.update(vault)
        self.app.vault._pushkey_revision = getattr(vault, "_pushkey_revision", None)
        self.app.vault_key = key
        self.app.config = load_config()

    def set_value(self, key, value):
        vault, _ = load_vault(PASSWORD)
        vault[key]["value"] = value
        save_vault(vault, PASSWORD)
        self.reload_app()

    def disk_vault(self):
        vault, _ = load_vault(PASSWORD)
        return vault


@pytest.fixture
def world(tmp_path, monkeypatch, box):
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    return World(tmp_path)


def _env_text(folder, name=".env"):
    path = Path(folder) / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def _connections(vault, key, project):
    return [c for c in vault[key].get("connections", []) if c["project"] == project]


# -- add key / rotate: only connections are written ------------------------------------


def test_add_key_no_longer_writes_unassigned_projects(world, box):
    connected = world.register("connected")
    unassigned = world.register("unassigned")
    world.connect(STRIPE, connected)
    assert STRIPE + "=" + OLD in _env_text(connected)

    world.app.add_name.set(STRIPE)
    world.app.add_value.set(NEW)
    _ok(world.app.add_key)

    # The connected project got the new value; the project with no connections got nothing.
    assert STRIPE + "=" + NEW in _env_text(connected)
    assert _env_text(unassigned) is None
    assert not (Path(unassigned) / ".gitignore").exists()


def test_auto_inject_after_add_writes_nothing_without_connections(world, box):
    project = world.register("acme")

    world.app.add_name.set("BRAND_NEW_KEY")
    world.app.add_value.set(NEW)
    _ok(world.app.add_key)

    assert "BRAND_NEW_KEY" in world.app.vault
    assert _env_text(project) is None
    assert box.of("askyesno") == []
    assert [c for c in box.of("info")] and "synced" not in box.text()


def test_auto_inject_key_reports_connected_projects_and_errors(world, box):
    first = world.register("first")
    second = world.register("second")
    world.connect(STRIPE, first, write=False)
    world.connect(OPENAI, first, write=False)  # connected too, but not the key being synced
    world.connect(STRIPE, second, write=False)
    (Path(second) / ".env").mkdir()  # an env file that cannot be written

    count, errors = _ok(lambda: world.app._auto_inject_key(STRIPE))

    assert count == 1
    assert _env_text(first) is not None and STRIPE in _env_text(first)
    assert OPENAI not in _env_text(first)
    assert len(errors) == 1 and "second" in errors[0] and OLD not in errors[0]


def test_inline_inject_button_explains_a_key_with_no_connections(world, box):
    project = world.register("acme")

    _ok(lambda: world.app._inline_inject(STRIPE))

    assert _env_text(project) is None
    assert "not connected to any project" in box.text() and "Assign Keys" in box.text()

    world.connect(STRIPE, project, write=False)
    box.calls.clear()
    _ok(lambda: world.app._inline_inject(STRIPE))
    assert STRIPE + "=" + OLD in _env_text(project)
    assert "synced" in box.text().lower() or "written" in box.text().lower()


def test_bulk_inject_writes_only_connected_keys(world, box):
    project = world.register("acme")
    world.connect(STRIPE, project, write=False)
    world.connect(OPENAI, project, write=False)  # connected, but not in the list given

    count, errors = _ok(lambda: world.app._auto_inject_keys_bulk([STRIPE, "NOT_IN_THE_VAULT"]))

    assert (count, errors) == (1, [])
    text = _env_text(project)
    assert STRIPE in text and OPENAI not in text


# -- inject_env_file and the packaged CLI ---------------------------------------------


def test_inject_env_file_refuses_empty_list(tmp_path):
    vault = {"A": {"value": "1"}, "B": {"value": "2"}}

    for names in ([], None):
        error = _raised(lambda: pushkey.inject_env_file(tmp_path, vault, names))
        assert isinstance(error, ValueError) and "no keys given" in str(error)

    assert not (tmp_path / ".env").exists()
    pushkey.inject_env_file(tmp_path, vault, ["A"])
    assert "A=1" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_cli_main_inject_requires_keys(tmp_path, capsys):
    folder = tmp_path / "proj"
    folder.mkdir()
    save_vault({"A": _entry("1"), "B": _entry("2")}, PASSWORD)

    for argv in (["inject", str(folder)], ["inject", str(folder), "--keys"]):
        error = _raised(lambda: pushkey._cli_main(["-p", PASSWORD, *argv]))
        assert isinstance(error, SystemExit) and error.code == 2
    assert not (folder / ".env").exists()

    pushkey._cli_main(["-p", PASSWORD, "inject", str(folder), "--keys", "A"])
    text = (folder / ".env").read_text(encoding="utf-8")
    assert "A=1" in text and "B=2" not in text


# -- projects: register, remove, limit -------------------------------------------------


def test_add_project_registers_through_the_core_and_writes_nothing(world, box):
    folder = world.folder("acme-web")
    world.app.proj_name.set("Acme Web")
    world.app.proj_path_var.set(str(folder))
    world.app.proj_env.set("staging")

    _ok(world.app.add_project)

    config = load_config(strict=True)
    registered = pushkey_connect.registered_projects(config)
    assert list(registered) == [pushkey_connect.pushkey_projectfs.canonical_project_path(str(folder))]
    record = next(iter(registered.values()))
    assert record["name"] == "Acme Web" and record["environment"] == "staging"
    assert set(config["projects"]) == set(registered)  # no name-keyed entry beside it
    assert _env_text(folder) is None and not (folder / ".gitignore").exists()
    assert pushkey_connect.registered_projects(world.app.config) == registered
    assert world.app.rendered >= 1 and box.of("info")


def test_add_project_does_not_connect_keys_by_name_prefix(world, box):
    folder = world.folder("stripe")  # the folder name is a prefix of STRIPE_SECRET_KEY
    world.app.proj_name.set("stripe")
    world.app.proj_path_var.set(str(folder))

    _ok(world.app.add_project)

    assert len(pushkey_connect.registered_projects(load_config(strict=True))) == 1
    assert _connections(world.disk_vault(), STRIPE, str(folder)) == []
    assert world.disk_vault()[STRIPE]["projects"] == []
    assert _env_text(folder) is None


def test_add_project_refreshes_the_in_memory_config(world, box):
    folder = world.folder("acme-web")
    world.app.proj_name.set("Acme Web")
    world.app.proj_path_var.set(str(folder))  # the default environment: no extra record update

    _ok(world.app.add_project)

    assert list(pushkey_connect.registered_projects(world.app.config)) == list(
        pushkey_connect.registered_projects(load_config(strict=True)))
    assert len(pushkey_connect.registered_projects(world.app.config)) == 1


def test_register_project_gate_message_when_limit_reached(world, box, monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "free")
    first = world.register("first")
    second = world.folder("second")
    world.app.proj_name.set("second")
    world.app.proj_path_var.set(str(second))

    _ok(world.app.add_project)

    assert world.app.gate_calls == [("max_projects", 1)]
    assert list(pushkey_connect.registered_projects(load_config(strict=True))) == [first]
    assert box.of("error") == [] and box.of("info") == []


def test_add_project_duplicate_says_so(world, box):
    folder = world.folder("acme")
    world.register("acme")
    world.app.proj_name.set("again")
    world.app.proj_path_var.set(str(folder))

    _ok(world.app.add_project)

    assert box.of("warning") + box.of("error")
    assert "already a project" in box.text()
    assert len(pushkey_connect.registered_projects(load_config(strict=True))) == 1


def test_remove_project_drops_connections(world, box):
    project = world.register("acme")
    world.connect(STRIPE, project)
    before = _env_text(project)
    assert _connections(world.app.vault, STRIPE, project)

    _ok(lambda: world.app.remove_project(project))

    assert project not in load_config(strict=True)["projects"]
    assert project not in world.app.config["projects"]
    for vault in (world.disk_vault(), world.app.vault):
        assert _connections(vault, STRIPE, project) == []
        assert project not in vault[STRIPE]["projects"]
    assert _env_text(project) == before  # the file is left alone


def test_remove_project_text_says_files_are_not_changed(world, box):
    project = world.register("acme")
    box.answer = False

    _ok(lambda: world.app.remove_project(project))

    asked = box.of("askyesno")
    assert len(asked) == 1
    assert "Pushkey will stop managing this folder. Files in it are not changed." in asked[0][2]
    assert project in load_config(strict=True)["projects"]  # No means nothing changed


# -- Sync .env -------------------------------------------------------------------------


def test_sync_env_button_writes_only_connected_variables(world, box):
    project = world.register("acme")
    other = world.register("other")
    world.connect(STRIPE, project)
    world.connect(STRIPE, other)
    world.set_value(STRIPE, NEW)

    _ok(lambda: world.app.sync_project(project))

    asked = box.of("askyesno")
    assert len(asked) == 1 and STRIPE in asked[0][2] and ".env" in asked[0][2]
    assert OPENAI not in asked[0][2]
    text = _env_text(project)
    assert STRIPE + "=" + NEW in text and OPENAI not in text
    assert STRIPE + "=" + OLD in _env_text(other)  # another project is untouched


def test_sync_env_button_cancel_writes_nothing(world, box):
    project = world.register("acme")
    world.connect(STRIPE, project)
    world.set_value(STRIPE, NEW)
    box.answer = False

    _ok(lambda: world.app.sync_project(project))

    assert box.of("askyesno")
    assert STRIPE + "=" + OLD in _env_text(project)


def test_sync_env_button_without_connections_says_so(world, box):
    project = world.register("acme")

    _ok(lambda: world.app.sync_project(project))

    assert box.of("askyesno") == []
    assert box.of("info") and "Assign Keys" in box.text()
    assert _env_text(project) is None


# -- Assign Keys -----------------------------------------------------------------------


def test_assign_dialog_writes_connections(world, box):
    project = world.register("acme")

    _ok(lambda: world.app._apply_project_assignment(project, [STRIPE, OPENAI]))

    for vault in (world.disk_vault(), world.app.vault):
        for key in (STRIPE, OPENAI):
            conns = _connections(vault, key, project)
            assert [(c["file"], c["var"]) for c in conns] == [(".env", key)]
            assert vault[key]["projects"] == [project]
    assert _env_text(project) is None  # connecting does not write; Sync .env does

    _ok(lambda: world.app._apply_project_assignment(project, [OPENAI]))

    vault = world.disk_vault()
    assert _connections(vault, STRIPE, project) == []
    assert project not in vault[STRIPE]["projects"]
    assert len(_connections(vault, OPENAI, project)) == 1


def test_assign_dialog_asks_before_connecting_an_env_mismatch(world, box):
    project = world.register("acme")  # environment "dev"
    vault = world.disk_vault()
    vault[STRIPE]["env"] = "prod"
    save_vault(vault, PASSWORD)
    world.reload_app()
    box.answer = False

    _ok(lambda: world.app._apply_project_assignment(project, [STRIPE]))
    assert box.of("askyesno")
    assert _connections(world.disk_vault(), STRIPE, project) == []

    box.answer = True
    _ok(lambda: world.app._apply_project_assignment(project, [STRIPE]))
    assert len(_connections(world.disk_vault(), STRIPE, project)) == 1


def test_assign_dialog_source_calls_the_core_helper():
    source = inspect.getsource(pushkey.AppFrame.assign_keys_to_project)
    assert "_apply_project_assignment" in source
    assert "_auto_match_keys" not in source


# -- import a backup -------------------------------------------------------------------


def test_import_vault_keeps_local_connections_and_skips_the_backups_projects(world, box, monkeypatch, tmp_path):
    project = world.register("acme")
    world.connect(STRIPE, project, write=False)
    backup_vault = {STRIPE: _entry(NEW, projects=["elsewhere"]), "NEW_ONE": _entry(OTHER)}
    legacy = {"projects": {"legacy-name": {"path": "x", "keys": [STRIPE]}}}
    backup = tmp_path / "backup.pushkey-backup"
    backup.write_bytes(pushkey.encrypt_data(json.dumps({"vault": backup_vault, "config": legacy}), PASSWORD))
    monkeypatch.setattr(pushkey.filedialog, "askopenfilename", lambda **kwargs: str(backup))

    _ok(world.app.import_vault)

    for vault in (world.app.vault, world.disk_vault()):
        assert vault[STRIPE]["value"] == NEW  # the backup's value was merged in
        assert len(_connections(vault, STRIPE, project)) == 1  # this computer's link survived
        assert vault[STRIPE]["projects"] == [project]
        assert "NEW_ONE" in vault
    assert "legacy-name" not in world.app.config["projects"]
    assert "legacy-name" not in load_config(strict=True)["projects"]


# -- scans -----------------------------------------------------------------------------


def _git(folder, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=folder, check=True, capture_output=True,
    )


def test_project_scan_roots_use_registry_paths(world, box):
    project = world.register("acme")
    (Path(project) / "settings.py").write_text(f'TOKEN = "{OLD}"\n', encoding="utf-8")

    assert pushkey._project_scan_roots(world.app.config) == {project}
    findings = _ok(world.app._run_scan)

    assert [f["key"] for f in findings] == [STRIPE]
    assert all(Path(f["file"]).parent == Path(project) for f in findings)


def test_scan_roots_ignore_unregistered_names(world, box):
    project = world.register("acme")
    legacy = world.folder("legacy")
    (legacy / "settings.py").write_text(f'TOKEN = "{OLD}"\n', encoding="utf-8")
    world.app.config["projects"]["legacy-name"] = {"path": str(legacy), "keys": [], "added": "x"}
    _git(project, "init")  # the project is its own repository: not the Pushkey checkout around tmp

    assert pushkey._project_scan_roots(world.app.config) == {project}
    assert _ok(world.app._run_scan) == []  # the registered folder is clean
    assert _ok(world.app._run_git_scan) == []


def test_git_scan_reads_the_registered_folder(world, box):
    project = world.register("acme")
    (Path(project) / "settings.py").write_text(f'TOKEN = "{OLD}"\n', encoding="utf-8")
    _git(project, "init")
    _git(project, "add", "settings.py")
    _git(project, "commit", "-m", "add")

    findings = _ok(world.app._run_git_scan)

    assert {f["key"] for f in findings} == {STRIPE}
    assert all(f["repo"] == project for f in findings)


# -- CI fields -------------------------------------------------------------------------


def test_ci_fields_are_kept_on_the_path_keyed_record(world, box, monkeypatch):
    project = world.register("acme")
    other = world.register("other")

    def refuse(config):
        raise AssertionError("whole-config save_config called")

    monkeypatch.setattr(pushkey, "save_config", refuse)
    fields = {"vercel_token": "tok-should-not-persist", "vercel_project_id": "prj_1",
              "vercel_target": "production"}

    _ok(lambda: world.app._save_ci_fields(project, "Vercel", fields))

    on_disk = load_config(strict=True)
    record = on_disk["projects"][project]
    assert record.get("vercel_project_id") == "prj_1" and record.get("ci_platform") == "Vercel"
    assert record.get("name") == "acme" and record.get("default_file") == ".env"  # record intact
    assert "tok-should-not-persist" not in json.dumps(on_disk)
    assert "vercel_token" not in record
    assert on_disk["theme"] == "dark" and other in on_disk["projects"]
    assert world.app.config["projects"][project].get("ci_platform") == "Vercel"


def test_ci_fields_for_a_project_that_is_gone_are_skipped(world, box):
    project = world.register("acme")
    pushkey_connect.unregister_project(project, vault_key=None, password=PASSWORD)

    _ok(lambda: world.app._save_ci_fields(project, "Railway", {"railway_project_id": "x"}))

    assert project not in load_config(strict=True)["projects"]


# -- the old shape is gone from the source ----------------------------------------------

_FORBIDDEN = {
    "a hand-written project entry": r'self\.config\["projects"\]\[[^\]]+\]\s*=(?!=)',
    "a whole projects assignment": r'self\.config\["projects"\]\s*=(?!=)',
    "setdefault on projects": r'setdefault\(\s*"projects"',
    "deleting a project entry": r'del\s+self\.config\["projects"\]',
    "a hand-written key list": r'\["keys"\]\s*=(?!=)',
    "name-prefix auto-assign": r"_auto_match_keys",
    "the empty-list rule": r"or not proj_keys",
    "the old inject helper with a project record": r"inject_env_file\(\s*path",
    "the whole-config save": r"\bsave_config\(self\.config\)",
}


def test_no_hand_written_project_config_writes_remain():
    sources = {
        name: inspect.getsource(member)
        for name, member in inspect.getmembers(pushkey.AppFrame, inspect.isfunction)
    }
    found = [
        (label, name)
        for label, pattern in _FORBIDDEN.items()
        for name, source in sources.items()
        if re.search(pattern, source)
    ]
    assert found == []
    assert not hasattr(pushkey.AppFrame, "_auto_match_keys")
    assert not hasattr(pushkey.AppFrame, "_refresh_project_keys")
    assert not hasattr(pushkey.AppFrame, "_refresh_all_projects")


def test_project_code_reads_the_registry_not_the_name_keyed_store():
    for name in ("render_projects", "_draw_project_card", "_run_scan", "_run_git_scan",
                 "sync_project", "ci_sync_project", "assign_keys_to_project"):
        source = inspect.getsource(getattr(pushkey.AppFrame, name))
        assert 'info["path"]' not in source and 'proj["path"]' not in source, name
        assert 'config.get("projects"' not in source and 'config["projects"]' not in source, name


# -- copy ------------------------------------------------------------------------------


def test_help_text_no_longer_promises_automatic_writes():
    title, text = pushkey.SECTION_HELP["projects"]
    lowered = text.lower()
    assert "whenever you add or rotate a matching key" not in lowered
    assert "auto-match" not in lowered and "target env filters" not in lowered
    assert "only" in lowered and "connect" in lowered


def test_projects_screen_copy_no_longer_promises_automatic_writes():
    source = inspect.getsource(pushkey.AppFrame.render_projects)
    assert "auto-write" not in source
    assert "only inject keys matching this env" not in source


# -- plain error text ------------------------------------------------------------------


def test_core_errors_have_plain_text():
    for code in ("project_exists", "project_limit", "project_not_registered", "migration_pending",
                 "var_taken", "file_tracked_by_git", "vault_changed"):
        text = pushkey._connect_error_text(pushkey_connect.ConnectError(code))
        assert text and code not in text, code
    assert "already a project" in pushkey._connect_error_text(pushkey_connect.ConnectError("project_exists"))
    unknown = pushkey._connect_error_text(pushkey_connect.ConnectError("something_new"))
    assert unknown and "something_new" in unknown  # unknown codes still say which


def test_project_connections_lists_one_folder_only(world):
    project = world.register("acme")
    other = world.register("other")
    world.connect(STRIPE, project, write=False)
    world.connect(OPENAI, other, write=False)
    world.reload_app()

    rows = pushkey._project_connections(world.app.vault, project)

    assert [(name, conn["var"]) for name, conn in rows] == [(STRIPE, STRIPE)]


# -- fix round 1: nothing from another machine decides where a secret is written ---------


def _backup_file(tmp_path, monkeypatch, vault):
    backup = tmp_path / "backup.pushkey-backup"
    backup.write_bytes(pushkey.encrypt_data(json.dumps({"vault": vault, "config": {}}), PASSWORD))
    monkeypatch.setattr(pushkey.filedialog, "askopenfilename", lambda **kwargs: str(backup))


def _foreign_link(project):
    return {"project": project, "file": ".env", "var": "NEW_ONE", "added": "2026-01-01"}


def test_import_vault_new_key_arrives_with_no_connections_to_a_path_registered_here(
        world, box, monkeypatch, tmp_path):
    project = world.register("acme")  # the same path is registered here
    backup_vault = {"NEW_ONE": _entry(OTHER, projects=[project], connections=[_foreign_link(project)])}
    _backup_file(tmp_path, monkeypatch, backup_vault)

    _ok(world.app.import_vault)

    for vault in (world.app.vault, world.disk_vault()):
        assert vault["NEW_ONE"]["value"] == OTHER
        assert vault["NEW_ONE"]["connections"] == []
        assert vault["NEW_ONE"]["projects"] == []
    # The next add/rotate sync for the key must not write into the coincident folder.
    count, errors = _ok(lambda: world.app._auto_inject_key("NEW_ONE"))
    assert (count, errors) == (0, [])
    assert _env_text(project) is None


def test_import_vault_existing_key_without_local_links_does_not_take_the_backups(
        world, box, monkeypatch, tmp_path):
    project = world.register("acme")
    legacy = world.disk_vault()
    del legacy[STRIPE]["projects"], legacy[STRIPE]["connections"]  # an entry from before links existed
    save_vault(legacy, PASSWORD)
    world.reload_app()
    entry = _entry(NEW, projects=[project], connections=[_foreign_link(project)])
    _backup_file(tmp_path, monkeypatch, {STRIPE: entry})

    _ok(world.app.import_vault)

    vault = world.disk_vault()
    assert vault[STRIPE]["value"] == NEW
    assert vault[STRIPE]["connections"] == [] and vault[STRIPE]["projects"] == []


def test_team_import_goes_through_the_same_merge_and_never_trusts_foreign_links():
    source = inspect.getsource(pushkey.AppFrame.team_import)
    assert "_merge_foreign_vault_entries" in source
    assert "self.vault.update(team_vault)" not in source

    project = "C:/same/path/here"
    local = {STRIPE: _entry(OLD, projects=[project], connections=[_foreign_link(project)])}
    incoming = {
        STRIPE: _entry(NEW, projects=["x"], connections=[]),
        "TEAM_NEW": _entry(OTHER, projects=[project], connections=[_foreign_link(project)]),
    }
    pushkey._merge_foreign_vault_entries(local, incoming)

    assert local[STRIPE]["value"] == NEW  # the shared value arrives
    assert local[STRIPE]["connections"] == [_foreign_link(project)]  # this computer's links stay
    assert local[STRIPE]["projects"] == [project]
    assert local["TEAM_NEW"]["connections"] == [] and local["TEAM_NEW"]["projects"] == []
    assert incoming["TEAM_NEW"]["connections"] == [_foreign_link(project)]  # the input is not edited


def test_merge_keeps_the_rest_of_a_foreign_entry():
    local = {}
    pushkey._merge_foreign_vault_entries(
        local, {"K": _entry(OTHER, provider="OpenAI", notes="n", _rbac={"role": "viewer"})})
    assert local["K"]["provider"] == "OpenAI" and local["K"]["notes"] == "n"
    assert local["K"]["_rbac"] == {"role": "viewer"}


def test_reload_config_keeps_project_data_when_the_config_file_is_unreadable(world, box, monkeypatch):
    project = world.register("acme")
    before = dict(world.app.config["projects"])
    logged = []
    monkeypatch.setattr(pushkey, "log_event", lambda message, *a, **k: logged.append(message))
    pushkey_shared.CONFIG_FILE.write_bytes(b"not a config at all")

    _ok(world.app._reload_config)

    assert world.app.config["projects"] == before and project in world.app.config["projects"]
    assert len(logged) == 1 and "config" in logged[0]
    assert box.of("error") == [] and box.of("warning") == [] and box.of("info") == []


@pytest.mark.parametrize("failure", [
    pushkey_vault.ConfigUnreadableError("config_unreadable"), OSError("disk full")],
    ids=["config_unreadable", "oserror"])
def test_add_project_reports_when_the_environment_cannot_be_saved(world, box, monkeypatch, failure):
    folder = world.folder("acme-web")
    world.app.proj_name.set("Acme Web")
    world.app.proj_path_var.set(str(folder))
    world.app.proj_env.set("staging")

    def refuse(mutate):
        raise failure

    monkeypatch.setattr(pushkey, "update_config", refuse)

    _ok(world.app.add_project)

    registered = pushkey_connect.registered_projects(load_config(strict=True))
    assert len(registered) == 1  # the project stays registered
    errors = box.of("error")
    assert len(errors) == 1
    assert "added, but its environment could not be saved" in errors[0][2]
    assert (str(failure) or "") in errors[0][2]
    assert box.of("info") == []  # no "Linked"
