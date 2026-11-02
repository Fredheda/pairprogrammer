import subprocess
from pathlib import Path

import pytest

from pairprogrammer.sources import SourceError, SourceRef, SourceRoot, Sources

PLAN = """# Voice briefing plan

Intro text.

## Goal

Speak first within 3 s.

```python
# not a heading
```

## Steps

### Step 1: token

Mint an ephemeral token.
"""


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "plans").mkdir(parents=True)
    (root / "plans" / "voice.md").write_text(PLAN)
    (root / "readme.md").write_text("Pairprogrammer docs.\n")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (root / "dist").mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607
    (root / ".gitignore").write_text("dist/\n")
    (root / "src" / "main.py").write_text("print('hi')\n")
    (root / "dist" / "bundle.js").write_text("x\n")
    (root / ".env").write_text("API_KEY=secret\n")
    (root / "src" / ".env.local").write_text("API_KEY=secret\n")
    (root / "certs").mkdir()
    (root / "certs" / "server.pem").write_text("-----BEGIN-----\n")
    return root


@pytest.fixture
def sources(docs: Path, repo: Path) -> Sources:
    return Sources([SourceRoot("docs", docs), SourceRoot("app", repo)])


def read(path: str | Path) -> tuple[str, dict[str, str]]:
    return "Read", {"file_path": str(path)}


def test_duplicate_root_names_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a" / "app").mkdir(parents=True)
    (tmp_path / "b" / "app").mkdir(parents=True)

    with pytest.raises(SourceError, match="duplicate root name: app"):
        Sources(
            [SourceRoot("app", tmp_path / "a" / "app"), SourceRoot("app", tmp_path / "b" / "app")]
        )
    with pytest.raises(SourceError, match="duplicate root name: app"):
        Sources.from_env({"REPO_ROOTS": f"{tmp_path / 'a' / 'app'},{tmp_path / 'b' / 'app'}"})


def test_list_roots_gives_names_and_absolute_paths(
    sources: Sources, docs: Path, repo: Path
) -> None:
    result = sources.list_roots()

    assert result.text.splitlines() == [f"docs: {docs}", f"app: {repo}"]
    assert result.refs == (SourceRef("docs", "."), SourceRef("app", "."))


def test_cwd_is_the_first_root(sources: Sources, docs: Path) -> None:
    assert sources.cwd == docs
    assert Sources([]).cwd is None


@pytest.mark.parametrize("path", ["readme.md", "plans/voice.md"])
def test_allows_reads_inside_a_root(sources: Sources, docs: Path, path: str) -> None:
    assert sources.deny_reason(*read(path)) is None
    assert sources.deny_reason(*read(docs / path)) is None


def test_allows_reads_in_other_roots(sources: Sources, repo: Path) -> None:
    assert sources.deny_reason(*read(repo / "src" / "main.py")) is None


@pytest.mark.parametrize(
    "path", ["../secret.txt", "plans/../../secret.txt", "plans/../readme.md", "/etc/passwd"]
)
def test_denies_paths_that_leave_a_root(sources: Sources, path: str) -> None:
    assert "outside" in (sources.deny_reason(*read(path)) or "")


def test_denies_symlinks_that_escape_a_root(sources: Sources, docs: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("top secret")
    (docs / "link.txt").symlink_to(tmp_path / "secret.txt")
    (docs / "linkdir").symlink_to(tmp_path, target_is_directory=True)

    assert "outside" in (sources.deny_reason(*read(docs / "link.txt")) or "")
    assert "outside" in (sources.deny_reason("Grep", {"path": str(docs / "linkdir")}) or "")


@pytest.mark.parametrize("path", [".env", "src/.env.local", "certs/server.pem"])
def test_denies_secret_files(sources: Sources, repo: Path, path: str) -> None:
    assert "secret" in (sources.deny_reason(*read(repo / path)) or "")


def test_denies_symlink_to_a_secret(sources: Sources, repo: Path) -> None:
    (repo / "notes.txt").symlink_to(repo / ".env")

    assert "secret" in (sources.deny_reason(*read(repo / "notes.txt")) or "")


def test_denies_gitignored_files(sources: Sources, repo: Path) -> None:
    assert "ignored" in (sources.deny_reason(*read(repo / "dist" / "bundle.js")) or "")
    assert "ignored" in (sources.deny_reason("Grep", {"path": str(repo / "dist")}) or "")


def test_grep_and_glob_default_to_the_cwd(sources: Sources) -> None:
    assert sources.deny_reason("Grep", {"pattern": "voice"}) is None
    assert sources.deny_reason("Glob", {"pattern": "**/*.md"}) is None


def test_grep_and_glob_stay_inside_roots(sources: Sources, repo: Path) -> None:
    assert sources.deny_reason("Grep", {"pattern": "x", "path": str(repo / "src")}) is None
    assert "outside" in (sources.deny_reason("Grep", {"pattern": "x", "path": "/etc"}) or "")
    assert "outside" in (sources.deny_reason("Glob", {"pattern": "*", "path": "/"}) or "")


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Glob", {"pattern": "/etc/*"}),
        ("Glob", {"pattern": "../**/*"}),
        ("Grep", {"pattern": "x", "glob": "../*"}),
    ],
)
def test_denies_globs_that_leave_a_root(
    sources: Sources, tool: str, tool_input: dict[str, str]
) -> None:
    assert "outside" in (sources.deny_reason(tool, tool_input) or "")


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Grep", {"pattern": "KEY", "glob": ".env*"}),
        ("Grep", {"pattern": "KEY", "glob": "**/*.pem"}),
        ("Glob", {"pattern": "**/.env"}),
    ],
)
def test_denies_globs_that_target_secrets(
    sources: Sources, tool: str, tool_input: dict[str, str]
) -> None:
    assert "secret" in (sources.deny_reason(tool, tool_input) or "")


def test_denies_other_tools_and_everything_without_roots(docs: Path) -> None:
    assert Sources([SourceRoot("docs", docs)]).deny_reason("Bash", {"command": "ls"})
    assert Sources([]).deny_reason(*read(docs / "readme.md"))


def test_outline_lists_headings_outside_code_fences(sources: Sources) -> None:
    result = sources.outline("docs", "plans/voice.md")

    assert result.text.splitlines() == [
        "L1 # Voice briefing plan",
        "L5 ## Goal",
        "L13 ## Steps",
        "L15 ### Step 1: token",
    ]
    assert result.refs[1] == SourceRef("docs", "plans/voice.md", lines=(5, 5), heading="Goal")
    assert result.refs[1].cite() == "docs:plans/voice.md#L5 (Goal)"


def test_outline_without_headings(sources: Sources) -> None:
    result = sources.outline("docs", "readme.md")

    assert result.text == "no headings"
    assert result.refs == (SourceRef("docs", "readme.md"),)


@pytest.mark.parametrize(
    ("root", "path", "error"),
    [
        ("nope", "readme.md", "unknown root"),
        ("docs", "../secret.md", "outside"),
        ("docs", "missing.md", "not found"),
        ("app", ".env", "secret"),
        ("app", "dist/bundle.js", "ignored"),
    ],
)
def test_outline_refuses_what_the_hook_refuses(
    sources: Sources, root: str, path: str, error: str
) -> None:
    with pytest.raises(SourceError, match=error):
        sources.outline(root, path)


def test_outline_stops_at_the_byte_budget_on_a_whole_line(docs: Path) -> None:
    (docs / "big.md").write_text("".join(f"# Überschrift {i}\n" for i in range(1, 101)))
    sources = Sources([SourceRoot("docs", docs)], max_bytes=50)

    result = sources.outline("docs", "big.md")

    assert result.text.splitlines() == ["L1 # Überschrift 1", "L2 # Überschrift 2"]
    assert "\ufffd" not in result.text


def test_from_env_builds_docs_and_repo_roots(tmp_path: Path) -> None:
    for name in ("docs", "repo-a", "repo-b"):
        (tmp_path / name).mkdir()

    sources = Sources.from_env(
        {
            "WORKSPACE_DOCS_DIR": str(tmp_path / "docs"),
            "REPO_ROOTS": f"{tmp_path / 'repo-a'}, {tmp_path / 'repo-b'}",
        }
    )

    assert [root.name for root in sources.roots] == ["docs", "repo-a", "repo-b"]


def test_from_env_without_roots_is_empty() -> None:
    assert Sources.from_env({}).roots == ()
