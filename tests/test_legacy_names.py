"""The project used to be called BioNexus. Existing workspaces and shell profiles must keep working."""
import subprocess
import sys

from proef.paths import migrate_legacy_workspace


def test_old_ledger_file_is_renamed_with_its_wal_and_contents_untouched(tmp_path):
    for suffix, body in (("", b"ledger"), ("-wal", b"wal"), ("-shm", b"shm")):
        (tmp_path / f"bionexus.db{suffix}").write_bytes(body)
    assert migrate_legacy_workspace(tmp_path) is True
    assert (tmp_path / "proef.db").read_bytes() == b"ledger"
    assert (tmp_path / "proef.db-wal").read_bytes() == b"wal"
    assert not (tmp_path / "bionexus.db").exists()
    assert migrate_legacy_workspace(tmp_path) is False        # idempotent


def test_never_overwrites_an_existing_new_ledger(tmp_path):
    (tmp_path / "bionexus.db").write_bytes(b"old")
    (tmp_path / "proef.db").write_bytes(b"new")
    assert migrate_legacy_workspace(tmp_path) is False
    assert (tmp_path / "proef.db").read_bytes() == b"new" and (tmp_path / "bionexus.db").exists()


def test_old_environment_variables_still_apply_and_new_ones_win():
    code = ("import os, proef; print(os.environ.get('PROEF_LLM_MODEL'), os.environ.get('PROEF_CAMPAIGN_ID'),"
            " os.environ.get('PROEF_DATA_DIR'))")
    env = {"PATH": "/usr/bin", "BIONEXUS_LLM_MODEL": "legacy-model", "BN_CAMPAIGN_ID": "cmp-1",
           "BIONEXUS_DATA_DIR": "/tmp/old", "PROEF_DATA_DIR": "/tmp/new"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.split()
    assert out == ["legacy-model", "cmp-1", "/tmp/new"]
