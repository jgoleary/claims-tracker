import pytest
from pathlib import Path
from app.storage import LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "pdfs")


def test_save_and_get(storage: LocalFileStorage):
    key = storage.save("sub-123/bill.pdf", b"PDF content here")
    assert key == "sub-123/bill.pdf"
    assert storage.get("sub-123/bill.pdf") == b"PDF content here"


def test_get_missing_raises(storage: LocalFileStorage):
    with pytest.raises(FileNotFoundError):
        storage.get("nonexistent/file.pdf")


def test_delete(storage: LocalFileStorage):
    storage.save("sub-123/bill.pdf", b"data")
    storage.delete("sub-123/bill.pdf")
    with pytest.raises(FileNotFoundError):
        storage.get("sub-123/bill.pdf")


def test_delete_missing_is_noop(storage: LocalFileStorage):
    storage.delete("nonexistent/file.pdf")  # must not raise


def test_save_creates_subdirectories(storage: LocalFileStorage):
    storage.save("a/b/c/file.pdf", b"nested")
    assert storage.get("a/b/c/file.pdf") == b"nested"
