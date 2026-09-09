import importlib.util
import sqlite3
from pathlib import Path
import pytest


def test_backup_restore_integrity_and_tamper_rejection(tmp_path):
    script=Path(__file__).resolve().parents[2]/'scripts/local-backup.py'
    spec=importlib.util.spec_from_file_location('local_backup',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source';source.mkdir()
    with sqlite3.connect(source/'aibi-v2.db') as conn:
        conn.execute('CREATE TABLE sample (value TEXT)');conn.execute("INSERT INTO sample VALUES ('preserved')")
    (source/'.vault-key').write_bytes(b'test-only-vault-key')
    (source/'sample.csv').write_bytes(b'a,b\n1,2\n')
    backup=tmp_path/'backup';restored=tmp_path/'restored'
    assert module.copy_snapshot(source,backup)==3
    assert module.copy_snapshot(backup,restored,True)==3
    assert (restored/'.vault-key').read_bytes()==(source/'.vault-key').read_bytes()
    with sqlite3.connect(restored/'aibi-v2.db') as conn:assert conn.execute('SELECT value FROM sample').fetchone()[0]=='preserved'
    with pytest.raises(ValueError):module.copy_snapshot(backup,restored,True)
    (backup/'sample.csv').write_bytes(b'tampered')
    with pytest.raises(ValueError):module.copy_snapshot(backup,tmp_path/'bad-restore',True)
    assert not (tmp_path/'bad-restore').exists()
    import json
    manifest=json.loads((backup/'backup-manifest.json').read_text())
    manifest['files']={str((source/'aibi-v2.db').resolve()):module.digest(source/'aibi-v2.db')}
    (backup/'backup-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):module.copy_snapshot(backup,tmp_path/'absolute-restore',True)
    assert not (tmp_path/'absolute-restore').exists()
