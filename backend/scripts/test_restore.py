import sqlite3
import shutil
from pathlib import Path

# Copy the backup to a test database
backup_file = Path('backups/contentmind_20261019_000654.db')
test_db = Path('test_restore.db')

# Remove test db if exists
if test_db.exists():
    test_db.unlink()

shutil.copy2(backup_file, test_db)

# Verify the restored database
conn = sqlite3.connect(test_db)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f'Tables in restored: {len(tables)}')
for t in tables:
    print(f'  {t[0]}')

# Verify data integrity
cursor.execute("SELECT COUNT(*) FROM user")
print(f'User count: {cursor.fetchone()[0]}')

cursor.execute("SELECT COUNT(*) FROM content")
print(f'Content count: {cursor.fetchone()[0]}')

cursor.execute("SELECT version_num FROM alembic_version")
print(f'Alembic version: {cursor.fetchone()[0]}')

print('Restore test passed!')