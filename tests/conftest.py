"""Isolate all local state writes away from the repo working tree.

The workbench registry (.data/wizard.db) and other local state live in
cwd-relative paths; without this redirect every pytest run pollutes the
user's Experiments workspace with test campaign rows."""
import os
import tempfile

os.environ["BIONEXUS_DATA_DIR"] = os.path.join(
    tempfile.gettempdir(), "bionexus-test-data")
os.makedirs(os.environ["BIONEXUS_DATA_DIR"], exist_ok=True)
