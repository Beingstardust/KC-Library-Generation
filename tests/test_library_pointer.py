import pytest

from kc_l.knowledge_library import load_release
from kc_l.runtime import load_active_library_pointer, resolve_active_release_manifest_path


def test_active_library_pointer_starts_empty():
    pointer = load_active_library_pointer()
    assert pointer.state == "none"
    assert pointer.has_active_release is False


def test_release_resolution_fails_cleanly_without_active_library():
    with pytest.raises(FileNotFoundError, match="No active frozen Knowledge Library release"):
        resolve_active_release_manifest_path()
    with pytest.raises(FileNotFoundError, match="No active frozen Knowledge Library release"):
        load_release()
