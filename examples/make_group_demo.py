"""Create fictional local sales data. Refuses an existing file. No API required."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument('database')
args = parser.parse_args()
path = Path(args.database)
if path.exists() or path.is_symlink():
    raise SystemExit('Use a new database path; existing data is never replaced.')
# Reserve rather than silently opening an existing user's database.
with path.open('xb'):
    pass
with closing(sqlite3.connect(path)) as db, db:
    db.execute('CREATE TABLE sales(region TEXT COLLATE NOCASE,amount INTEGER,note TEXT)')
    db.executemany('INSERT INTO sales VALUES(?,?,?)', [
        ('North', 120, 'fictional'), ('North', 120, 'fictional'),
        ('North', None, 'missing'), ('north', -20, 'refund'),
        ('South', 0, ''), ('South', 75, 'fictional'), (None, None, 'unknown')])
print('Created fictional seven-row sales fixture. No real customer data.')
