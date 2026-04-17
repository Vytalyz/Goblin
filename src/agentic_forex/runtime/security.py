from __future__ import annotations

from pathlib import Path


class ProjectIsolationError(RuntimeError):
    pass


class ReadPolicy:
    def __init__(self, *, project_root: Path, allowed_external_roots: list[Path] | None = None) -> None:
        self.project_root = project_root.resolve()
        self.allowed_external_roots = [path.resolve() for path in (allowed_external_roots or [])]

    def assert_allowed(self, candidate: str | Path) -> Path:
        resolved = Path(candidate).resolve()
        if self._is_relative_to(resolved, self.project_root):
            return resolved
        for root in self.allowed_external_roots:
            if self._is_relative_to(resolved, root):
                return resolved
        raise ProjectIsolationError(f"Read blocked outside allowed roots: {resolved}")

    def read_text(self, candidate: str | Path, *, encoding: str = "utf-8") -> str:
        return self.assert_allowed(candidate).read_text(encoding=encoding)

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
