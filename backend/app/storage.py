from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """Persist data under key; returns the key."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve data by key; raises FileNotFoundError if absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove data by key; no-op if absent."""


class LocalFileStorage(Storage):
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self.base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"No file at storage key: {key!r}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self.base_dir / key
        if path.exists():
            path.unlink()


_default_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the process-wide storage instance (lazy init)."""
    global _default_storage
    if _default_storage is None:
        from pathlib import Path as _Path
        _default_storage = LocalFileStorage(
            _Path(__file__).parent.parent.parent / "data" / "pdfs"
        )
    return _default_storage
