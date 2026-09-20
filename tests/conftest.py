"""Isolate all local state writes away from the repo working tree.

The workbench registry (.data/wizard.db) and other local state live in
cwd-relative paths; without this redirect every pytest run pollutes the
user's Experiments workspace with test campaign rows."""
import os
import tempfile

_data_dir = os.path.join(tempfile.gettempdir(), "bionexus-test-data")
# fresh per session: tests must not see (or feed) earlier runs' rows
import shutil
shutil.rmtree(_data_dir, ignore_errors=True)
os.environ["BIONEXUS_DATA_DIR"] = _data_dir
os.makedirs(os.environ["BIONEXUS_DATA_DIR"], exist_ok=True)
