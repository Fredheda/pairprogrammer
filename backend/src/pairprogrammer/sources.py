"""Root confinement for the agent's read tools, plus a Markdown outline."""

import os
import re
import shutil
import subprocess  # nosec B404: fixed argv, only `git check-ignore`
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_MAX_BYTES = 1_000_000
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# File names never shown to the model, wherever they sit in a root.
SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".npmrc",
    ".pypirc",
    ".netrc",
)
# Sample names a glob is tried against: a glob matching one targets secrets.
_SECRET_SAMPLES = (".env", ".env.local", "x.pem", "x.key", "x.p12", "id_rsa", ".npmrc")
_GIT = shutil.which("git")


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


def is_secret(name: str) -> bool:
    return any(fnmatch(name, pattern) for pattern in SECRET_PATTERNS)


class Sources:
    def __init__(self, roots: Sequence[SourceRoot], max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.roots = tuple(SourceRoot(r.name, r.path.resolve()) for r in roots)
        self.max_bytes = max_bytes
        self._by_name: dict[str, SourceRoot] = {}
        for root in self.roots:
            if root.name in self._by_name:
                raise SourceError(f"duplicate root name: {root.name}")
            self._by_name[root.name] = root

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Sources":
        roots: list[SourceRoot] = []
        if docs := env.get("WORKSPACE_DOCS_DIR", "").strip():
            roots.append(SourceRoot("docs", Path(docs).expanduser()))
        for repo in env.get("REPO_ROOTS", "").split(","):
            if repo := repo.strip():
                path = Path(repo).expanduser()
                roots.append(SourceRoot(path.resolve().name, path))
        return cls(roots)

    @property
    def cwd(self) -> Path | None:
        """Working directory for the agent; relative tool paths resolve against it."""
        return self.roots[0].path if self.roots else None

    def list_roots(self) -> SourceResult:
        text = "\n".join(f"{r.name}: {r.path}" for r in self.roots) or "no roots configured"
        return SourceResult(text, tuple(SourceRef(r.name, ".") for r in self.roots))

    def deny_reason(self, tool_name: str, tool_input: Mapping[str, Any]) -> str | None:
        """Why a built-in Read/Grep/Glob call must be refused, or None to let it run."""
        if tool_name not in ("Read", "Grep", "Glob"):
            return f"not a source tool: {tool_name}"
        if self.cwd is None:
            return "no source roots configured"
        key = "file_path" if tool_name == "Read" else "path"
        try:
            self._check(str(tool_input.get(key) or self.cwd))
            glob = tool_input.get("pattern" if tool_name == "Glob" else "glob")
            if glob:
                self._check_glob(str(glob))
        except SourceError as error:
            return str(error)
        return None

    def outline(self, root: str, path: str) -> SourceResult:
        source = self._by_name.get(root)
        if source is None:
            raise SourceError(f"unknown root: {root}")
        base, target = self._check(str(source.path / path))
        if base != source.path:
            raise SourceError(f"path is outside the source root: {root}:{path}")
        if not target.is_file():
            raise SourceError(f"not a file: {root}:{path}")
        rel = target.relative_to(base).as_posix()
        lines: list[str] = []
        refs: list[SourceRef] = []
        fence: str | None = None
        for number, line in enumerate(self._lines(target), start=1):
            if run := FENCE.match(line):
                opening = run.group(1)
                if fence is None:
                    fence = opening
                elif opening[0] == fence[0] and len(opening) >= len(fence):
                    fence = None
            elif fence is None and (match := HEADING.match(line)):
                hashes, title = match.groups()
                lines.append(f"L{number} {hashes} {title}")
                refs.append(SourceRef(root, rel, lines=(number, number), heading=title))
        if not lines:
            return SourceResult("no headings", (SourceRef(root, rel),))
        return SourceResult("\n".join(lines), tuple(refs))

    def _check(self, path: str) -> tuple[Path, Path]:
        """Resolve `path` (relative to cwd) and return (root, target) or raise."""
        requested = Path(path)
        if ".." in requested.parts:
            raise SourceError(f"path is outside the source roots: {path}")
        if self.cwd is None:
            raise SourceError("no source roots configured")
        absolute = requested if requested.is_absolute() else self.cwd / requested
        target = absolute.resolve()
        base = next((r.path for r in self.roots if target.is_relative_to(r.path)), None)
        if base is None:
            raise SourceError(f"path is outside the source roots: {path}")
        if not target.exists():
            raise SourceError(f"not found: {path}")
        named = [absolute.name, *target.relative_to(base).parts]
        if ".git" in named:
            raise SourceError(f"git metadata, not readable: {path}")
        if any(is_secret(part) for part in named):
            raise SourceError(f"secret file, not readable: {path}")
        if self._ignored(base, target):
            raise SourceError(f"gitignored, not readable: {path}")
        return base, target

    @staticmethod
    def _check_glob(glob: str) -> None:
        pattern = PurePosixPath(glob)
        if pattern.is_absolute() or ".." in pattern.parts:
            raise SourceError(f"glob is outside the source roots: {glob}")
        last = pattern.name
        if ".git" in pattern.parts:
            raise SourceError(f"glob targets git metadata: {glob}")
        if last not in ("*", "**") and any(fnmatch(s, last) for s in _SECRET_SAMPLES):
            raise SourceError(f"glob targets secret files: {glob}")

    @staticmethod
    def _ignored(base: Path, target: Path) -> bool:
        if target == base:
            return False
        if _GIT is None:
            # can't check ignore rules; fail closed inside a checkout
            return (base / ".git").exists()
        result = subprocess.run(  # noqa: S603  # nosec B603: fixed argv, no shell
            [_GIT, "-C", str(base), "check-ignore", "-q", "--", str(target)],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _lines(self, file: Path) -> Iterator[str]:
        """Whole lines up to `max_bytes` (UTF-8), never a cut-off character."""
        budget = self.max_bytes
        with file.open(encoding="utf-8", errors="replace", newline="") as handle:
            for line in handle:
                budget -= len(line.encode("utf-8"))
                if budget < 0:
                    return
                yield line.rstrip("\r\n")
