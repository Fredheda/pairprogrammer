"""Read-only, root-confined access to workspace docs and local repo checkouts."""

import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_BYTES = 200_000
DEFAULT_MAX_MATCHES = 50
SKIPPED_DIRS = frozenset({".git", ".next", ".venv", "__pycache__", "node_modules"})
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


class SourceError(Exception):
    """A request the source tools refuse or cannot answer."""


@dataclass(frozen=True)
class SourceRoot:
    name: str
    path: Path


@dataclass(frozen=True)
class SourceRef:
    root: str
    path: str
    lines: tuple[int, int] | None = None
    heading: str | None = None

    def cite(self) -> str:
        ref = f"{self.root}:{self.path}"
        if self.lines:
            first, last = self.lines
            ref += f"#L{first}" if first == last else f"#L{first}-L{last}"
        if self.heading:
            ref += f" ({self.heading})"
        return ref


@dataclass(frozen=True)
class SourceResult:
    text: str
    refs: tuple[SourceRef, ...]


class Sources:
    def __init__(
        self,
        roots: Sequence[SourceRoot],
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_matches: int = DEFAULT_MAX_MATCHES,
    ) -> None:
        self.roots = tuple(SourceRoot(r.name, r.path.resolve()) for r in roots)
        self.max_bytes = max_bytes
        self.max_matches = max_matches
        self._by_name = {r.name: r for r in self.roots}

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Sources":
        roots: list[SourceRoot] = []
        if docs := env.get("WORKSPACE_DOCS_DIR", "").strip():
            roots.append(SourceRoot("docs", Path(docs).expanduser()))
        for repo in env.get("REPO_ROOTS", "").split(","):
            if repo := repo.strip():
                path = Path(repo).expanduser()
                roots.append(SourceRoot(path.resolve().name, path))
        max_bytes = int(env.get("SOURCE_MAX_BYTES") or DEFAULT_MAX_BYTES)
        return cls(roots, max_bytes=max_bytes)

    def list_roots(self) -> SourceResult:
        text = "\n".join(r.name for r in self.roots) or "no roots configured"
        return SourceResult(text, tuple(SourceRef(r.name, ".") for r in self.roots))

    def list_files(self, root: str, path: str = ".") -> SourceResult:
        base, start = self._resolve(root, path)
        if not start.is_dir():
            raise SourceError(f"not a directory: {root}:{path}")
        files = [self._rel(base, f) for f in self._walk(base, start)]
        here = SourceRef(root, self._rel(base, start))
        return SourceResult("\n".join(files) or "no files", (here,))

    def read_file(self, root: str, path: str) -> SourceResult:
        base, target = self._resolve(root, path)
        if not target.is_file():
            raise SourceError(f"not a file: {root}:{path}")
        text, total = self._read(target)
        shown = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        if total > self.max_bytes:
            text += f"\n[truncated: showing {self.max_bytes} of {total} bytes]"
        ref = SourceRef(root, self._rel(base, target), lines=(1, max(shown, 1)))
        return SourceResult(text, (ref,))

    def search_text(self, root: str, query: str, path: str = ".") -> SourceResult:
        if not query.strip():
            raise SourceError("query must not be empty")
        base, start = self._resolve(root, path)
        files = [start] if start.is_file() else self._walk(base, start)
        needle = query.lower()
        hits: list[str] = []
        refs: list[SourceRef] = []
        for file in files:
            text, _ = self._read(file)
            if "\x00" in text:
                continue
            rel = self._rel(base, file)
            for number, line in enumerate(text.splitlines(), start=1):
                if needle in line.lower():
                    if len(hits) == self.max_matches:
                        hits.append(f"[truncated: first {self.max_matches} matches]")
                        return SourceResult("\n".join(hits), tuple(refs))
                    hits.append(f"{rel}:{number}: {line.strip()}")
                    refs.append(SourceRef(root, rel, lines=(number, number)))
        if not hits:
            here = SourceRef(root, self._rel(base, start))
            return SourceResult(f"no matches for {query!r}", (here,))
        return SourceResult("\n".join(hits), tuple(refs))

    def outline(self, root: str, path: str) -> SourceResult:
        base, target = self._resolve(root, path)
        if not target.is_file():
            raise SourceError(f"not a file: {root}:{path}")
        text, _ = self._read(target)
        rel = self._rel(base, target)
        lines: list[str] = []
        refs: list[SourceRef] = []
        in_fence = False
        for number, line in enumerate(text.splitlines(), start=1):
            if FENCE.match(line):
                in_fence = not in_fence
            elif not in_fence and (match := HEADING.match(line)):
                hashes, title = match.groups()
                lines.append(f"L{number} {hashes} {title}")
                refs.append(SourceRef(root, rel, lines=(number, number), heading=title))
        if not lines:
            return SourceResult("no headings", (SourceRef(root, rel),))
        return SourceResult("\n".join(lines), tuple(refs))

    def _resolve(self, root: str, path: str) -> tuple[Path, Path]:
        source = self._by_name.get(root)
        if source is None:
            raise SourceError(f"unknown root: {root}")
        requested = Path(path)
        if ".." in requested.parts:
            raise SourceError(f"path is outside root {root}: {path}")
        target = (source.path / requested).resolve()
        if not target.is_relative_to(source.path):
            raise SourceError(f"path is outside root {root}: {path}")
        if not target.exists():
            raise SourceError(f"not found: {root}:{path}")
        return source.path, target

    def _walk(self, base: Path, start: Path) -> list[Path]:
        return sorted(self._iter_files(base, start), key=lambda f: self._rel(base, f))

    def _iter_files(self, base: Path, start: Path) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in SKIPPED_DIRS and self._inside(base, Path(dirpath, d))
            ]
            for name in sorted(filenames):
                file = Path(dirpath, name)
                if self._inside(base, file) and file.is_file():
                    yield file

    def _read(self, file: Path) -> tuple[str, int]:
        total = file.stat().st_size
        with file.open("rb") as handle:
            data = handle.read(self.max_bytes)
        return data.decode("utf-8", errors="replace"), total

    @staticmethod
    def _inside(base: Path, path: Path) -> bool:
        return path.resolve().is_relative_to(base)

    @staticmethod
    def _rel(base: Path, path: Path) -> str:
        return path.resolve().relative_to(base).as_posix()
