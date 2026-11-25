"""Small, isolated repositories for Git checkout fixtures."""

import os
from pathlib import Path
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[2]


def git(cwd, *args, data=None):
    cwd = Path(cwd).resolve(strict=True)
    process_env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    process_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.check_output(
        ["git", "-C", str(cwd), "-c", "core.longpaths=true", *args],
        env=process_env,
        input=data,
        stderr=subprocess.STDOUT,
    )


def validate_commit_target(repo, temporary_root):
    temporary_root = Path(temporary_root).resolve(strict=True)
    repo = Path(repo).resolve(strict=True)
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if (
        system_temp not in temporary_root.parents
        or not repo.is_relative_to(temporary_root)
        or repo == temporary_root
        or temporary_root.is_relative_to(PROJECT)
        or any((path / ".git").exists() for path in temporary_root.parents)
    ):
        raise RuntimeError("Commit proibido fora do diretório temporário da fixture")
    dotgit = repo / ".git"
    if not dotgit.is_dir() or dotgit.is_symlink() or dotgit.is_junction():
        raise RuntimeError("A fixture não contém um repositório independente")
    root, common_dir = (
        git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-common-dir",
        )
        .decode("utf-8")
        .splitlines()
    )
    if Path(root).resolve() != repo or Path(common_dir).resolve() != dotgit:
        raise RuntimeError("Git aponta para um repositório fora da fixture")
    if git(repo, "remote").strip():
        raise RuntimeError("A fixture deve ficar sem remotos")


def commit(repo, temporary_root, message):
    validate_commit_target(repo, temporary_root)
    return git(
        repo,
        "-c",
        "user.name=EduDownloader Tests",
        "-c",
        "user.email=tests@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        message,
    )


def new_repository(repo):
    repo.mkdir()
    git(repo, "init", "--quiet", "--template=")
    git(repo, "config", "core.autocrlf", "false")
    # Never run hooks or use an identity from the host configuration.
    hooks = repo / ".git" / "hooks-fixture"
    hooks.mkdir()
    git(repo, "config", "core.hooksPath", str(hooks))


def clone_with_autocrlf(repo, checkout):
    git(
        repo.parent,
        "clone",
        "--quiet",
        "--no-hardlinks",
        "--no-checkout",
        str(repo),
        str(checkout),
    )
    git(checkout, "config", "core.autocrlf", "true")
    git(checkout, "checkout", "--quiet", "HEAD")
