"""Stopped-service backup/restore into a NEW directory. Never overwrite data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_snapshot(source,destination,restore=False):
    source=Path(source).resolve(); destination=Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Destination must be a new directory outside the source')
    if not source.is_dir():raise ValueError('Source directory does not exist')
    manifest=json.loads((source/'backup-manifest.json').read_text(encoding='utf-8')) if restore else None
    if restore and (manifest.get('version')!=1 or 'aibi-v2.db' not in manifest.get('files',{})):
        raise ValueError('Unsupported or incomplete backup manifest')
    entries=manifest['files'] if manifest else {
        str(p.relative_to(source).as_posix()):digest(p) for p in source.rglob('*')
        if p.is_file() and not p.is_symlink() and p.relative_to(source).parts[0] not in {'acceptance','backups'}
        and p.name not in {'backup-manifest.json','aibi-v2.db-wal','aibi-v2.db-shm'}}
    for name,expected in entries.items():
        if Path(name).is_absolute() or '..' in Path(name).parts or not (destination/name).resolve().is_relative_to(destination):
            raise ValueError('Snapshot entries must be relative paths inside the destination')
        path=(source/name).resolve()
        if not path.is_relative_to(source) or path.is_symlink() or not path.is_file() or digest(path)!=expected:
            raise ValueError('Invalid snapshot path or checksum')
    database=source/'aibi-v2.db'
    with sqlite3.connect(f'file:{database.as_posix()}?mode=ro',uri=True) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity failed')
    if (source/'aibi-v2.db-wal').exists() and (source/'aibi-v2.db-wal').stat().st_size:
        raise ValueError('Uncheckpointed WAL exists; stop service and checkpoint before copying')
    destination.mkdir(parents=True)
    for name in entries:
        target=destination/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,target)
        if digest(target)!=entries[name]:raise ValueError('Copy verification failed; incomplete destination retained')
    if not restore:
        (destination/'backup-manifest.json').write_text(json.dumps({'version':1,'files':entries},indent=2),encoding='utf-8')
    return len(entries)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['backup','restore']);parser.add_argument('source');parser.add_argument('destination')
    parser.add_argument('--confirm-stopped',action='store_true',required=True,help='Confirm API and other data writers are stopped')
    args=parser.parse_args()
    print(f'Verified {copy_snapshot(args.source,args.destination,args.operation=="restore")} files. Snapshot contains sensitive data; keep private.')
