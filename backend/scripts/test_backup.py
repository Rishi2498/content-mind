import sqlite3

conn = sqlite3.connect('backups/contentmind_20261019_000654.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f'Tables in backup: {len(tables)}')
for t in tables:
    print(f'  {t[0]}')