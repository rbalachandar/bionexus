"""Isolate all local state writes away from the repo working tree.

The workbench registry (.data/wizard.db), the provenance ledger (proef.db) and other local
state live in cwd-relative paths; without this redirect every pytest run pollutes the user's
workspace with test campaigns and programs (program records go to ./proef.db regardless of
PROEF_DATA_DIR). So the whole session runs from a scratch working directory."""
import os
import tempfile

_data_dir = os.path.join(tempfile.gettempdir(), "proef-test-data")
# fresh per session: tests must not see (or feed) earlier runs' rows
import shutil
shutil.rmtree(_data_dir, ignore_errors=True)
os.environ["PROEF_DATA_DIR"] = _data_dir
os.makedirs(os.environ["PROEF_DATA_DIR"], exist_ok=True)

# cwd-relative state (proef.db, .data/...) must never be the developer's real workspace
_repo = os.getcwd()
import pathlib
REPO = pathlib.Path(__file__).resolve().parents[1]
_scratch = os.path.join(tempfile.gettempdir(), "proef-test-cwd")
shutil.rmtree(_scratch, ignore_errors=True)
os.makedirs(_scratch, exist_ok=True)
os.chdir(_scratch)


import pytest  # noqa: E402


@pytest.fixture
def repo_cwd(monkeypatch):
    """For the few tests that inspect the repository layout itself (skills/, frozen data)."""
    monkeypatch.chdir(REPO)
