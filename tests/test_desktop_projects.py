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
    "_update_project_record", "_try_update_project_record", "import_vault", "_inline_inject",
    "_run_scan", "_run_git_scan", "_apply_rotation", "_promote_backup_key", "_submit_add_key",
    "_add_wants_connection", "_add_connection_choice", "_sync_results", "_show_sync_results",
    "_register_folder_for_add", "_used_in_update_now", "_used_in_disconnect",
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
        # The add-key window's "Connect to a project" widgets (off until a test picks one).
        self.add_conn_on = FakeText(0)
        self.add_conn_project = FakeText("")
        self.add_conn_file = FakeText("")
        self.add_conn_var = FakeText("")
        self._add_conn_paths = {}
        for name in _BOUND:
            setattr(self, name, types.MethodType(getattr(pushkey.AppFrame, name), self))

    def _invalidate_tabs(self, *tabs):
        self.invalidated.extend(tabs)

    def render_projects(self):
        self.rendered += 1

    def _render_key_rows(self):
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

    def pick(self, project, file=".env", var="", on=True):
        """Fill the add-key window's connect section the way the user would."""
        label = Path(project).name
        self.app._add_conn_paths = {label: project}
        self.app.add_conn_on.set(1 if on else 0)
        self.app.add_conn_project.set(label)
        self.app.add_conn_file.set(file)
        self.app.add_conn_var.set(var)

    def fill(self, name, value=NEW, category="General", env="all"):
        self.app.add_name.set(name)
        self.app.add_value.set(value)
        self.app.add_cat.set(category)
        self.app.add_env.set(env)


@pytest.fixture
def world(tmp_path, monkeypatch, box):
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    return World(tmp_path)


def _env_text(folder, name=".env"):
    path = Path(folder) / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def _connections(vault, key, project):
    return [c for c in (vault.get(key) or {}).get("connections", []) if c["project"] == project]


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


# =========================================================================================
# Task 13: add-and-connect screens (add-key window logic, USED IN block, rotation results,
# migration notice). No Tk root: every test drives a bound method on the fakes above.
# =========================================================================================

NEW_KEY = "BRAND_NEW_KEY"


class FakeWin:
    """A window that only remembers whether it was closed."""

    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


# -- add_key ----------------------------------------------------------------------------


def test_add_key_returns_false_on_missing_info(world, box):
    world.fill("", NEW)
    assert world.app.add_key() is False
    world.fill("SOMETHING", "")
    assert world.app.add_key() is False

    assert len(box.of("warning")) == 2
    assert "SOMETHING" not in world.app.vault and "SOMETHING" not in world.disk_vault()


def test_add_key_with_connection_calls_connect(world, box):
    project = world.register("acme")
    world.fill(NEW_KEY, NEW, env="dev")
    world.pick(project, ".env", NEW_KEY)

    assert world.app.add_key() is True

    disk = world.disk_vault()
    assert disk.get(NEW_KEY, {}).get("value") == NEW
    connections = _connections(disk, NEW_KEY, project)
    assert [(c["file"], c["var"]) for c in connections] == [(".env", NEW_KEY)]
    assert NEW_KEY + "=" + NEW in _env_text(project)
    assert NEW_KEY in world.app.vault  # the session's own copy was brought up to date
    assert NEW not in box.text()
    assert "keys" in world.app.invalidated and "projects" in world.app.invalidated


def test_add_key_with_connection_keeps_the_chosen_category(world, box):
    project = world.register("acme")
    world.fill(NEW_KEY, NEW, category="AI", env="dev")
    world.pick(project, ".env", NEW_KEY)

    assert world.app.add_key() is True

    assert world.disk_vault().get(NEW_KEY, {}).get("category") == "AI"
    assert world.app.vault.get(NEW_KEY, {}).get("category") == "AI"


def test_add_key_write_failure_after_the_vault_save_still_closes_the_window(world, box):
    project = world.register("acme")
    (Path(project) / ".env").mkdir()  # an env file that cannot be written
    world.fill(NEW_KEY, NEW, env="dev")
    world.pick(project, ".env", NEW_KEY)

    assert world.app.add_key() is True  # the key is saved; a second Save would say "exists"

    disk = world.disk_vault()
    assert disk.get(NEW_KEY, {}).get("value") == NEW
    assert _connections(disk, NEW_KEY, project)
    assert (disk.get(NEW_KEY, {}).get("connections") or [{}])[0].get("last_error")
    shown = box.of("warning") + box.of("error")
    assert len(shown) == 1 and "acme" in shown[0][2]
    assert NEW not in box.text()


def test_add_key_failure_keeps_window_open(world, box):
    project = world.register("acme")
    world.connect(OPENAI, project, var="SHARED_VAR", write=False)
    world.fill(NEW_KEY, NEW, env="dev")
    world.pick(project, ".env", "SHARED_VAR")  # another key already writes there
    win = FakeWin()

    assert world.app._submit_add_key(win) is False

    assert win.destroyed is False
    assert world.app.add_name.get() == NEW_KEY and world.app.add_value.get() == NEW  # inputs kept
    errors = box.of("error")
    assert len(errors) == 1 and "Another key already writes" in errors[0][2]
    assert NEW_KEY not in world.app.vault and NEW_KEY not in world.disk_vault()
    assert NEW not in box.text()


def test_add_key_success_closes_the_window(world, box):
    project = world.register("acme")
    world.fill(NEW_KEY, NEW, env="dev")
    world.pick(project, ".env", NEW_KEY)
    win = FakeWin()

    assert world.app._submit_add_key(win) is True

    assert win.destroyed is True


def test_add_key_button_and_return_both_use_the_submit_helper():
    source = inspect.getsource(pushkey.AppFrame._show_add_key_modal)

    assert source.count("_submit_add_key") >= 2  # the button and <Return>
    assert "self.add_key(), win.destroy()" not in source


def test_add_key_connect_checked_without_a_project_asks_instead_of_saving(world, box):
    world.fill(NEW_KEY, NEW, env="dev")
    world.pick("", "", "", on=True)

    assert world.app.add_key() is False

    assert len(box.of("warning")) == 1
    assert NEW_KEY not in world.disk_vault()


def test_add_key_extra_confirmation_no_cancels_save(world, box):
    project = world.register("acme")  # a dev project
    world.fill("PROD_KEY", NEW, env="prod")  # for another environment
    world.pick(project, ".env", "PROD_KEY")
    box.answer = False

    assert world.app.add_key() is False

    asks = box.of("askyesno")
    assert len(asks) == 1 and "This key is for another environment. Continue?" in asks[0][2]
    assert "PROD_KEY" not in world.app.vault and "PROD_KEY" not in world.disk_vault()
    assert _env_text(project) is None

    box.answer = True
    box.calls.clear()
    assert world.app.add_key() is True
    assert "PROD_KEY=" + NEW in _env_text(project)


def test_add_key_second_extra_confirmation_no_also_cancels(world, box):
    project = world.register("acme")
    world.fill("PROD_SECRET", NEW, env="prod")
    world.pick(project, ".env", "NEXT_PUBLIC_PROD_SECRET")  # bundled into browser code too
    answers = iter([True, False])
    box.askyesno = lambda *a, **k: (box._record("askyesno", a), next(answers))[1]

    assert world.app.add_key() is False

    texts = [call[2] for call in box.of("askyesno")]
    assert len(texts) == 2
    assert "another environment" in texts[0] and "bundled into browser code. Continue?" in texts[1]
    assert "PROD_SECRET" not in world.disk_vault()
    assert _env_text(project) is None


def test_add_key_plain_path_uses_commit_not_stale_save(world, box):
    other, _ = load_vault(PASSWORD)  # another tool adds a key after the desktop loaded
    other["ADDED_ELSEWHERE"] = _entry(OTHER)
    save_vault(other, PASSWORD)
    stale_saves = []
    world.app.save = lambda *a, **k: stale_saves.append(1)  # the stale whole-vault save
    world.fill(NEW_KEY, NEW, category="AI")

    assert world.app.add_key() is True

    disk = world.disk_vault()
    assert NEW_KEY in disk and "ADDED_ELSEWHERE" in disk  # nothing was overwritten
    assert disk.get(NEW_KEY, {}).get("category") == "AI" and disk.get(NEW_KEY, {}).get("value") == NEW
    assert "ADDED_ELSEWHERE" in world.app.vault  # the session adopted what was on disk
    assert box.of("warning") == [] and box.of("error") == []
    assert stale_saves == []


def test_add_key_plain_path_refuses_a_name_another_tool_just_added(world, box):
    other, _ = load_vault(PASSWORD)
    other[NEW_KEY] = _entry(OTHER)  # appears between the desktop's load and this Save
    save_vault(other, PASSWORD)
    world.fill(NEW_KEY, NEW)

    assert world.app.add_key() is False

    assert world.disk_vault()[NEW_KEY]["value"] == OTHER  # not replaced
    assert len(box.of("error")) == 1


def test_add_key_rotation_uses_commit_and_shows_per_project_results(world, box):
    project = world.register("acme")
    world.connect(STRIPE, project)
    other, _ = load_vault(PASSWORD)
    other["ADDED_ELSEWHERE"] = _entry(OTHER)
    save_vault(other, PASSWORD)
    world.fill(STRIPE, NEW)

    assert world.app.add_key() is True

    disk = world.disk_vault()
    assert disk[STRIPE]["value"] == NEW and disk[STRIPE].get("previous") == OLD
    assert "ADDED_ELSEWHERE" in disk
    assert STRIPE + "=" + NEW in _env_text(project)
    dialogs = box.of("info") + box.of("warning")
    assert len(dialogs) == 1 and "acme" in dialogs[0][2] and ".env" in dialogs[0][2]
    assert OLD not in box.text() and NEW not in box.text()


def test_add_key_existing_name_with_a_connection_replaces_and_connects(world, box):
    first = world.register("first")
    second = world.register("second")
    world.connect(STRIPE, first)
    world.fill(STRIPE, NEW, env="dev")
    world.pick(second, ".env", STRIPE)

    assert world.app.add_key() is True

    disk = world.disk_vault()
    assert disk[STRIPE]["value"] == NEW
    assert _connections(disk, STRIPE, first) and _connections(disk, STRIPE, second)
    assert STRIPE + "=" + NEW in _env_text(first)
    assert STRIPE + "=" + NEW in _env_text(second)


# -- rotation: replace_value + sync, one results dialog -----------------------------------


def test_rotation_results_dialog_has_no_value(world, box):
    project = world.register("acme")
    second = world.register("second")
    world.connect(STRIPE, project)
    world.connect(STRIPE, second, write=False)
    (Path(second) / ".env").mkdir()  # this one cannot be written

    assert world.app._apply_rotation(STRIPE, NEW) is True

    dialogs = box.of("info") + box.of("warning") + box.of("error")
    assert len(dialogs) == 1
    text = dialogs[0][2]
    assert "acme" in text and "second" in text and ".env" in text
    assert OLD not in box.text() and NEW not in box.text()
    assert world.disk_vault()[STRIPE].get("previous") == OLD
    assert STRIPE + "=" + NEW in _env_text(project)


def test_rotation_without_connections_is_one_short_dialog(world, box):
    assert world.app._apply_rotation(OPENAI, NEW) is True

    assert len(box.calls) == 1 and OPENAI in box.calls[0][2]
    assert world.disk_vault()[OPENAI]["value"] == NEW


def test_rotation_failure_says_so_and_changes_nothing(world, box, monkeypatch):
    def refuse(mutate, **kw):
        raise pushkey_connect.ConnectError("vault_changed")

    monkeypatch.setattr(pushkey_connect, "commit", refuse)

    assert world.app._apply_rotation(STRIPE, NEW) is False

    errors = box.of("error")
    assert len(errors) == 1 and "vault changed" in errors[0][2]
    assert world.disk_vault()[STRIPE]["value"] == OLD


def _with_backup(world, project):
    world.connect(STRIPE, project)
    vault, _ = load_vault(PASSWORD)
    vault[STRIPE].update(dual_rotation=True, next_value=NEW, next_added="2026-01-01")
    save_vault(vault, PASSWORD)
    world.reload_app()


def test_promote_backup_syncs(world, box):
    project = world.register("acme")
    _with_backup(world, project)

    world.app._promote_backup_key(STRIPE)

    disk = world.disk_vault()
    assert disk[STRIPE]["value"] == NEW and disk[STRIPE].get("previous") == OLD
    assert disk[STRIPE]["next_value"] is None and disk[STRIPE]["next_added"] is None
    assert STRIPE + "=" + NEW in _env_text(project)
    assert OLD not in box.text() and NEW not in box.text()
    assert "acme" in box.text()  # the per-project result is in the one dialog


def test_promote_backup_declined_changes_nothing(world, box):
    project = world.register("acme")
    _with_backup(world, project)
    box.answer = False

    world.app._promote_backup_key(STRIPE)

    assert world.disk_vault()[STRIPE]["value"] == OLD
    assert STRIPE + "=" + OLD in _env_text(project)


def test_promote_backup_text_no_longer_says_the_old_key_is_discarded():
    source = inspect.getsource(pushkey.AppFrame._promote_backup_key)

    assert "discarded from Pushkey" not in source  # the old value now goes to history
    assert "replace_value" in source and "commit" in source


# -- USED IN block ----------------------------------------------------------------------


def test_used_in_rows_from_status(world, box):
    first = world.register("acme")
    second = world.register("second")
    world.connect(STRIPE, first)
    world.connect(STRIPE, second, write=False)
    statuses = pushkey_connect.status(world.app.vault, world.app.config, key_name=STRIPE)

    rows = _ok(lambda: pushkey._used_in_rows(statuses))

    assert [row[:3] for row in rows] == [("acme", ".env", STRIPE), ("second", ".env", STRIPE)]
    assert [row[3] for row in rows] == [s.state for s in statuses]
    assert rows[0][3] == "up_to_date"
    assert all(len(row) == 5 for row in rows)
    assert OLD not in repr(rows)


def test_used_in_rows_state_mapping():
    import typing

    expected = {
        "up_to_date": ("Up to date", "green", False),
        "out_of_date": ("Out of date", "amber", True),
        "not_in_file": ("Not in the file yet", "amber", True),
        "not_ignored": ("Not in .gitignore", "amber", False),
        "not_written": ("Not written", "red", True),
        "file_missing": ("File missing", "red", False),
        "folder_missing": ("Folder not on this computer", "red", False),
    }
    states = set(typing.get_args(typing.get_type_hints(pushkey_connect.ConnectionStatus)["state"]))

    assert states == set(expected)  # every state the core can report has a pill
    for state, wanted in expected.items():
        assert _ok(lambda: pushkey._used_in_pill(state)) == wanted
    assert _ok(lambda: pushkey._used_in_pill("something_new")) == ("Unknown", "text3", False)


def test_used_in_update_now_syncs_only_that_connection(world, box):
    first = world.register("first")
    second = world.register("second")
    world.connect(STRIPE, first)
    world.connect(STRIPE, second)
    world.set_value(STRIPE, NEW)

    _ok(lambda: world.app._used_in_update_now(STRIPE, first))

    assert STRIPE + "=" + NEW in _env_text(first)
    assert STRIPE + "=" + OLD in _env_text(second)  # not asked for
    dialogs = box.calls
    assert len(dialogs) == 1 and "first" in dialogs[0][2]
    assert OLD not in box.text() and NEW not in box.text()


def test_used_in_disconnect_leaves_the_line_in_the_file(world, box):
    project = world.register("acme")
    world.connect(STRIPE, project)

    _ok(lambda: world.app._used_in_disconnect(STRIPE, project, ".env", STRIPE))

    asks = box.of("askyesno")
    assert len(asks) == 1 and "left as it is" in asks[0][2] and "acme" in asks[0][2]
    assert _connections(world.disk_vault(), STRIPE, project) == []
    assert STRIPE + "=" + OLD in _env_text(project)  # the line stays


def test_used_in_disconnect_declined_changes_nothing(world, box):
    project = world.register("acme")
    world.connect(STRIPE, project)
    box.answer = False

    _ok(lambda: world.app._used_in_disconnect(STRIPE, project, ".env", STRIPE))

    assert len(_connections(world.disk_vault(), STRIPE, project)) == 1


def test_expand_panel_has_a_used_in_block_instead_of_project_pills():
    source = inspect.getsource(pushkey.AppFrame._render_expand_panel)

    assert '"USED IN"' in source and "_used_in_rows" in source
    assert '"PROJECTS"' not in source
    assert "Not used in any project yet. Connect it from Add or the project's Keys screen." in source
    assert "_used_in_update_now" in source and "_used_in_disconnect" in source


# -- connect preview wording, adding a folder -----------------------------------------------


def _preview(**kw):
    values = dict(
        key=STRIPE, project="C:/p", project_name="acme", file=".env.local", var="STRIPE_KEY",
        environment="dev", line="Save to acme -> dev -> .env.local as STRIPE_KEY",
        change="add", gitignore_change=False, needs_confirm=[], conflict_key=None,
    )
    values.update(kw)
    return pushkey_connect.Preview(**values)


def test_connect_preview_lines_in_plain_words():
    lines = _ok(lambda: pushkey._connect_preview_lines(_preview()))
    assert lines == [
        "Save to acme -> dev -> .env.local as STRIPE_KEY",
        "Adds STRIPE_KEY to .env.local. The other lines stay as they are.",
        ".env.local is already ignored by git.",
    ]

    lines = pushkey._connect_preview_lines(_preview(
        change="replace", gitignore_change=True, needs_confirm=["env_mismatch", "public_prefix"]))
    assert lines == [
        "Save to acme -> dev -> .env.local as STRIPE_KEY",
        "Replaces STRIPE_KEY in .env.local. The other lines stay as they are.",
        ".env.local will be added to .gitignore.",
        "This key is for another environment. You will be asked to confirm.",
        "This name is bundled into browser code. You will be asked to confirm.",
    ]

    assert pushkey._connect_preview_lines(_preview(change="none"))[1] == ".env.local already holds this value."


def test_register_folder_for_add_registers_and_returns_the_path(world, box):
    folder = world.folder("brand-new")

    path = _ok(lambda: world.app._register_folder_for_add(str(folder)))

    assert path in pushkey_connect.registered_projects(load_config(strict=True))
    assert path in pushkey_connect.registered_projects(world.app.config)
    assert "projects" in world.app.invalidated


def test_register_folder_for_add_says_so_when_it_is_already_a_project(world, box):
    folder = world.folder("brand-new")
    _ok(lambda: world.app._register_folder_for_add(str(folder)))
    box.calls.clear()

    assert _ok(lambda: world.app._register_folder_for_add(str(folder))) is None

    assert len(box.calls) == 1 and "already a project" in box.calls[0][2]


def test_register_folder_for_add_over_the_limit_uses_the_plan_prompt(world, box, monkeypatch):
    world.register("first")
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "free")
    folder = world.folder("second")

    assert _ok(lambda: world.app._register_folder_for_add(str(folder))) is None

    assert world.app.gate_calls == [("max_projects", 1)]
    assert len(pushkey_connect.registered_projects(load_config(strict=True))) == 1


def test_register_folder_for_add_ignores_a_cancelled_dialog(world, box):
    assert _ok(lambda: world.app._register_folder_for_add("")) is None
    assert box.calls == []


# -- S12: imported keys use a real environment name -------------------------------------


def test_env_import_writes_prod_not_production():
    source = inspect.getsource(pushkey.AppFrame._do_env_import)

    assert '"env": "production"' not in source
    assert '"env": "prod"' in source
    assert "prod" in pushkey.ENV_LEVELS and "production" not in pushkey.ENV_LEVELS


# -- migration notice -------------------------------------------------------------------

NOTICE = {
    "every_key_projects": [],  # filled per test with real folders
    "env_skipped": [["acme", "PROD_KEY"]],
    "unusable": ["lost"],
    "unregistered": [["OTHER_KEY", "C:/work/elsewhere"]],
}


class NoticeApp:
    """The PushkeyApp attributes the notice methods use; the modal itself is a recorder."""

    def __init__(self):
        self.opened = []
        self.frame = None
        self._open_connect_notice = lambda view: self.opened.append(view)
        for name in ("_show_connect_notice", "_notice_later", "_notice_hide"):
            setattr(self, name, types.MethodType(getattr(pushkey.PushkeyApp, name), self))


def _notice_world(world, count=2):
    folders = [world.register(f"old-{i}") for i in range(count)]
    notice = dict(NOTICE, every_key_projects=folders)
    config = load_config(strict=True)
    config["connect_notice"] = notice
    config["connect_schema"] = 1
    save_config(config)
    return folders, notice


def test_notice_later_does_not_dismiss(world, box, monkeypatch):
    _folders, notice = _notice_world(world)
    monkeypatch.setattr(
        pushkey.pushkey_connect_migrate, "dismiss_notice",
        lambda: pytest.fail("Later must not dismiss the notice"))
    app, win = NoticeApp(), FakeWin()

    _ok(lambda: app._notice_later(win))

    assert win.destroyed is True
    assert load_config(strict=True)["connect_notice"] == notice
    assert box.calls == []


def test_notice_hide_button_dismisses(world, box):
    _folders, _notice = _notice_world(world)
    app, win = NoticeApp(), FakeWin()

    _ok(lambda: app._notice_hide(win))

    assert "connect_notice" not in load_config(strict=True)
    assert win.destroyed is True
    assert box.calls == []


def test_notice_hide_failure_warns_once_and_keeps_the_window(world, box, monkeypatch):
    _folders, notice = _notice_world(world)

    def refuse():
        raise RuntimeError("config_busy")

    monkeypatch.setattr(pushkey.pushkey_connect_migrate, "dismiss_notice", refuse)
    app, win = NoticeApp(), FakeWin()

    _ok(lambda: app._notice_hide(win))

    assert box.calls == [(
        "warning", "Pushkey", "The notice could not be hidden. It will show again next time.")]
    assert win.destroyed is False  # still there to try again or press Later
    assert load_config(strict=True)["connect_notice"] == notice


def test_notice_only_the_hide_button_can_dismiss():
    for name in ("_show_connect_notice", "_open_connect_notice", "_notice_later"):
        assert "dismiss_notice" not in inspect.getsource(getattr(pushkey.PushkeyApp, name)), name
    assert "dismiss_notice" in inspect.getsource(pushkey.PushkeyApp._notice_hide)
    builder = inspect.getsource(pushkey.PushkeyApp._open_connect_notice)
    # The window's own X is "Later", and there is no "don't show again" checkbox.
    assert "WM_DELETE_WINDOW" in builder and "_notice_later" in builder
    assert "CTkCheckBox" not in builder and "show again" not in builder
    assert "Hide this notice" in builder and "Later" in builder and "Pick keys" in builder


def test_show_connect_notice_opens_the_modal_with_names_only(world, box):
    folders, _notice = _notice_world(world)
    app = NoticeApp()

    _ok(lambda: app._show_connect_notice(world.app.vault))

    assert len(app.opened) == 1 and box.calls == []  # one modal, no message boxes
    text = repr(app.opened[0])
    for expected in ("old-0", "old-1", "PROD_KEY", "lost", "OTHER_KEY", "C:/work/elsewhere"):
        assert expected in text
    assert OLD not in text and OTHER not in text
    assert load_config(strict=True).get("connect_notice")  # showing it never dismisses


def test_show_connect_notice_with_nothing_to_show_opens_nothing(world, box):
    save_config({"projects": {}, "connect_schema": 1})
    app = NoticeApp()

    _ok(lambda: app._show_connect_notice(world.app.vault))

    assert app.opened == [] and box.calls == []


def test_connect_notice_view_title_rows_and_counts(world, box):
    folders, notice = _notice_world(world, count=2)
    world.connect(STRIPE, folders[0], write=False)
    config = load_config(strict=True)

    view = _ok(lambda: pushkey._connect_notice_view(notice, config, world.app.vault))

    assert isinstance(view, dict)
    assert view["title"] == "2 projects used to get every key"
    assert [(row[1], row[2]) for row in view["rows"]] == [("old-0", "· 1 key"), ("old-1", "· 0 keys")]
    assert [row[0] for row in view["rows"]] == folders
    assert "Now a project only gets the keys you connect to it." in view["intro"]
    assert "Their .env files are not changed." in view["footer"]
    extras = "\n".join(view["extras"])
    assert "acme / PROD_KEY" in extras and "lost" in extras and "OTHER_KEY / C:/work/elsewhere" in extras

    one = pushkey._connect_notice_view(dict(notice, every_key_projects=folders[:1]), config, world.app.vault)
    assert one["title"] == "1 project used to get every key"

    none = pushkey._connect_notice_view(dict(notice, every_key_projects=[]), config, world.app.vault)
    assert none["rows"] == [] and none["title"] == "Some projects need a look"
