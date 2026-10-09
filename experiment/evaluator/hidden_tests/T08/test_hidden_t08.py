"""Hidden evaluation tests for T08 (recordstore).

Verifies deduplication by 'id' across repeated runs and multiple input files.
"""

from pathlib import Path
import pytest
from recordstore.storage import import_records, import_records_file
from recordstore.io import save_records, load_records
import import_data


def test_hidden_repeated_run_no_duplicates(tmp_path: Path):
    """Verify importing same file twice produces no duplicate records."""
    src = tmp_path / "data.json"
    tgt = tmp_path / "store.json"
    save_records(src, [{"id": "x1", "v": 10}, {"id": "x2", "v": 20}])

    # First import
    import_records_file(src, tgt)
    # Second import of same file
    res = import_records_file(src, tgt)
    assert len(res) == 2
    assert [r["id"] for r in res] == ["x1", "x2"]


def test_hidden_mixed_existing_and_new_ids(tmp_path: Path):
    """Verify importing batch with some existing and some new IDs."""
    src1 = tmp_path / "batch1.json"
    src2 = tmp_path / "batch2.json"
    tgt = tmp_path / "store.json"

    save_records(src1, [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}])
    save_records(src2, [{"id": "2", "name": "b_dup"}, {"id": "3", "name": "c"}])

    import_records_file(src1, tgt)
    res = import_records_file(src2, tgt)
    assert len(res) == 3
    assert [r["id"] for r in res] == ["1", "2", "3"]


def test_hidden_multiple_identical_incoming_ids():
    """Verify incoming batch containing duplicate IDs amongst itself."""
    existing = [{"id": "init"}]
    incoming = [{"id": "new1"}, {"id": "new1"}, {"id": "new2"}]
    res = import_records(existing, incoming)
    assert len(res) == 3
    assert [r["id"] for r in res] == ["init", "new1", "new2"]


def test_hidden_disjoint_ids_all_appended():
    """Verify disjoint IDs are all appended correctly."""
    existing = [{"id": "1"}, {"id": "2"}]
    incoming = [{"id": "3"}, {"id": "4"}]
    res = import_records(existing, incoming)
    assert len(res) == 4
    assert [r["id"] for r in res] == ["1", "2", "3", "4"]


def test_hidden_empty_incoming_file(tmp_path: Path):
    """Verify importing an empty incoming file leaves storage untouched."""
    src = tmp_path / "empty.json"
    tgt = tmp_path / "store.json"
    save_records(src, [])
    save_records(tgt, [{"id": "k1"}])

    res = import_records_file(src, tgt)
    assert len(res) == 1
    assert res[0]["id"] == "k1"


def test_hidden_cli_invocation_deduplicates(tmp_path: Path):
    """Verify running import_data CLI script performs deduplication."""
    src = tmp_path / "cli_src.json"
    tgt = tmp_path / "cli_tgt.json"
    save_records(tgt, [{"id": "existing_id", "status": "ok"}])
    save_records(src, [{"id": "existing_id", "status": "new"}, {"id": "other_id", "status": "ok"}])

    ret = import_data.main(["--source", str(src), "--target", str(tgt)])
    assert ret == 0
    loaded = load_records(tgt)
    assert len(loaded) == 2
    assert [r["id"] for r in loaded] == ["existing_id", "other_id"]
