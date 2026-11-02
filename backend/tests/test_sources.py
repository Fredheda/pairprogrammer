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
    (root / "readme.md").write_text("Pairprogrammer docs.\nSee the voice plan.\n")
    return root


@pytest.fixture
def sources(docs: Path) -> Sources:
    return Sources([SourceRoot("docs", docs)], max_bytes=1000)


def assert_refs_in_root(refs: tuple[SourceRef, ...], root: str = "docs") -> None:
    assert refs
    for ref in refs:
        assert ref.root == root
        assert ref.path
        assert ref.cite().startswith(f"{root}:")


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "plans/../../secret.txt",
        "plans/../readme.md",
        "/etc/passwd",
    ],
)
def test_rejects_paths_that_leave_the_root(sources: Sources, path: str) -> None:
    with pytest.raises(SourceError, match="outside"):
        sources.read_file("docs", path)


def test_accepts_absolute_path_inside_the_root(sources: Sources, docs: Path) -> None:
    result = sources.read_file("docs", str(docs / "readme.md"))

    assert "Pairprogrammer docs." in result.text
    assert result.refs[0].path == "readme.md"


def test_rejects_symlink_that_escapes_the_root(
    sources: Sources, docs: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    (docs / "link.txt").symlink_to(secret)
    (docs / "linkdir").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(SourceError, match="outside"):
        sources.read_file("docs", "link.txt")
    with pytest.raises(SourceError, match="outside"):
        sources.read_file("docs", "linkdir/secret.txt")
    listed = sources.list_files("docs").text
    assert "link.txt" not in listed
    assert "linkdir" not in listed
    assert "top secret" not in sources.search_text("docs", "secret").text


def test_unknown_root(sources: Sources) -> None:
    with pytest.raises(SourceError, match="unknown root"):
        sources.read_file("nope", "readme.md")


def test_missing_file(sources: Sources) -> None:
    with pytest.raises(SourceError, match="not found"):
        sources.read_file("docs", "plans/missing.md")


def test_read_file_carries_line_range(sources: Sources) -> None:
    result = sources.read_file("docs", "readme.md")

    assert result.text == "Pairprogrammer docs.\nSee the voice plan.\n"
    assert result.refs == (SourceRef("docs", "readme.md", lines=(1, 2)),)
    assert result.refs[0].cite() == "docs:readme.md#L1-L2"


def test_large_file_is_truncated_with_marker(docs: Path) -> None:
    (docs / "big.md").write_text("".join(f"line {i}\n" for i in range(1, 101)))
    sources = Sources([SourceRoot("docs", docs)], max_bytes=50)

    result = sources.read_file("docs", "big.md")

    assert result.text.startswith("line 1\n")
    assert result.text.endswith("[truncated: showing 50 of 792 bytes]")
    shown_lines = result.text.split("\n[truncated")[0].count("\n") + 1
    assert result.refs[0].lines == (1, shown_lines)


def test_list_files_recurses_and_skips_noise(sources: Sources, docs: Path) -> None:
    (docs / ".git").mkdir()
    (docs / ".git" / "config").write_text("x")
    (docs / "node_modules").mkdir()
    (docs / "node_modules" / "x.js").write_text("x")

    result = sources.list_files("docs")

    assert result.text.splitlines() == ["plans/voice.md", "readme.md"]
    assert_refs_in_root(result.refs)
    assert sources.list_files("docs", "plans").text.splitlines() == ["plans/voice.md"]


def test_search_text_is_case_insensitive_with_line_refs(sources: Sources) -> None:
    result = sources.search_text("docs", "VOICE")

    assert result.text.splitlines() == [
        "plans/voice.md:1: # Voice briefing plan",
        "readme.md:2: See the voice plan.",
    ]
    assert result.refs == (
        SourceRef("docs", "plans/voice.md", lines=(1, 1)),
        SourceRef("docs", "readme.md", lines=(2, 2)),
    )


def test_search_text_without_matches(sources: Sources) -> None:
    result = sources.search_text("docs", "kubernetes")

    assert result.text == "no matches for 'kubernetes'"
    assert result.refs == (SourceRef("docs", "."),)


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


def test_from_env_builds_docs_and_repo_roots(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "repo-a").mkdir()
    (tmp_path / "repo-b").mkdir()

    sources = Sources.from_env(
        {
            "WORKSPACE_DOCS_DIR": str(tmp_path / "docs"),
            "REPO_ROOTS": f"{tmp_path / 'repo-a'},{tmp_path / 'repo-b'}",
            "SOURCE_MAX_BYTES": "1234",
        }
    )

    assert [root.name for root in sources.roots] == ["docs", "repo-a", "repo-b"]
    assert sources.max_bytes == 1234


def test_from_env_without_roots_is_empty() -> None:
    assert Sources.from_env({}).roots == ()
