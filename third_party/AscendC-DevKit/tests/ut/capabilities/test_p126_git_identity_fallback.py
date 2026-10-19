"""P126 — git commit identity conditional fallback (bare CI/container envs).

`git commit` refuses (rc=128 "Author identity unknown") when neither config nor
env supplies a committer identity. precision_debug's git-based rollback anchoring
then fails EVERY commit and leaves best_commit stale, so the exit-time
`git clean -fd` destroys the codegen it was meant to preserve.

`git_commit_identity_env` probes `git var GIT_COMMITTER_IDENT` and supplies a
synthetic framework identity via GIT_* env vars ONLY when git cannot otherwise
resolve one — never writing git config, never overriding a real developer's
identity. These tests are hermetic: they control the probe env (GIT_CONFIG_*)
so they do not depend on the machine's ambient global git config.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from ascendc_devkit.infra.repo_guard import (
    _FALLBACK_COMMITTER_EMAIL,
    _FALLBACK_COMMITTER_NAME,
    git_commit_identity_env,
)

_IDENT_KEYS = (
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
)


def _stripped_env(**overrides) -> dict:
    """os.environ minus any inherited git-identity signal, plus overrides.

    Removes GIT_* identity vars and points config discovery at nothing, so the
    probe result is decided solely by `overrides` — not the host's ~/.gitconfig.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull  # no global config unless overridden
    env.update(overrides)
    return env


def _write_global_config(tmp_path, body: str) -> str:
    cfg = tmp_path / "gitconfig"
    cfg.write_text(body, encoding="utf-8")
    return str(cfg)


def test_returns_empty_when_identity_in_env():
    """Explicit GIT_* identity in the env → git resolves it → no override."""
    env = _stripped_env(
        GIT_AUTHOR_NAME="Real Dev", GIT_AUTHOR_EMAIL="real@dev.example",
        GIT_COMMITTER_NAME="Real Dev", GIT_COMMITTER_EMAIL="real@dev.example",
    )
    assert git_commit_identity_env(None, env) == {}


def test_returns_empty_when_global_config_resolves(tmp_path):
    """A global config with user.name/email → resolvable → no override."""
    cfg = _write_global_config(
        tmp_path, "[user]\n\tname = Cfg Dev\n\temail = cfg@dev.example\n")
    env = _stripped_env(GIT_CONFIG_GLOBAL=cfg)
    assert git_commit_identity_env(None, env) == {}


def test_injects_fallback_when_unresolvable(tmp_path, monkeypatch):
    """useConfigOnly with no name/email → git var fails → synthetic identity."""
    # Hermetic: probe with ``work_dir=None`` runs git in cwd, so move cwd out of
    # THIS repo (else its repo-local user.name/email would resolve the identity
    # and mask the unresolvable case — the test would false-fail when the suite
    # is launched from the repo root).
    monkeypatch.chdir(tmp_path)
    cfg = _write_global_config(tmp_path, "[user]\n\tuseConfigOnly = true\n")
    env = _stripped_env(GIT_CONFIG_GLOBAL=cfg)
    out = git_commit_identity_env(None, env)
    assert set(out) == set(_IDENT_KEYS)
    assert out["GIT_AUTHOR_NAME"] == _FALLBACK_COMMITTER_NAME
    assert out["GIT_COMMITTER_NAME"] == _FALLBACK_COMMITTER_NAME
    assert out["GIT_AUTHOR_EMAIL"] == _FALLBACK_COMMITTER_EMAIL
    assert out["GIT_COMMITTER_EMAIL"] == _FALLBACK_COMMITTER_EMAIL


def test_fallback_env_enables_commit_in_bare_repo(tmp_path):
    """End-to-end: a repo + identity-less env can commit once the fallback is
    merged in, and the commit is stamped with the synthetic framework author."""
    repo = tmp_path / "repo"
    repo.mkdir()
    unresolvable = _stripped_env(
        GIT_CONFIG_GLOBAL=_write_global_config(
            tmp_path, "[user]\n\tuseConfigOnly = true\n"))

    def git(*args, env):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, env=env, timeout=30)

    assert git("init", env=unresolvable).returncode == 0
    (repo / "f.txt").write_text("x", encoding="utf-8")
    assert git("add", "f.txt", env=unresolvable).returncode == 0

    # Baseline: without the fallback, commit fails for lack of identity.
    bare = git("commit", "-m", "no identity", env=unresolvable)
    assert bare.returncode != 0
    assert "identity" in (bare.stderr + bare.stdout).lower()

    # With the conditional fallback merged in, the commit succeeds.
    ident = git_commit_identity_env(repo, unresolvable)
    assert ident, "fallback identity expected in an unresolvable env"
    commit_env = {**unresolvable, **ident}
    assert git("commit", "-m", "with fallback", env=commit_env).returncode == 0

    author = git("log", "-1", "--pretty=%an <%ae>", env=commit_env)
    assert author.stdout.strip() == \
        f"{_FALLBACK_COMMITTER_NAME} <{_FALLBACK_COMMITTER_EMAIL}>"


def test_probe_honors_repo_local_identity(tmp_path, monkeypatch):
    """work_dir inside a repo with repo-local identity → resolvable → {}
    (repo-local config must not be overridden by the fallback)."""
    # The second probe uses ``work_dir=None`` (cwd), so move cwd out of THIS
    # repo — otherwise this repo's own repo-local identity resolves it and the
    # fallback assertion false-fails when the suite runs from the repo root.
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    unresolvable = _stripped_env(
        GIT_CONFIG_GLOBAL=_write_global_config(
            tmp_path, "[user]\n\tuseConfigOnly = true\n"))
    subprocess.run(["git", "-C", str(repo), "init"],
                   capture_output=True, env=unresolvable, timeout=30)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Local Dev"],
                   capture_output=True, env=unresolvable, timeout=30)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "local@dev.example"],
                   capture_output=True, env=unresolvable, timeout=30)
    # Probing WITH the repo dir sees repo-local identity → no override.
    assert git_commit_identity_env(repo, unresolvable) == {}
    # Probing WITHOUT the repo dir misses repo-local config → fallback.
    assert git_commit_identity_env(None, unresolvable) != {}
