#!/usr/bin/env python3
"""Restore script for ContentMind database.

Restores a SQLite or PostgreSQL database from backup.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_database_info():
    """Get database URL and type from settings."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.config import get_settings
    settings = get_settings()
    return settings.database_url


def restore_sqlite(backup_file: Path, db_path: Path) -> None:
    """Restore SQLite database from backup."""
    import sqlite3
    
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    
    # Close any existing connections by creating new ones
    source = sqlite3.connect(str(backup_file))
    dest = sqlite3.connect(str(db_path))
    source.backup(dest)
    dest.close()
    source.close()


def restore_postgres(backup_file: Path, db_url: str) -> None:
    """Restore PostgreSQL database from backup."""
    import re
    match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', db_url)
    if not match:
        raise ValueError(f"Invalid PostgreSQL URL: {db_url}")
    
    user, password, host, port, dbname = match.groups()
    
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    
    env = os.environ.copy()
    env['PGPASSWORD'] = password
    
    # Drop and recreate database
    drop_cmd = [
        'dropdb',
        '-h', host,
        '-p', port,
        '-U', user,
        '--if-exists',
        dbname,
    ]
    subprocess.run(drop_cmd, env=env, capture_output=True)
    
    create_cmd = [
        'createdb',
        '-h', host,
        '-p', port,
        '-U', user,
        dbname,
    ]
    subprocess.run(create_cmd, env=env, capture_output=True)
    
    # Restore
    restore_cmd = [
        'psql',
        '-h', host,
        '-p', port,
        '-U', user,
        '-d', dbname,
        '-f', str(backup_file),
    ]
    result = subprocess.run(restore_cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"psql restore failed: {result.stderr}")


def restore_uploads(backup_file: Path, uploads_dir: Path) -> None:
    """Restore uploads directory from backup."""
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    
    # Remove existing uploads
    if uploads_dir.exists():
        shutil.rmtree(uploads_dir)
    
    uploads_dir.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(backup_file), str(uploads_dir))


def main():
    parser = argparse.ArgumentParser(description="Restore ContentMind database and uploads")
    parser.add_argument('backup_file', type=Path, help='Path to backup file')
    parser.add_argument('--uploads-backup', type=Path, help='Path to uploads backup (optional)')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()
    
    if not args.backup_file.exists():
        print(f"Backup file not found: {args.backup_file}")
        sys.exit(1)
    
    if not args.force:
        confirm = input(f"This will overwrite the current database. Continue? (y/N): ")
        if confirm.lower() != 'y':
            print("Restore cancelled.")
            sys.exit(0)
    
    db_url = get_database_info()
    
    try:
        if db_url.startswith('sqlite'):
            db_path = Path(db_url.replace('sqlite:///', ''))
            if not db_path.is_absolute():
                db_path = Path(__file__).resolve().parent.parent / db_path
            
            restore_sqlite(args.backup_file, db_path)
            print(f"Database restored from: {args.backup_file}")
        else:
            restore_postgres(args.backup_file, db_url)
            print(f"Database restored from: {args.backup_file}")
        
        # Restore uploads if provided
        if args.uploads_backup:
            uploads_dir = Path(__file__).resolve().parent.parent / 'uploads'
            restore_uploads(args.uploads_backup, uploads_dir)
            print(f"Uploads restored from: {args.uploads_backup}")
        
        print("Restore completed successfully")
    except Exception as e:
        print(f"Restore failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()