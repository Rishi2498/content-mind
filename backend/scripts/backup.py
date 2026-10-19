#!/usr/bin/env python3
"""Backup script for ContentMind database.

Creates a timestamped backup of the SQLite database and media uploads.
For PostgreSQL, uses pg_dump.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_database_info():
    """Get database URL and type from settings."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.config import get_settings
    settings = get_settings()
    return settings.database_url


def backup_sqlite(db_path: Path, backup_dir: Path, timestamp: str) -> Path:
    """Create a backup of SQLite database using .backup command."""
    backup_file = backup_dir / f"contentmind_{timestamp}.db"
    
    import sqlite3
    source = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(backup_file))
    source.backup(dest)
    dest.close()
    source.close()
    
    return backup_file


def backup_postgres(db_url: str, backup_dir: Path, timestamp: str) -> Path:
    """Create a backup of PostgreSQL database using pg_dump."""
    backup_file = backup_dir / f"contentmind_{timestamp}.sql"
    
    # Parse the database URL
    # postgresql://user:pass@host:port/dbname
    import re
    match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', db_url)
    if not match:
        raise ValueError(f"Invalid PostgreSQL URL: {db_url}")
    
    user, password, host, port, dbname = match.groups()
    
    env = os.environ.copy()
    env['PGPASSWORD'] = password
    
    cmd = [
        'pg_dump',
        '-h', host,
        '-p', port,
        '-U', user,
        '-d', dbname,
        '-f', str(backup_file),
        '--no-owner',
        '--no-privileges',
    ]
    
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")
    
    return backup_file


def backup_uploads(uploads_dir: Path, backup_dir: Path, timestamp: str) -> Path:
    """Create a tar.gz archive of the uploads directory."""
    if not uploads_dir.exists():
        print(f"Uploads directory not found: {uploads_dir}")
        return None
    
    backup_file = backup_dir / f"uploads_{timestamp}.tar.gz"
    shutil.make_archive(
        str(backup_file).replace('.tar.gz', ''),
        'gztar',
        str(uploads_dir)
    )
    return backup_file


def main():
    parser = argparse.ArgumentParser(description="Backup ContentMind database and uploads")
    parser.add_argument('--backup-dir', type=Path, default=Path('./backups'),
                        help='Directory to store backups')
    parser.add_argument('--keep', type=int, default=30,
                        help='Number of backups to keep (oldest deleted)')
    args = parser.parse_args()
    
    # Create backup directory
    backup_dir = args.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    db_url = get_database_info()
    
    if db_url.startswith('sqlite'):
        # SQLite backup
        db_path = Path(db_url.replace('sqlite:///', ''))
        if not db_path.is_absolute():
            db_path = Path(__file__).resolve().parent.parent / db_path
        
        if not db_path.exists():
            print(f"Database not found: {db_path}")
            sys.exit(1)
        
        backup_file = backup_sqlite(db_path, backup_dir, timestamp)
        print(f"Database backup created: {backup_file}")
    else:
        # PostgreSQL backup
        backup_file = backup_postgres(db_url, backup_dir, timestamp)
        print(f"Database backup created: {backup_file}")
    
    # Backup uploads
    uploads_dir = Path(__file__).resolve().parent.parent / 'uploads'
    uploads_backup = backup_uploads(uploads_dir, backup_dir, timestamp)
    if uploads_backup:
        print(f"Uploads backup created: {uploads_backup}")
    
    # Clean up old backups
    db_backups = sorted(backup_dir.glob('contentmind_*.db')) + sorted(backup_dir.glob('contentmind_*.sql'))
    upload_backups = sorted(backup_dir.glob('uploads_*.tar.gz'))
    
    for backups in [db_backups, upload_backups]:
        while len(backups) > args.keep:
            old = backups.pop(0)
            old.unlink()
            print(f"Deleted old backup: {old}")
    
    print("Backup completed successfully")


if __name__ == '__main__':
    main()