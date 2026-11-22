"""Desktop save and reload safety, and the migration at login (pushkey.py).

No Tk root: AppFrame / PushkeyApp methods are bound onto small fake objects with
`types.MethodType` (the pattern of tests/test_ui_helpers.py). The module's own
`messagebox` name is patched with a recorder. The vault is a V2 password vault and the
config is the real encrypted config.json, both under tmp_path (the vault directory).
Keys carry dummy values.
"""
import hashlib
import inspect
import re
import types

import pytest

import pushkey
import pushkey_connect
import pushkey_connect_migrate
import pushkey_crypto
import pushkey_shared
import pushkey_tiers
import pushkey_vault
from pushkey_vault import load_config, load_vault, save_config, save_vault

PASSWORD = "pw"
KEY = "OPENAI_API_KEY"
CONFLICT_TEXT = (
    "The vault changed in another Pushkey window or tool. "
    "It has been reloaded; please repeat your last change."
)
RELOAD_FAILED_TEXT = "The vault could not be reloaded. Please lock and unlock Pushkey."
PROJECT_OWNED = ("projects", "projects_legacy", "connect_schema", "connect_notice", "last_project")


def _entry(**extra):
    entry = {
        "value": "dummy-value", "created": "2026-01-01", "rotated": None,
        "provider": "Unknown", "env": "dev", "projects": [], "connections": [], "notes": "",
    }
    entry.update(extra)
    return entry


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


@pytest.fixture
def box(monkeypatch):
    fake = FakeBox()
    monkeypatch.setattr(pushkey, "messagebox", fake)
    return fake


class FakeFrame:
    """The attributes AppFrame.save / _save_config / _toggle_theme read."""

    def __init__(self, vault, key, config):
        self.password = PASSWORD
        self.vault = vault
        self.vault_key = key
        self.config = config
        self.invalidated = []
        self.app = None
        self.master = None
        self.theme_button_text = None
        self.save = types.MethodType(pushkey.AppFrame.save, self)
        self._save_config = types.MethodType(pushkey.AppFrame._save_config, self)
        self._reload_after_conflict = types.MethodType(pushkey.AppFrame._reload_after_conflict, self)
        self._toggle_theme = types.MethodType(pushkey.AppFrame._toggle_theme, self)
        self._cloud_sync_once = types.MethodType(pushkey.AppFrame._cloud_sync_once, self)
        self._theme_btn = types.SimpleNamespace(configure=self._set_theme_text)

    def _set_theme_text(self, **kw):
        self.theme_button_text = kw.get("text")

    def _invalidate_tabs(self, *tabs):
        self.invalidated.extend(tabs)


@pytest.fixture
def frame(tmp_path, monkeypatch, box):
    """A FakeFrame loaded the way AppFrame.__init__ loads: vault and config once."""
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    monkeypatch.setattr(pushkey, "set_theme", lambda mode: None)
    save_vault({KEY: _entry()}, PASSWORD)
    save_config({"projects": {}, "theme": "dark"})
    vault, key = load_vault(PASSWORD)
    return FakeFrame(vault, key, load_config())


def _ok(call):
    """The result of `call`; an exception is a failed assertion, not a test error."""
    try:
        return call()
    except Exception as exc:
        raise AssertionError(f"unexpected {exc!r}") from exc


def _external_vault_change(name="STRIPE_KEY"):
    """Another Pushkey tool saves the vault after the desktop loaded it."""
    other, _ = load_vault(PASSWORD)
    other[name] = _entry()
    save_vault(other, PASSWORD)


def _register(tmp_path, name="acme"):
    folder = tmp_path / name
    folder.mkdir()
    canonical, _ = pushkey_connect.register_project(str(folder))
    return canonical


# -- save: vault side -----------------------------------------------------------------


def test_desktop_save_normal_returns_true_and_persists(frame, box):
    frame.vault["NEW_KEY"] = _entry()

    assert frame.save() is True

    assert "NEW_KEY" in load_vault(PASSWORD)[0]
    assert box.calls == []


def test_desktop_save_reloads_after_conflict(frame, box):
    _external_vault_change()
    frame.vault["MINE"] = _entry()

    result = _ok(frame.save)

    assert result is False
    assert box.of("warning") == [("warning", "Pushkey", CONFLICT_TEXT)]
    # The desktop's copy was replaced by what is on disk: the other tool's key is
    # there, the unsaved local change is not, and the same dict object is kept.
    assert "STRIPE_KEY" in frame.vault and "MINE" not in frame.vault
    on_disk, _ = load_vault(PASSWORD)
    assert set(on_disk) == set(frame.vault)
    assert frame.vault._pushkey_revision == on_disk._pushkey_revision
    # A save after the reload carries the new revision and succeeds.
    frame.vault["MINE"] = _entry()
    assert frame.save() is True
    assert "MINE" in load_vault(PASSWORD)[0]


def test_desktop_save_conflict_returns_false_and_skips_config(frame, box, monkeypatch):
    _external_vault_change()
    frame.config["theme"] = "light"
    writes = []
    real = pushkey_vault.update_config
    monkeypatch.setattr(pushkey, "update_config", lambda mutate: writes.append(1) or real(mutate))

    assert _ok(frame.save) is False

    assert writes == []
    assert load_config()["theme"] == "dark"
    assert "keys" in frame.invalidated


def test_desktop_save_conflict_keeps_the_reloaded_vault_key(frame, box, monkeypatch):
    _external_vault_change()
    real = pushkey.load_vault
    monkeypatch.setattr(pushkey, "load_vault", lambda password: (real(password)[0], b"k" * 32))

    assert _ok(frame.save) is False

    assert frame.vault_key == b"k" * 32


def test_desktop_save_reload_failure_says_so(frame, box, monkeypatch):
    _external_vault_change()
    monkeypatch.setattr(pushkey, "load_vault", lambda password: None)

    assert _ok(frame.save) is False

    assert box.of("warning") == [("warning", "Pushkey", RELOAD_FAILED_TEXT)]


def test_desktop_save_reload_exception_says_so(frame, box, monkeypatch):
    _external_vault_change()

    def boom(password):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(pushkey, "load_vault", boom)

    assert _ok(frame.save) is False

    assert box.of("warning") == [("warning", "Pushkey", RELOAD_FAILED_TEXT)]


# -- save: config side ----------------------------------------------------------------


def test_desktop_save_keeps_projects_added_elsewhere(frame, tmp_path):
    frame.config["theme"] = "light"
    canonical = _register(tmp_path)  # another tool, after the desktop loaded config

    assert frame.save() is True

    on_disk = load_config(strict=True)
    assert canonical in on_disk["projects"]
    assert on_disk["theme"] == "light"
    assert canonical in frame.config.get("projects", {})  # refreshed for the project-owned keys


def test_desktop_save_theme_keeps_projects_added_elsewhere(frame, tmp_path, monkeypatch):
    canonical = _register(tmp_path)
    frame.app = types.SimpleNamespace(reload_app=lambda pw, vault: None)
    frame.master = types.SimpleNamespace(after=lambda delay, fn: None)
    monkeypatch.setattr(pushkey, "_CURRENT_THEME", "dark")

    frame._toggle_theme()

    on_disk = load_config(strict=True)
    assert on_disk["theme"] == "light"
    assert canonical in on_disk["projects"]


def test_desktop_theme_toggle_without_app_updates_button(frame, tmp_path, monkeypatch):
    monkeypatch.setattr(pushkey, "_CURRENT_THEME", "dark")

    frame._toggle_theme()

    assert load_config(strict=True)["theme"] == "light"
    assert frame.config["theme"] == "light"
    assert frame.theme_button_text == "\u263e"  # moon: the next click goes back to dark


def test_desktop_save_never_writes_project_owned_keys(frame, tmp_path):
    canonical = _register(tmp_path)
    before = load_config(strict=True)
    frame.config["projects"] = {"ghost": {"path": "nowhere"}}
    frame.config["projects_legacy"] = {"junk": 1}
    frame.config["connect_schema"] = 99
    frame.config["connect_notice"] = {"every_key_projects": ["x"]}
    frame.config["last_project"] = "ghost"
    frame.config["tray_notify"] = False

    assert frame._save_config() is True

    after = load_config(strict=True)
    for owned in PROJECT_OWNED:
        assert after.get(owned) == before.get(owned), owned
    assert canonical in after["projects"] and "ghost" not in after["projects"]
    assert after["tray_notify"] is False  # a desktop-owned key was written
    assert frame.config["projects"] == after["projects"]  # memory follows disk


def test_desktop_save_config_unreadable_warns_and_keeps_memory(frame, box):
    pushkey_shared.CONFIG_FILE.write_bytes(b"not a config at all")
    frame.config["theme"] = "light"

    assert frame._save_config() is False

    warnings = box.of("warning")
    assert len(warnings) == 1
    assert warnings[0][1] == "Pushkey"
    assert "Settings could not be saved" in warnings[0][2] and "config_unreadable" in warnings[0][2]
    assert frame.config["theme"] == "light"
    assert pushkey_shared.CONFIG_FILE.read_bytes() == b"not a config at all"


def test_desktop_save_config_quiet_does_not_show_a_dialog(frame, box):
    pushkey_shared.CONFIG_FILE.write_bytes(b"not a config at all")

    assert frame._save_config(quiet=True) is False

    assert box.calls == []


def test_no_direct_save_config_calls_left(frame, tmp_path, monkeypatch):
    """The save, theme and cloud paths never write the whole config."""
    def refuse(config):
        raise AssertionError("whole-config save_config called")

    monkeypatch.setattr(pushkey, "save_config", refuse)
    _register(tmp_path)
    frame.config["theme"] = "light"
    assert frame.save() is True
    monkeypatch.setattr(pushkey, "_CURRENT_THEME", "dark")
    frame.app = types.SimpleNamespace(reload_app=lambda pw, vault: None)
    frame.master = types.SimpleNamespace(after=lambda delay, fn: None)
    frame._toggle_theme()
    assert load_config(strict=True)["theme"] == "light"

    # The closures (tray toggles, SSO settings, cloud settings) cannot run without Tk:
    # prove from source that every AppFrame method calls only the helper, except the
    # one project-credentials site that belongs to Task 12.
    offenders = []
    for name, member in inspect.getmembers(pushkey.AppFrame, inspect.isfunction):
        if re.search(r"\bsave_config\(self\.config\)", inspect.getsource(member)):
            offenders.append(name)
    assert offenders == ["ci_sync_project"]


def test_desktop_cloud_sync_conflict_goes_through_the_helper(frame, tmp_path, monkeypatch):
    canonical = _register(tmp_path)
    frame.config["cloud"] = {"endpoint": "https://example.invalid", "token": "t", "etag": "e1"}
    monkeypatch.setattr(pushkey, "cloud_push", lambda *a, **k: "e2")
    monkeypatch.setattr(pushkey, "VAULT_FILE", pushkey_shared.VAULT_FILE)

    frame._cloud_sync_once(silent=True)

    on_disk = load_config(strict=True)
    assert on_disk["cloud"]["etag"] == "e2" and "last_synced" in on_disk["cloud"]
    assert canonical in on_disk["projects"]


# -- fix round 1: first-run vault, theme rebuild, config refresh ----------------------


class FakeDialog:
    """The attributes RecoverySetupDialog._submit reads (no Tk root)."""

    def __init__(self, on_confirmed):
        self._password = PASSWORD
        self._code = pushkey.generate_recovery_code()
        self._on_confirmed = on_confirmed
        self.destroyed = False
        self._submit = types.MethodType(pushkey.RecoverySetupDialog._submit, self)

    def destroy(self):
        self.destroyed = True


def test_desktop_fix1_new_vault_saves_twice_in_one_session(tmp_path, box, monkeypatch):
    """Brand-new user: the vault the dialog hands over carries a revision, so saves work."""
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    handed = []
    dialog = FakeDialog(lambda pw, vault, key: handed.append((pw, vault, key)))

    dialog._submit()

    assert len(handed) == 1
    pw, vault, key = handed[0]
    session = FakeFrame(vault, key, load_config())
    session.vault["FIRST"] = _entry()
    assert _ok(session.save) is True
    session.vault["SECOND"] = _entry()
    assert _ok(session.save) is True
    assert set(load_vault(PASSWORD)[0]) == {"FIRST", "SECOND"}
    assert box.calls == []


class FakePushkeyApp:
    """The attributes PushkeyApp.reload_app reads (no Tk root); switch records its kwargs."""

    def __init__(self):
        self.switched = []
        self.root = types.SimpleNamespace(configure=lambda **kw: None)
        self.reload_app = types.MethodType(pushkey.PushkeyApp.reload_app, self)

    def switch(self, cls, **kw):
        self.switched.append((cls, kw))

    def show_login(self):
        pass


def test_desktop_fix1_reload_app_passes_the_vault_key_to_the_frame():
    app = FakePushkeyApp()
    vault = {}

    _ok(lambda: app.reload_app(PASSWORD, vault, b"k" * 32))

    assert len(app.switched) == 1
    cls, kw = app.switched[0]
    assert cls is pushkey.AppFrame
    assert kw.get("vault_key") == b"k" * 32
    assert kw["vault"] is vault and kw["password"] == PASSWORD and kw["app"] is app


def test_desktop_fix1_theme_toggle_keeps_the_vault_key_and_saves(frame, box, monkeypatch):
    # A V3 vault: its saves need the vault key (the `frame` fixture's vault is V2).
    pushkey_shared.VAULT_FILE.unlink()
    pushkey.save_vault_and_publish(
        {KEY: _entry()}, PASSWORD, recovery_code=pushkey.generate_recovery_code())
    frame.vault, frame.vault_key = load_vault(PASSWORD)
    app = FakePushkeyApp()
    frame.app = app
    frame.master = types.SimpleNamespace(after=lambda delay, fn: fn())  # run the rebuild now
    monkeypatch.setattr(pushkey, "_CURRENT_THEME", "dark")
    old_key = frame.vault_key

    frame._toggle_theme()

    assert len(app.switched) == 1
    kw = app.switched[0][1]
    assert kw.get("vault_key") == old_key and old_key is not None
    # The rebuilt AppFrame is built from exactly these kwargs; its save must work on V3.
    rebuilt = FakeFrame(kw["vault"], kw.get("vault_key"), load_config())
    rebuilt.vault["AFTER_THEME"] = _entry()
    assert _ok(rebuilt.save) is True
    assert "AFTER_THEME" in load_vault(PASSWORD)[0]
    assert load_config(strict=True)["theme"] == "light"
    assert box.calls == []


def test_desktop_fix1_save_config_never_drops_project_keys_from_memory(frame, tmp_path, monkeypatch):
    """The worker thread runs _save_config while the UI thread reads config["projects"]."""
    canonical = _register(tmp_path)
    seen = []

    class SpyConfig(dict):
        def _note(self, what):
            seen.append((what, "projects" in self))

        def pop(self, *args):
            result = super().pop(*args)
            self._note("pop")
            return result

        def __delitem__(self, key):
            super().__delitem__(key)
            self._note("del")

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            self._note("set")

        def update(self, *args, **kwargs):
            super().update(*args, **kwargs)
            self._note("update")

    frame.config = SpyConfig(frame.config)
    frame.config["theme"] = "light"
    seen.clear()
    real = pushkey.update_config

    def spy(mutate):
        seen.append(("during_update_config", "projects" in frame.config))
        result = real(mutate)
        seen.append(("after_update_config", "projects" in frame.config))
        return result

    monkeypatch.setattr(pushkey, "update_config", spy)

    assert frame._save_config() is True

    assert seen and all(present for _what, present in seen), seen
    assert canonical in frame.config["projects"]  # still refreshed from disk


# -- login ----------------------------------------------------------------------------


class FakeApp:
    """The attributes PushkeyApp.on_login / _migrate_at_login / _show_connect_notice use."""

    def __init__(self):
        self.events = []
        self.root = None
        self.on_login = types.MethodType(pushkey.PushkeyApp.on_login, self)
        self._migrate_at_login = types.MethodType(pushkey.PushkeyApp._migrate_at_login, self)
        self._show_connect_notice = types.MethodType(pushkey.PushkeyApp._show_connect_notice, self)

    def switch(self, cls, **kw):
        self.events.append(("switch", kw["vault"]))

    def show_login(self):
        pass

    def _start_clip_watcher(self, vault):
        self.events.append(("clip",))


def _legacy_world(tmp_path):
    """A vault with one key and a desktop-shaped (name-keyed) project assigned that key."""
    folder = tmp_path / "acme"
    folder.mkdir()
    save_vault({KEY: _entry(env="dev")}, PASSWORD)
    save_config({"projects": {"acme": {
        "path": str(folder), "keys": [KEY], "added": "2026-01-02T03:04:05", "target_env": "all",
    }}})
    vault, key = load_vault(PASSWORD)
    return folder, vault, key


def test_desktop_login_runs_migration(tmp_path, box, monkeypatch):
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    folder, vault, key = _legacy_world(tmp_path)
    app = FakeApp()

    app.on_login(PASSWORD, vault, key)

    config = load_config(strict=True)
    assert config.get("connect_schema") == 1
    on_disk, _ = load_vault(PASSWORD)
    assert on_disk[KEY]["connections"]  # the assignment became a connection
    # The vault the session carries was brought up to date in place, so its first save is
    # not a conflict.
    assert vault[KEY]["connections"] == on_disk[KEY]["connections"]
    assert [e[0] for e in app.events] == ["switch", "clip"]
    assert app.events[0][1] is vault
    assert box.of("warning") == []


def test_desktop_login_migrates_before_the_frame_is_built(tmp_path, box, monkeypatch):
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    app = FakeApp()
    order = []
    monkeypatch.setattr(
        pushkey_connect_migrate, "ensure_migrated",
        lambda **kw: order.append(("migrate", kw["password"], kw["vault_key"], kw["target"])),
    )
    app.switch = lambda cls, **kw: order.append(("switch",))
    target = {}

    app.on_login(PASSWORD, target, b"k" * 32)

    assert order == [("migrate", PASSWORD, b"k" * 32, target), ("switch",)]


def test_desktop_login_survives_unreadable_config(tmp_path, box, monkeypatch):
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    save_vault({KEY: _entry()}, PASSWORD)
    pushkey_shared.CONFIG_FILE.write_bytes(b"not a config at all")
    vault, key = load_vault(PASSWORD)
    app = FakeApp()

    app.on_login(PASSWORD, vault, key)

    assert [e[0] for e in app.events] == ["switch", "clip"]  # login went on
    assert pushkey_shared.CONFIG_FILE.read_bytes() == b"not a config at all"
    assert len(box.of("warning")) == 1


def test_desktop_login_unreadable_config_warns_once(tmp_path, box, monkeypatch):
    save_vault({KEY: _entry()}, PASSWORD)
    pushkey_shared.CONFIG_FILE.write_bytes(b"not a config at all")
    vault, key = load_vault(PASSWORD)
    app = FakeApp()

    app._migrate_at_login(PASSWORD, vault, key)
    app._show_connect_notice()

    assert box.calls == [(
        "warning", "Pushkey",
        "Projects could not be migrated: your Pushkey settings file is unreadable or busy. "
        "Everything else works.",
    )]


def test_desktop_login_other_migration_error_warns_with_the_class_name(box, monkeypatch):
    class Odd(Exception):
        pass

    def boom(**kw):
        raise Odd("secret detail that must not be shown")

    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", boom)
    app = FakeApp()

    _ok(lambda: app._migrate_at_login(PASSWORD, {}, None))

    assert box.calls == [(
        "warning", "Pushkey", "Projects could not be migrated (Odd). Everything else works.",
    )]


def test_desktop_login_migration_conflict_does_not_block(box, monkeypatch):
    def boom(**kw):
        raise pushkey_connect.ConnectError("vault_changed")

    monkeypatch.setattr(pushkey_connect_migrate, "ensure_migrated", boom)
    app = FakeApp()

    _ok(lambda: app._migrate_at_login(PASSWORD, {}, None))

    assert len(box.of("warning")) == 1
    assert "vault_changed" in box.of("warning")[0][2]
    assert "Everything else works." in box.of("warning")[0][2]


# -- notice ---------------------------------------------------------------------------


NOTICE = {
    "every_key_projects": ["C:/work/acme"],
    "env_skipped": [["acme", "PROD_KEY"]],
    "unusable": ["lost"],
    "unregistered": [["OTHER_KEY", "C:/work/elsewhere"]],
}


def _notice_world(tmp_path):
    save_vault({KEY: _entry()}, PASSWORD)
    save_config({"projects": {}, "connect_schema": 1, "connect_notice": NOTICE})


def test_desktop_login_notice_dismissed_on_yes(tmp_path, box):
    _notice_world(tmp_path)
    box.answer = True
    app = FakeApp()

    app._show_connect_notice()

    info = box.of("info")
    assert len(info) == 1 and info[0][1] == "Projects were updated"
    text = info[0][2]
    for expected in ("C:/work/acme", "PROD_KEY", "lost", "OTHER_KEY", "C:/work/elsewhere"):
        assert expected in text
    assert box.of("askyesno") == [("askyesno", "Pushkey", "Hide this notice from now on?")]
    assert "connect_notice" not in load_config(strict=True)


def test_desktop_login_notice_kept_on_no(tmp_path, box):
    _notice_world(tmp_path)
    box.answer = False
    app = FakeApp()

    app._show_connect_notice()

    assert len(box.of("info")) == 1 and len(box.of("askyesno")) == 1
    assert load_config(strict=True)["connect_notice"] == NOTICE


def test_desktop_login_shows_the_notice_once_the_frame_is_built(tmp_path, box, monkeypatch):
    monkeypatch.setattr(pushkey, "write_health_sidecar", lambda vault: True)
    _notice_world(tmp_path)
    vault, key = load_vault(PASSWORD)
    app = FakeApp()
    shown_before_switch = []
    app.switch = lambda cls, **kw: shown_before_switch.append(len(box.calls))

    app.on_login(PASSWORD, vault, key)

    assert shown_before_switch == [0]  # nothing was shown while the frame was still unbuilt
    assert len(box.of("info")) == 1 and len(box.of("askyesno")) == 1


def test_desktop_login_no_notice_means_no_dialog(tmp_path, box):
    save_vault({KEY: _entry()}, PASSWORD)
    save_config({"projects": {}, "connect_schema": 1})
    app = FakeApp()

    app._show_connect_notice()

    assert box.calls == []


def test_desktop_login_empty_notice_means_no_dialog(tmp_path, box):
    save_vault({KEY: _entry()}, PASSWORD)
    save_config({"projects": {}, "connect_schema": 1, "connect_notice": {
        "every_key_projects": [], "env_skipped": []}})
    app = FakeApp()

    app._show_connect_notice()

    assert box.calls == []


def test_desktop_login_notice_dismiss_failure_warns_once(tmp_path, box, monkeypatch):
    _notice_world(tmp_path)
    box.answer = True

    def boom():
        raise RuntimeError("config_busy")

    monkeypatch.setattr(pushkey_connect_migrate, "dismiss_notice", boom)
    app = FakeApp()

    app._show_connect_notice()

    assert len(box.of("warning")) == 1
