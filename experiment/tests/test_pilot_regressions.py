"""Measurement bugs found by the pilot: binary LOC and validation environment."""
from pathlib import Path
import tempfile

from experiment.evaluator.evaluator import compute_repo_diff
from experiment.runner import runtime_environment


def test_binary_artifact_is_recorded_but_not_counted_as_code():
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "old"
        new = Path(tmp) / "new"
        old.mkdir()
        new.mkdir()
        (old / "parser.py").write_text("return value.strip()\n")
        (new / "parser.py").write_text("if value is None: return None\nreturn value.strip()\n")
        (new / "xcrun_db").write_bytes(b"XR1L\x00binary\ncache\n")
        result = compute_repo_diff(old, new)
        assert result["added_files"] == ["xcrun_db"]
        assert result["binary_files"] == ["xcrun_db"]
        assert result["lines_added"] == 1
        assert result["lines_deleted"] == 0


def test_collection_scope_is_environment_configuration_not_task_prompt():
    repo = Path("/private/tmp/example/repo")
    environment = runtime_environment(repo, repo.parent / "runtime")
    assert environment["PYTEST_ADDOPTS"] == "--confcutdir=/private/tmp/example/repo/tests --import-mode=importlib"
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["PWD"] == str(repo)
    assert not any(k.startswith(("HERDR_", "PI_")) for k in environment)
