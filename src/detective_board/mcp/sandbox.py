"""Path sandbox: a path is usable only if it resolves to a regular file inside an allowed root."""

from __future__ import annotations

import os
from pathlib import Path, PurePath


class SandboxError(Exception):
    """Deliberately vague: the message never echoes paths outside the allowlist."""


def parse_roots(raw: str | None) -> list[Path]:
    """Split an os.pathsep separated list into existing, resolved directories."""
    roots: list[Path] = []
    for part in (raw or "").split(os.pathsep):
        if part.strip():
            p = Path(part).expanduser().resolve()
            if p.is_dir():
                roots.append(p)
    return roots


def resolve_in_allowlist(path: str, roots: list[Path]) -> Path:
    """Return the resolved file path or raise SandboxError.

    Rejected: empty / NUL paths, any `..` component, absolute paths outside every root,
    symlinks (anywhere in the path) whose target leaves the root, non-files.
    """
    if not roots:
        raise SandboxError("no allowed directory configured")
    if not path or "\x00" in path:
        raise SandboxError("path not permitted")
    pp = PurePath(path)
    if ".." in pp.parts:
        raise SandboxError("path not permitted")
    for root in roots:
        cand = Path(path) if pp.is_absolute() else root / pp
        try:
            real = cand.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real.is_relative_to(root) and real.is_file():
            return real
    raise SandboxError("path not permitted")
