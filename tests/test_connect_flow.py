"""pushkey_connect flow: preview, connect, sync, status, disconnect and suggestions.

The vault is a V2 password vault seeded with one key, SUPABASE_ANON_KEY (a dummy
value), and one registered project, tmp_path/"acme-web" (tmp_path itself is the
vault directory). No test passes a real secret. A test that asserts "nothing was
written" also asserts one thing the operation did do, so it cannot pass vacuously.
"""
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import ANY

import pytest

import pushkey_connect
import pushkey_projectfs
import pushkey_shared
import pushkey_tiers
import pushkey_vault
from pushkey_connect import ConnectError
from pushkey_projectfs import ProjectPathError
from pushkey_vault import load_config, load_vault, save_vault

PASSWORD = "pw"
KEY = "SUPABASE_ANON_KEY"
VALUE = "sb_publishable_x"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _entry(**extra):
    entry = {
        "value": VALUE, "created": "2026-01-01", "rotated": None,
        "provider": "Unknown", "env": "dev", "projects": [], "connections": [], "notes": "",
    }
    entry.update(extra)
    return entry


def _conn(project, file=".env", var="A", **extra):
    return {"project": project, "file": file, "var": var, "added": "2026-11-21T10:00:00", **extra}


def _raised(call, exc_type):
    """The exception `call` raises, or None. An exception of another type fails the test."""
    try:
        call()
    except Exception as exc:
        assert isinstance(exc, exc_type), f"expected {exc_type.__name__}, got {exc!r}"
        return exc
    return None


def _ok(call):
    """The result of `call`; an exception is a failed assertion, not a test error."""
    try:
        return call()
    except Exception as exc:
        raise AssertionError(f"unexpected {exc!r}") from exc


def _only(items):
    """The single item of `items`; any other length is a failed assertion, not an IndexError."""
    items = list(items)
    assert len(items) == 1, f"expected exactly one item, got {len(items)}"
    return items[0]


def _git(folder, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=folder, check=True, capture_output=True,
    )


def _track(folder, relpath):
    """Make git track `relpath` (a committed secret file) in a fresh repo at `folder`."""
    _git(folder, "init")
    _git(folder, "add", "-f", relpath)
    _git(folder, "commit", "-m", "add")


def _backups():
    return sorted(Path(pushkey_shared.ENV_BACKUPS_DIR).rglob("*.bak"))


class _World:
    """A seeded vault, one registered project and the credentials of one entry point."""

    def __init__(self, root):
        self.root = root
        self.folder = root / "acme-web"
        self.folder.mkdir()
        self.project, _ = pushkey_connect.register_project(str(self.folder))
        save_vault({KEY: _entry(provider="Supabase")}, PASSWORD)
        self.auth = {"vault_key": None, "password": PASSWORD}

    def vault(self):
        loaded, _ = load_vault(PASSWORD)
        return loaded

    def config(self):
        return load_config(strict=True)

    def set_vault(self, change):
        vault = self.vault()
        change(vault)
        save_vault(vault, PASSWORD)

    def add_key(self, name, **extra):
        self.set_vault(lambda vault: vault.update({name: _entry(**extra)}))

    def add_project(self, name):
        folder = self.root / name
        folder.mkdir()
        canonical, _ = pushkey_connect.register_project(str(folder))
        return folder, canonical

    def rotate(self, name, new_value):
        pushkey_connect.commit(
            lambda vault: pushkey_connect.replace_value(vault[name], new_value), **self.auth
        )

    def connect(self, **kw):
        args = {"key_name": KEY, "project": self.project, "actor": "test", **self.auth, **kw}
        return pushkey_connect.connect(**args)

    def sync(self, **kw):
        return pushkey_connect.sync(actor="test", **self.auth, **kw)

    def preview(self, **kw):
        args = {"key_name": KEY, "project": self.project, **kw}
        return pushkey_connect.preview(self.vault(), self.config(), **args)

    def status(self, **kw):
        return pushkey_connect.status(self.vault(), self.config(), **kw)

    def disconnect(self, **kw):
        args = {
            "key_name": KEY, "project": self.project, "file": ".env", "var": KEY,
            "actor": "test", **self.auth, **kw,
        }
        return pushkey_connect.disconnect(**args)

    def conns(self, name=KEY):
        return self.vault()[name]["connections"]

    def read(self, relpath, folder=None):
        return ((folder or self.folder) / relpath).read_bytes().decode("utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(pushkey_tiers, "current_tier", lambda: "pro")
    return _World(tmp_path)


# -- preview ---------------------------------------------------------------------


def test_preview_line_and_defaults(world):
    shown = world.preview()

    assert shown.line == "Save to acme-web -> dev -> .env as SUPABASE_ANON_KEY"
    assert shown.change == "add"
    assert shown.gitignore_change is True
    assert (shown.key, shown.project, shown.project_name) == (KEY, world.project, "acme-web")
    assert (shown.file, shown.var, shown.environment) == (".env", KEY, "dev")
    assert shown.needs_confirm == [] and shown.conflict_key is None
    assert not (world.folder / ".env").exists() and not (world.folder / ".gitignore").exists()


def test_preview_uses_the_projects_default_file_and_environment(world):
    def change(config):
        record = config["projects"][world.project]
        record["default_file"] = ".env.staging"
        record["environment"] = "prod"

    pushkey_vault.update_config(change)
    world.set_vault(lambda vault: vault[KEY].update(env="prod"))

    shown = world.preview(var="API_KEY")

    assert shown.line == "Save to acme-web -> prod -> .env.staging as API_KEY"
    assert shown.needs_confirm == []


def test_preview_reads_the_file_to_tell_add_replace_and_none(world):
    target = world.folder / ".env"
    target.write_bytes(b"OTHER=1\n")
    assert world.preview().change == "add"
    target.write_bytes(f"{KEY}=old\n".encode())
    assert world.preview().change == "replace"
    target.write_bytes(f'export {KEY} = "{VALUE}"\n'.encode())
    assert world.preview().change == "none"


def test_preview_gitignore_change_is_false_when_the_file_is_already_ignored(world):
    assert world.preview().gitignore_change is True
    (world.folder / ".gitignore").write_bytes(b"node_modules\n.env*\n")
    assert world.preview().gitignore_change is False


def test_preview_refuses_what_it_cannot_resolve(world):
    stranger = world.root / "stranger"
    stranger.mkdir()

    def code_of(**kw):
        error = _raised(lambda: world.preview(**kw), ConnectError)
        return error.code if error else None

    assert code_of(key_name="NOPE") == "key_not_found"
    assert code_of(project=str(stranger)) == "project_not_registered"
    assert code_of(var="BAD-NAME") == "invalid_var"
    assert code_of(var="1STARTS_WITH_DIGIT") == "invalid_var"
    assert code_of(var="TRAILING_NEWLINE\n") == "invalid_var"
    for bad_file in ("../.env", ".env.example", "notes.txt"):
        assert _raised(lambda: world.preview(file=bad_file), ProjectPathError) is not None, bad_file


def test_preview_refuses_a_tracked_file(world):
    (world.folder / ".env.local").write_bytes(b"A=1\n")
    _track(world.folder, ".env.local")

    error = _raised(lambda: world.preview(file=".env.local"), ConnectError)

    assert error is not None and error.code == "file_tracked_by_git"


def test_preview_names_the_key_that_holds_the_variable(world):
    world.add_key("OTHER", value="other-value")
    _ok(lambda: world.connect(key_name="OTHER", var="SHARED"))

    error = _raised(lambda: world.preview(var="SHARED"), ConnectError)
    assert error is not None and error.code == "var_taken"
    assert error.detail == {"key": "OTHER"}

    shown = world.preview(var="SHARED", replace_source=True)
    assert shown.conflict_key == "OTHER"
    assert shown.change == "replace"


@pytest.mark.parametrize(
    "key_env, expected",
    [("dev", []), ("all", []), ("prod", ["env_mismatch"]), ("staging", ["env_mismatch"])],
)
def test_preview_env_mismatch(world, key_env, expected):
    world.set_vault(lambda vault: vault[KEY].update(env=key_env))

    assert world.preview().needs_confirm == expected


def test_preview_env_matches_the_projects_own_environment(world):
    pushkey_vault.update_config(lambda c: c["projects"][world.project].update(environment="prod"))
    world.set_vault(lambda vault: vault[KEY].update(env="prod"))
    assert world.preview().needs_confirm == []
    world.set_vault(lambda vault: vault[KEY].update(env="dev"))
    assert world.preview().needs_confirm == ["env_mismatch"]


@pytest.mark.parametrize(
    "prefix",
    ["NEXT_PUBLIC_", "VITE_", "PUBLIC_", "REACT_APP_", "EXPO_PUBLIC_", "NUXT_PUBLIC_"],
)
def test_preview_public_prefix_for_every_browser_prefix(world, prefix):
    world.add_key("BACKEND_SECRET", value="eyJxyz")

    shown = world.preview(key_name="BACKEND_SECRET", var=f"{prefix}SECRET")

    assert shown.needs_confirm == ["public_prefix"]


@pytest.mark.parametrize(
    "key_name, var, value, expected",
    [
        ("BACKEND_SECRET", "SECRET", "eyJx", []),                              # no browser prefix
        ("BACKEND_SECRET", "MY_VITE_SECRET", "eyJx", []),                      # prefix must start the name
        ("BACKEND_SECRET", "NEXT_PUBLIC_SECRET", "pk_live_abc", []),           # publishable value
        ("BACKEND_SECRET", "NEXT_PUBLIC_SECRET", "sb_publishable_abc", []),
        ("BACKEND_ANON", "VITE_SECRET", "eyJx", []),                           # marker in the key name
        ("BACKEND_SECRET", "VITE_ANON_KEY", "eyJx", []),                       # markers in the variable
        ("BACKEND_SECRET", "VITE_STRIPE_PUBLISHABLE", "eyJx", []),
        ("BACKEND_SECRET", "VITE_PUBLIC_KEY_ID", "eyJx", []),
        ("BACKEND_SECRET", "NEXT_PUBLIC_API_URL", "eyJx", []),
        ("BACKEND_SECRET", "NEXT_PUBLIC_GITHUB_CLIENT_ID", "eyJx", []),
        ("BACKEND_SECRET", "NEXT_PUBLIC_SECRET", "eyJx", ["public_prefix"]),
        ("BACKEND_SECRET", "NEXT_PUBLIC_SECRET", "sk_live_abc", ["public_prefix"]),
    ],
)
def test_preview_public_prefix_exemptions(world, key_name, var, value, expected):
    world.add_key(key_name, value=value)

    assert world.preview(key_name=key_name, var=var).needs_confirm == expected


# -- connect ---------------------------------------------------------------------


def test_connect_writes_and_records(world):
    result = _ok(lambda: world.connect(file=".env.local", var="NEXT_PUBLIC_SUPABASE_ANON_KEY"))

    assert isinstance(result, pushkey_connect.ConnectResult)
    assert (result.key, result.project, result.file) == (KEY, world.project, ".env.local")
    assert result.var == "NEXT_PUBLIC_SUPABASE_ANON_KEY"
    assert result.written is True and result.reason is None
    assert result.change == "add" and result.gitignore_changed is True
    assert f"NEXT_PUBLIC_SUPABASE_ANON_KEY={VALUE}\n" in world.read(".env.local")
    assert ".env.local" in world.read(".gitignore").splitlines()
    entry = world.vault()[KEY]
    assert entry["connections"] == [
        {"project": world.project, "file": ".env.local",
         "var": "NEXT_PUBLIC_SUPABASE_ANON_KEY", "added": ANY}
    ]
    assert TIMESTAMP.match(entry["connections"][0]["added"])
    assert world.project in entry["projects"]


def test_connect_into_a_subfolder_lists_the_exact_path_in_gitignore(world):
    (world.folder / "apps" / "web").mkdir(parents=True)

    result = _ok(lambda: world.connect(file="apps/web/.env.local", var="API_KEY"))

    assert result.written is True
    assert f"API_KEY={VALUE}\n" in world.read("apps/web/.env.local")
    assert "apps/web/.env.local" in world.read(".gitignore").splitlines()
    assert world.vault()[KEY]["connections"][0]["file"] == "apps/web/.env.local"


def test_connect_into_a_missing_subfolder_is_refused_and_creates_nothing(world):
    error = _raised(lambda: world.connect(file="apps/web/.env.local", var="API_KEY"), ProjectPathError)

    assert error is not None
    assert not (world.folder / "apps").exists()
    assert world.conns() == []


def test_connect_refuses_unregistered_folder(world):
    stranger = world.root / "stranger"
    stranger.mkdir()

    error = _raised(lambda: world.connect(project=str(stranger)), ConnectError)

    assert error is not None and error.code == "project_not_registered"
    assert not (stranger / ".env").exists()
    assert world.conns() == []
    assert world.vault()[KEY]["projects"] == []


def test_connect_refuses_escape_path(world):
    error = _raised(lambda: world.connect(file="../.env"), ProjectPathError)

    assert error is not None
    assert not (world.root / ".env").exists()
    assert world.conns() == []


def test_connect_refuses_a_template_file_before_it_writes(world):
    before = pushkey_shared.VAULT_FILE.read_bytes()

    error = _raised(lambda: world.connect(file=".env.example"), ProjectPathError)

    assert error is not None and error.reason == "env template files are read-only"
    assert not (world.folder / ".env.example").exists()
    assert pushkey_shared.VAULT_FILE.read_bytes() == before


def test_connect_refuses_tracked_file(world):
    secret = world.folder / ".env.local"
    secret.write_bytes(b"COMMITTED=1\n")
    _track(world.folder, ".env.local")
    before = secret.read_bytes()

    error = _raised(lambda: world.connect(file=".env.local"), ConnectError)

    assert error is not None and error.code == "file_tracked_by_git"
    assert secret.read_bytes() == before
    assert world.conns() == []


def test_connect_refuses_an_invalid_variable_and_a_missing_key(world):
    error = _raised(lambda: world.connect(var="BAD-NAME"), ConnectError)
    assert error is not None and error.code == "invalid_var"
    error = _raised(lambda: world.connect(key_name="NOPE"), ConnectError)
    assert error is not None and error.code == "key_not_found"
    assert world.conns() == []


def test_connect_value_on_existing_key_needs_replace(world):
    _ok(lambda: world.connect(file=".env.local", var="FIRST"))

    error = _raised(lambda: world.connect(value="v2"), ConnectError)
    assert error is not None and error.code == "key_exists"
    assert world.vault()[KEY]["value"] == VALUE

    _ok(lambda: world.connect(value="v2", replace=True, file=".env", var="SECOND"))

    entry = world.vault()[KEY]
    assert entry["value"] == "v2"
    assert entry["history"][0]["value"] == VALUE
    assert entry["rotation_count"] == 1
    assert [c["var"] for c in entry["connections"]] == ["FIRST", "SECOND"]
    assert "SECOND=v2\n" in world.read(".env")


def test_connect_creates_a_new_key_with_a_value(world):
    result = _ok(
        lambda: world.connect(key_name="STRIPE_SECRET_KEY", value="sk_test_abc", notes="billing", var="STRIPE_KEY")
    )

    assert result.written is True
    entry = world.vault()["STRIPE_SECRET_KEY"]
    assert entry["value"] == "sk_test_abc"
    assert entry["provider"] == "Stripe"
    assert entry["env"] == "dev"
    assert entry["notes"] == "billing"
    assert entry["rotation_count"] == 0
    assert TIMESTAMP.match(entry["created"])
    assert entry["projects"] == [world.project]
    assert [c["var"] for c in entry["connections"]] == ["STRIPE_KEY"]
    assert "STRIPE_KEY=sk_test_abc\n" in world.read(".env")


def test_connect_new_key_takes_the_given_provider_and_env(world):
    first = _ok(lambda: world.connect(key_name="MYSTERY", value="zzz", provider="Acme", env="all"))
    second = _ok(lambda: world.connect(key_name="UNKNOWN_THING", value="q", var="Q"))

    assert first.written is True and second.written is True
    vault = world.vault()
    assert (vault["MYSTERY"]["provider"], vault["MYSTERY"]["env"]) == ("Acme", "all")
    assert vault["UNKNOWN_THING"]["provider"] == "Unknown"


def test_public_prefix_needs_confirmation(world):
    world.add_key("SUPABASE_SERVICE_ROLE_KEY", value="eyJhbGciOiJIUzI1NiJ9.dummy")

    error = _raised(
        lambda: world.connect(key_name="SUPABASE_SERVICE_ROLE_KEY", var="NEXT_PUBLIC_SR"), ConnectError
    )

    assert error is not None and error.code == "confirmation_required"
    assert error.detail == {"needs": ["public_prefix"]}
    assert not (world.folder / ".env").exists()
    assert world.conns("SUPABASE_SERVICE_ROLE_KEY") == []

    result = _ok(
        lambda: world.connect(
            key_name="SUPABASE_SERVICE_ROLE_KEY", var="NEXT_PUBLIC_SR", confirmed={"public_prefix"}
        )
    )

    assert result.written is True
    assert "NEXT_PUBLIC_SR=eyJhbGciOiJIUzI1NiJ9.dummy\n" in world.read(".env")


def test_env_mismatch_needs_confirmation(world):
    world.add_key("PROD_KEY", value="prod-value", env="prod")

    error = _raised(lambda: world.connect(key_name="PROD_KEY"), ConnectError)

    assert error is not None and error.code == "confirmation_required"
    assert error.detail == {"needs": ["env_mismatch"]}
    assert not (world.folder / ".env").exists()

    result = _ok(lambda: world.connect(key_name="PROD_KEY", confirmed=["env_mismatch"]))

    assert result.written is True
    assert "PROD_KEY=prod-value\n" in world.read(".env")


def test_confirmation_lists_only_what_is_still_missing(world):
    world.add_key("PROD_KEY", value="eyJx", env="prod")

    error = _raised(
        lambda: world.connect(key_name="PROD_KEY", var="VITE_PROD", confirmed={"env_mismatch"}), ConnectError
    )

    assert error is not None and error.detail == {"needs": ["public_prefix"]}


def test_missing_confirmation_saves_nothing_for_a_new_key(world):
    before = pushkey_shared.VAULT_FILE.read_bytes()

    error = _raised(
        lambda: world.connect(key_name="NEW_SECRET", value="eyJx", var="NEXT_PUBLIC_NEW"), ConnectError
    )

    assert error is not None and error.code == "confirmation_required"
    assert pushkey_shared.VAULT_FILE.read_bytes() == before
    assert "NEW_SECRET" not in world.vault()
    assert not (world.folder / ".env").exists()


def test_var_taken_by_other_key(world):
    world.add_key("OTHER", value="other-value")
    (world.folder / ".env").write_bytes(b"KEEP=1\n")
    _ok(lambda: world.connect(key_name="OTHER", var="SHARED"))
    before = (world.folder / ".env").read_bytes()

    error = _raised(lambda: world.connect(var="SHARED"), ConnectError)

    assert error is not None and error.code == "var_taken"
    assert error.detail["key"] == "OTHER"
    assert (world.folder / ".env").read_bytes() == before
    assert world.conns() == []


def test_replace_source_takes_the_variable_over(world):
    world.add_key("OTHER", value="other-value")
    _ok(lambda: world.connect(key_name="OTHER", var="SHARED"))

    result = _ok(lambda: world.connect(var="SHARED", replace_source=True))

    assert result.written is True and result.change == "replace"
    assert f"SHARED={VALUE}\n" in world.read(".env")
    vault = world.vault()
    assert vault["OTHER"]["connections"] == [] and vault["OTHER"]["projects"] == []
    assert [c["var"] for c in vault[KEY]["connections"]] == ["SHARED"]


def test_connect_replaces_the_line_keeps_the_rest_and_backs_up_the_old_file(world):
    old = b"# mine\nNEXT_PUBLIC_X=old\nB=2\n"
    (world.folder / ".env.local").write_bytes(old)

    result = _ok(lambda: world.connect(file=".env.local", var="NEXT_PUBLIC_X"))

    assert result.change == "replace"
    assert world.read(".env.local") == f"# mine\nNEXT_PUBLIC_X={VALUE}\nB=2\n"
    backups = _backups()
    assert len(backups) == 1 and backups[0].read_bytes() == old
    assert not list(world.folder.glob("*.bak")) and not list(world.folder.glob(".env.pushkey_backup_*"))


def test_connect_twice_keeps_one_connection_and_touches_nothing(world):
    first = _ok(lambda: world.connect(var="API_KEY"))
    assert first.written is True
    before = (world.folder / ".env").read_bytes()
    backups = len(_backups())

    result = _ok(lambda: world.connect(var="API_KEY"))

    assert result.written is True and result.change == "none" and result.gitignore_changed is False
    assert (world.folder / ".env").read_bytes() == before
    assert len(_backups()) == backups
    assert len(world.conns()) == 1


def test_connect_keeps_bom_and_crlf(world):
    (world.folder / ".env").write_bytes(b"\xef\xbb\xbfA=1\r\nB=2\r\n")

    _ok(lambda: world.connect(var="API_KEY"))

    data = (world.folder / ".env").read_bytes()
    assert data.startswith(b"\xef\xbb\xbfA=1\r\nB=2\r\n")
    assert data.count(b"\r\n") == data.count(b"\n") and b"API_KEY=" in data


def test_connect_with_write_false_saves_the_connection_only(world):
    result = _ok(lambda: world.connect(write=False))

    assert result.written is False and result.reason == "write_skipped"
    assert not (world.folder / ".env").exists() and not (world.folder / ".gitignore").exists()
    conn = _only(world.conns())
    assert conn["var"] == KEY and "last_error" not in conn
    assert _only(world.status()).state == "file_missing"


def test_connect_reports_a_file_it_cannot_rewrite(world):
    (world.folder / ".env").write_bytes(b"A=1\rB=2\r")  # bare CR line endings

    result = _ok(lambda: world.connect())

    assert result.written is False and result.reason == "invalid_env_file"
    assert (world.folder / ".env").read_bytes() == b"A=1\rB=2\r"
    assert _only(world.conns())["last_error"] == "invalid_env_file"


def test_connect_rechecks_the_registration_inside_the_save(world, monkeypatch):
    real_commit = pushkey_connect.commit

    def unregistered_just_before_the_save(mutate, **kw):
        pushkey_vault.update_config(lambda config: config["projects"].pop(world.project))
        return real_commit(mutate, **kw)

    monkeypatch.setattr(pushkey_connect, "commit", unregistered_just_before_the_save)
    before = pushkey_shared.VAULT_FILE.read_bytes()

    error = _raised(lambda: world.connect(key_name="NEW_KEY", value="v"), ConnectError)

    assert error is not None and error.code == "project_not_registered"
    assert pushkey_shared.VAULT_FILE.read_bytes() == before
    assert not (world.folder / ".env").exists()


def test_failed_write_is_not_written(world, monkeypatch):
    reason = "project directory identity changed during write"

    def refuse(*args, **kwargs):
        raise ProjectPathError(409, reason)

    with monkeypatch.context() as patched:
        patched.setattr(pushkey_projectfs, "atomic_project_write", refuse)
        result = _ok(lambda: world.connect())

    assert result.written is False and result.reason == reason
    conn = _only(world.conns())
    assert conn["var"] == KEY and conn["last_error"] == reason
    state = _only(world.status())
    assert (state.state, state.reason) == ("not_written", reason)

    synced = _ok(lambda: world.sync())

    assert [(r.written, r.reason) for r in synced] == [(True, None)]
    assert "last_error" not in _only(world.conns())
    assert _only(world.status()).state == "up_to_date"
    assert f"{KEY}={VALUE}\n" in world.read(".env")


def test_a_gitignore_failure_after_the_file_is_written_is_reported(world, monkeypatch):
    real_write = pushkey_projectfs.atomic_project_write

    def refuse_gitignore(registered, relpath, *args, **kwargs):
        if relpath == ".gitignore":
            raise ProjectPathError(400, "refusing link or reparse-point project target")
        return real_write(registered, relpath, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(pushkey_projectfs, "atomic_project_write", refuse_gitignore)
        result = _ok(lambda: world.connect())

    assert result.written is False and result.reason == "refusing link or reparse-point project target"
    assert f"{KEY}={VALUE}\n" in world.read(".env")
    assert _only(world.conns())["last_error"] == result.reason


def test_connect_survives_a_failed_second_save(world, monkeypatch):
    real_commit = pushkey_connect.commit
    calls = []

    def second_save_fails(mutate, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise ConnectError("vault_changed")
        return real_commit(mutate, **kw)

    (world.folder / ".env").write_bytes(b"A=1\rB=2\r")
    monkeypatch.setattr(pushkey_connect, "commit", second_save_fails)

    result = _ok(lambda: world.connect())

    assert len(calls) == 2
    assert result.written is False and result.reason == "invalid_env_file"
    assert _only(world.conns())["var"] == KEY


def test_connect_result_and_log_have_no_value(world, monkeypatch):
    messages = []
    monkeypatch.setattr(pushkey_connect, "log_event", messages.append)
    world.add_key("PROD_KEY", value="prod-secret-value", env="prod")

    result = _ok(lambda: world.connect())
    refused = _raised(lambda: world.connect(key_name="PROD_KEY"), ConnectError)
    world.rotate(KEY, "sb_publishable_y")
    synced = _ok(lambda: world.sync())

    assert messages[:1] == [f"test: connected {KEY} -> acme-web .env as {KEY}"]
    assert refused is not None
    blob = " ".join(messages) + repr(result) + repr(synced) + repr(refused) + repr(refused.detail)
    for secret in (VALUE, "sb_publishable_y", "prod-secret-value"):
        assert secret not in blob


# -- sync ------------------------------------------------------------------------


def test_sync_replaces_after_rotation(world):
    _ok(lambda: world.connect())
    world.rotate(KEY, "sb_publishable_y")
    shutil.rmtree(pushkey_shared.ENV_BACKUPS_DIR, ignore_errors=True)

    results = _ok(lambda: world.sync(key_name=KEY))

    assert [(r.key, r.file, r.var, r.written, r.change) for r in results] == [
        (KEY, ".env", KEY, True, "replace")
    ]
    assert f"{KEY}=sb_publishable_y\n" in world.read(".env")
    backups = _backups()
    assert len(backups) == 1 and f"{KEY}={VALUE}".encode() in backups[0].read_bytes()


def test_sync_writes_each_file_once(world):
    world.add_key("OTHER", value="other-value")
    _ok(lambda: world.connect(var="FIRST"))
    _ok(lambda: world.connect(key_name="OTHER", var="SECOND"))
    world.rotate(KEY, "sb_publishable_y")
    world.rotate("OTHER", "other-value-2")
    shutil.rmtree(pushkey_shared.ENV_BACKUPS_DIR, ignore_errors=True)

    results = _ok(lambda: world.sync())

    assert sorted((r.key, r.written) for r in results) == [("OTHER", True), (KEY, True)]
    assert len(_backups()) == 1
    text = world.read(".env")
    assert "FIRST=sb_publishable_y\n" in text and "SECOND=other-value-2\n" in text


def test_sync_of_an_up_to_date_file_rewrites_nothing(world):
    assert _ok(lambda: world.connect()).written is True
    before = (world.folder / ".env").read_bytes()
    backups = len(_backups())

    results = _ok(lambda: world.sync())

    assert [(r.written, r.reason, r.change) for r in results] == [(True, None, "none")]
    assert (world.folder / ".env").read_bytes() == before
    assert len(_backups()) == backups


def test_sync_filters_by_key_and_by_project(world):
    second, second_path = world.add_project("beta-app")
    world.add_key("OTHER", value="other-value")
    _ok(lambda: world.connect())
    _ok(lambda: world.connect(project=second_path))
    _ok(lambda: world.connect(key_name="OTHER"))
    world.rotate(KEY, "sb_publishable_y")
    world.rotate("OTHER", "other-value-2")

    results = _ok(lambda: world.sync(key_name=KEY, project=second_path))

    assert [(r.key, r.project) for r in results] == [(KEY, second_path)]
    assert f"{KEY}=sb_publishable_y\n" in world.read(".env", second)
    assert f"{KEY}={VALUE}\n" in world.read(".env")
    assert "OTHER=other-value\n" in world.read(".env")


def test_sync_refuses_an_unknown_key(world):
    error = _raised(lambda: world.sync(key_name="NOPE"), ConnectError)

    assert error is not None and error.code == "key_not_found"


def test_status_folder_missing(world):
    _ok(lambda: world.connect())
    shutil.rmtree(world.folder)

    results = _ok(lambda: world.sync())

    assert [(r.written, r.reason) for r in results] == [(False, "folder_missing")]
    assert "last_error" not in _only(world.conns())
    assert _only(world.status()).state == "folder_missing"


def test_sync_refuses_a_file_git_tracks_and_leaves_its_bytes(world):
    (world.folder / ".env.local").write_bytes(b"A=1\n")
    _ok(lambda: world.connect(file=".env.local"))
    _track(world.folder, ".env.local")
    before = (world.folder / ".env.local").read_bytes()
    world.rotate(KEY, "sb_publishable_y")

    results = _ok(lambda: world.sync())

    assert [(r.written, r.reason) for r in results] == [(False, "file_tracked_by_git")]
    assert (world.folder / ".env.local").read_bytes() == before
    assert _only(world.conns())["last_error"] == "file_tracked_by_git"
    assert _only(world.status()).state == "not_written"


def test_sync_refuses_a_template_name_before_it_writes(world):
    world.set_vault(
        lambda vault: vault[KEY].update(
            projects=[world.project], connections=[_conn(world.project, ".env.example", "X")]
        )
    )

    results = _ok(lambda: world.sync())

    assert [(r.written, r.reason) for r in results] == [(False, "env template files are read-only")]
    assert not (world.folder / ".env.example").exists()


def test_sync_refuses_a_connection_to_an_unregistered_project(world):
    stranger = world.root / "stranger"
    stranger.mkdir()
    canonical = str(stranger.resolve())
    world.set_vault(
        lambda vault: vault[KEY].update(projects=[canonical], connections=[_conn(canonical, ".env", "X")])
    )

    results = _ok(lambda: world.sync())

    assert [(r.written, r.reason) for r in results] == [(False, "project_not_registered")]
    assert not (stranger / ".env").exists()


def test_one_unwritable_file_does_not_stop_the_other_connections(world):
    (world.folder / ".env.local").write_bytes(b"A=1\rB=2\r")
    world.set_vault(
        lambda vault: vault[KEY].update(
            projects=[world.project],
            connections=[_conn(world.project, ".env.local", "FIRST"), _conn(world.project, ".env", "SECOND")],
        )
    )

    results = _ok(lambda: world.sync())

    assert [(r.var, r.written, r.reason) for r in results] == [
        ("FIRST", False, "invalid_env_file"),
        ("SECOND", True, None),
    ]
    assert f"SECOND={VALUE}\n" in world.read(".env")
    assert (world.folder / ".env.local").read_bytes() == b"A=1\rB=2\r"


def test_sync_returns_its_results_when_recording_them_fails(world, monkeypatch):
    (world.folder / ".env").write_bytes(b"A=1\rB=2\r")
    world.set_vault(
        lambda vault: vault[KEY].update(
            projects=[world.project], connections=[_conn(world.project, ".env", KEY)]
        )
    )

    def busy(mutate, **kw):
        raise ConnectError("vault_changed")

    monkeypatch.setattr(pushkey_connect, "commit", busy)

    results = _ok(lambda: world.sync())

    assert [(r.written, r.reason) for r in results] == [(False, "invalid_env_file")]


# -- status ----------------------------------------------------------------------


def test_status_states(world):
    assert _ok(lambda: world.connect(file=".env.local", var="NEXT_PUBLIC_X")).written is True
    env_file = world.folder / ".env.local"
    gitignore = world.folder / ".gitignore"
    good, ignored = env_file.read_bytes(), gitignore.read_bytes()

    def state():
        only = _only(world.status(key_name=KEY))
        assert (only.key, only.project, only.project_name) == (KEY, world.project, "acme-web")
        assert (only.file, only.var) == (".env.local", "NEXT_PUBLIC_X")
        return only.state, only.reason

    assert state() == ("up_to_date", None)
    env_file.write_bytes(b"NEXT_PUBLIC_X=edited-by-hand\n")
    assert state() == ("out_of_date", None)
    env_file.write_bytes(b"OTHER=1\n")
    assert state() == ("not_in_file", None)
    env_file.unlink()
    assert state() == ("file_missing", None)
    env_file.write_bytes(good)
    gitignore.write_bytes(b"node_modules\n")
    assert state() == ("not_ignored", None)
    gitignore.write_bytes(ignored)
    assert state() == ("up_to_date", None)
    moved = world.root / "acme-web-moved"
    world.folder.rename(moved)
    try:
        assert state() == ("folder_missing", None)
    finally:
        moved.rename(world.folder)
    assert state() == ("up_to_date", None)


def test_status_compares_none_as_the_empty_string(world):
    (world.folder / ".env").write_bytes(b"EMPTY=\n")
    (world.folder / ".gitignore").write_bytes(b".env\n")
    vault = {"EMPTY_KEY": {"value": None, "connections": [_conn(world.project, ".env", "EMPTY")]}}

    only = _only(pushkey_connect.status(vault, world.config()))

    assert only.state == "up_to_date"


def test_status_compares_quoted_and_multiline_values(world):
    (world.folder / ".env").write_bytes(b'A="two words"\nB="line oneline two"\nC=\'it is\'\nD=x # note\n')
    (world.folder / ".gitignore").write_bytes(b".env\n")
    vault = {
        "KA": {"value": "two words", "connections": [_conn(world.project, ".env", "A")]},
        "KB": {"value": "line one\nline two", "connections": [_conn(world.project, ".env", "B")]},
        "KC": {"value": "it is", "connections": [_conn(world.project, ".env", "C")]},
        "KD": {"value": "x", "connections": [_conn(world.project, ".env", "D")]},
    }

    states = [s.state for s in pushkey_connect.status(vault, world.config())]

    # "line one\nline two" is sanitized (line breaks dropped) before it is compared and written.
    assert states == ["up_to_date"] * 4


def test_status_not_written_needs_a_last_error_and_a_file_that_is_not_up_to_date(world):
    (world.folder / ".env").write_bytes(f"{KEY}={VALUE}\n".encode())
    (world.folder / ".gitignore").write_bytes(b".env\n")
    seeded = _conn(world.project, ".env", KEY, last_error="write_failed")
    world.set_vault(lambda vault: vault[KEY].update(projects=[world.project], connections=[seeded]))
    assert _only(world.status()).state == "up_to_date"

    (world.folder / ".env").write_bytes(b"OTHER=1\n")
    only = _only(world.status())
    assert (only.state, only.reason) == ("not_written", "write_failed")


def test_status_does_not_read_a_template_file(world):
    (world.folder / ".env.example").write_bytes(b"X=v\n")
    vault = {"K": {"value": "v", "connections": [_conn(world.project, ".env.example", "X")]}}

    only = _only(pushkey_connect.status(vault, world.config()))

    assert only.state == "not_written" and only.reason == "env template files are read-only"


def test_status_filters_and_never_shows_a_value(world):
    second, second_path = world.add_project("beta-app")
    world.add_key("OTHER", value="other-value-zzz")
    _ok(lambda: world.connect())
    _ok(lambda: world.connect(project=second_path))
    _ok(lambda: world.connect(key_name="OTHER"))

    everything = world.status()
    assert [(s.key, s.project_name) for s in everything] == [
        (KEY, "acme-web"), (KEY, "beta-app"), ("OTHER", "acme-web"),
    ]
    assert [s.key for s in world.status(key_name="OTHER")] == ["OTHER"]
    assert [s.project for s in world.status(project=second_path)] == [second_path]
    assert world.status(key_name="NOPE") == []
    assert VALUE not in repr(everything) and "other-value-zzz" not in repr(everything)


# -- disconnect ------------------------------------------------------------------


def _connected(world, **kw):
    """Connect and assert it worked, so a disconnect test starts from a real connection."""
    result = _ok(lambda: world.connect(**kw))
    assert result.written is True
    return result


def test_disconnect_removes_the_connection_and_the_last_allowlist_entry(world):
    (world.folder / ".env").write_bytes(b"KEEP=1\n")
    _connected(world)
    before = (world.folder / ".env").read_bytes()

    result = _ok(lambda: world.disconnect())

    assert isinstance(result, pushkey_connect.CommitResult)
    entry = world.vault()[KEY]
    assert entry["connections"] == [] and entry["projects"] == []
    assert (world.folder / ".env").read_bytes() == before
    assert result.value == {"line_removed": False, "reason": None}


def test_disconnect_keeps_the_allowlist_while_another_connection_to_the_project_remains(world):
    _connected(world, var="FIRST")
    _connected(world, var="SECOND", file=".env.local")

    _ok(lambda: world.disconnect(var="FIRST"))

    entry = world.vault()[KEY]
    assert [c["var"] for c in entry["connections"]] == ["SECOND"]
    assert entry["projects"] == [world.project]


def test_disconnect_can_remove_the_line_whole_and_backs_up_the_file(world):
    _connected(world)
    old = f'# keep\n{KEY}="line1\nline2"\nB=2\n'.encode()
    (world.folder / ".env").write_bytes(old)
    shutil.rmtree(pushkey_shared.ENV_BACKUPS_DIR, ignore_errors=True)

    result = _ok(lambda: world.disconnect(remove_line=True))

    assert result.value == {"line_removed": True, "reason": None}
    assert world.read(".env") == "# keep\nB=2\n"
    assert world.conns() == []
    backups = _backups()
    assert len(backups) == 1 and backups[0].read_bytes() == old


def test_disconnect_remove_line_leaves_a_file_without_the_variable_alone(world):
    _connected(world)
    (world.folder / ".env").write_bytes(b"B=2\n")
    shutil.rmtree(pushkey_shared.ENV_BACKUPS_DIR, ignore_errors=True)

    result = _ok(lambda: world.disconnect(remove_line=True))

    assert result.value == {"line_removed": False, "reason": None}
    assert (world.folder / ".env").read_bytes() == b"B=2\n" and _backups() == []
    assert world.conns() == []


def test_disconnect_remove_line_keeps_a_tracked_file_and_says_why(world):
    (world.folder / ".env.local").write_bytes(b"A=1\n")
    _connected(world, file=".env.local")
    _track(world.folder, ".env.local")
    before = (world.folder / ".env.local").read_bytes()

    result = _ok(lambda: world.disconnect(file=".env.local", remove_line=True))

    assert result.value == {"line_removed": False, "reason": "file_tracked_by_git"}
    assert (world.folder / ".env.local").read_bytes() == before
    assert world.conns() == []


def test_disconnect_refuses_what_is_not_connected(world):
    _connected(world)
    before = pushkey_shared.VAULT_FILE.read_bytes()

    error = _raised(lambda: world.disconnect(var="NOT_CONNECTED"), ConnectError)
    assert error is not None and error.code == "connection_not_found"
    error = _raised(lambda: world.disconnect(key_name="NOPE"), ConnectError)
    assert error is not None and error.code == "key_not_found"
    assert pushkey_shared.VAULT_FILE.read_bytes() == before


def test_disconnect_logs_names_only(world, monkeypatch):
    messages = []
    monkeypatch.setattr(pushkey_connect, "log_event", messages.append)
    _connected(world)

    _ok(lambda: world.disconnect())

    assert messages[-1:] == [f"test: disconnected {KEY} -> acme-web .env as {KEY}"]
    assert VALUE not in " ".join(messages)


# -- suggestions -----------------------------------------------------------------


def _suggest(world, **kw):
    args = {"key_name": KEY, "project": world.project, **kw}
    return pushkey_connect.suggest(world.vault(), world.config(), **args)


def test_suggest_from_env_example(world):
    (world.folder / "next.config.js").write_text("module.exports = {}\n")
    (world.folder / ".env.example").write_text(
        "NEXT_PUBLIC_SUPABASE_ANON_KEY=\nOPENAI_API_KEY=\n", encoding="utf-8"
    )

    found = _suggest(world)

    assert found.files[:1] == [(".env.local", "Next.js or Vite project")]
    assert found.vars[:1] == [("NEXT_PUBLIC_SUPABASE_ANON_KEY", "found in .env.example")]
    assert "OPENAI_API_KEY" not in [name for name, _ in found.vars]
    assert found.vars[-1:] == [(KEY, "same as the key name")]


def test_suggest_reads_names_from_the_sample_and_target_files_and_skips_connected_ones(world):
    world.add_key("OTHER_SUPABASE", value="other", provider="Supabase")
    (world.folder / "vite.config.ts").write_text("export default {}\n")
    (world.folder / ".env.sample").write_text("SUPABASE_URL=https://example.invalid\n", encoding="utf-8")
    (world.folder / ".env.local").write_text("NEXT_PUBLIC_SUPABASE_JWT=dummy-secret-zzz\nUNRELATED=1\n")
    _ok(lambda: world.connect(key_name="OTHER_SUPABASE", var="SUPABASE_URL"))

    found = _suggest(world)

    assert found.vars == [
        ("NEXT_PUBLIC_SUPABASE_JWT", "found in .env.local"),
        (KEY, "same as the key name"),
    ]
    assert "dummy-secret-zzz" not in repr(found) and "example.invalid" not in repr(found)


def test_suggest_never_offers_the_key_name_twice_or_an_invalid_one(world):
    (world.folder / ".env.example").write_text(f"{KEY}=\n", encoding="utf-8")
    assert _suggest(world).vars == [(KEY, "found in .env.example")]

    world.add_key("my-dashed-key", value="v")
    assert _suggest(world, key_name="my-dashed-key").vars == []


def test_suggest_files(world):
    assert _suggest(world).files == [(".env", "default env file")]

    pushkey_vault.update_config(lambda c: c["projects"][world.project].update(default_file=".env.staging"))
    assert _suggest(world).files == [(".env.staging", "project default"), (".env", "default env file")]

    pushkey_vault.update_config(lambda c: c["projects"][world.project].update(default_file=".env.local"))
    (world.folder / "vite.config.js").write_text("export default {}\n")
    assert _suggest(world).files == [(".env.local", "project default"), (".env", "default env file")]

    pushkey_vault.update_config(lambda c: c["projects"][world.project].update(default_file=".env"))
    assert _suggest(world).files == [
        (".env.local", "Next.js or Vite project"), (".env", "default env file"),
    ]


def test_suggest_projects(world):
    last, last_path = world.add_project("last-one")
    other, other_path = world.add_project("shared-provider")
    world.add_key("SUPABASE_OTHER", value="v", provider="Supabase")
    world.add_key("STRIPE_SECRET", value="v", provider="Stripe")
    _ok(lambda: world.connect(key_name="SUPABASE_OTHER", project=other_path))
    _ok(lambda: world.connect(key_name="STRIPE_SECRET", project=last_path, var="STRIPE"))
    pushkey_vault.update_config(lambda config: config.update(last_project=last_path))
    stranger = world.root / "stranger"
    stranger.mkdir()

    found = _suggest(world, cwd=str(world.folder))

    assert found.projects == [
        (world.project, "current folder"),
        (last_path, "last used"),
        (other_path, "used with other Supabase keys"),
    ]
    assert _suggest(world, cwd=str(stranger)).projects == [
        (last_path, "last used"), (other_path, "used with other Supabase keys"),
    ]
    assert _suggest(world, cwd=last_path).projects[:1] == [(last_path, "current folder")]


def test_suggest_files_follow_the_first_project_when_none_is_chosen(world):
    (world.folder / "next.config.mjs").write_text("export default {}\n")

    found = pushkey_connect.suggest(world.vault(), world.config(), key_name=KEY, cwd=str(world.folder))

    assert found.projects == [(world.project, "current folder")]
    assert found.files[:1] == [(".env.local", "Next.js or Vite project")]
    nothing = pushkey_connect.suggest(world.vault(), world.config(), key_name=KEY)
    assert nothing.projects == [] and nothing.files == []
    assert nothing.vars == [(KEY, "same as the key name")]


# -- is_migrated and the unregister sweep -------------------------------------------


def test_is_migrated(tmp_path):
    absolute = str(tmp_path / "proj")
    cases = [
        ({}, True),
        ({"projects": {}}, True),
        ({"projects": {absolute: {"name": "p"}}}, True),
        ({"projects": {"my-project": {"path": absolute}}}, False),
        ({"projects": {absolute: {}, "my-project": {}}}, False),
        ({"connect_schema": 1, "projects": {"my-project": {}}}, True),
        ({"connect_schema": 2, "projects": {"my-project": {}}}, False),
    ]

    wrong = [(config, want) for config, want in cases if pushkey_connect.is_migrated(config) is not want]

    assert wrong == []


def test_unregister_sweeps_links_to_a_path_that_is_not_registered(world):
    stranger = world.root / "stranger"
    stranger.mkdir()
    canonical = str(stranger.resolve())
    world.set_vault(
        lambda vault: vault[KEY].update(projects=[canonical], connections=[_conn(canonical, ".env", "X")])
    )
    assert canonical not in pushkey_connect.registered_projects(world.config())

    result = _ok(lambda: pushkey_connect.unregister_project(canonical, **world.auth))

    entry = world.vault()[KEY]
    assert entry["projects"] == [] and entry["connections"] == []
    assert result.value == [KEY]
    assert list(pushkey_connect.registered_projects(world.config())) == [world.project]
