"""Local, bounded SQLite query receipts. Standard library only."""
import argparse
import base64
import csv
from contextlib import closing
import hashlib
import html
import json
import math
import os
import platform
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

VERSION = '0.2.0'
MAX_FILE = 32 * 1024 * 1024
MAX_ROWS = 10000
SAFE_FUNCTIONS = frozenset('like glob abs avg count sum total min max round length lower upper trim ltrim rtrim replace substr substring coalesce ifnull nullif typeof hex quote unicode instr printf format group_concat json json_array json_object json_extract json_valid json_type json_array_length json_quote row_number rank dense_rank lag lead first_value last_value nth_value percent_rank cume_dist ntile'.split())


def encoded(value):
    if isinstance(value, bytes):
        return {'blob_base64': base64.b64encode(value).decode()}
    if isinstance(value, float) and not math.isfinite(value):
        return {'float': str(value)}
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def filehash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def bounded(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError('Input must be a regular file no larger than 32 MiB')
    return path


def qi(name):
    return '"' + name.replace('"', '""') + '"'


def connect(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA trusted_schema=OFF')
    con.execute('PRAGMA query_only=ON')
    con.enable_load_extension(False)
    con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
    con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
    return con


def snapshot(destination, database=None, csvs=()):
    dest = Path(destination)
    if dest.exists():
        raise ValueError('Snapshot destination already exists')
    sources = []
    # Exclusive destination creation prevents accidental replacement.
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(dest)) as out:
            if database:
                source = bounded(database)
                with closing(connect(source)) as inp:
                    deadline = time.monotonic() + 5
                    def progress(status, remaining, total):
                        if time.monotonic() > deadline or total * 65536 > MAX_FILE * 16:
                            raise ValueError('Snapshot backup exceeds safety budget')
                    inp.backup(out, pages=128, progress=progress)
                sources.append({'kind': 'sqlite', 'note': 'Snapshot is a consistent SQLite backup, including committed WAL data.'})
            else:
                for name, filename in csvs:
                    if not name or name.lower().startswith('sqlite_'):
                        raise ValueError('Invalid table name')
                    source = bounded(filename)
                    raw = source.read_bytes()
                    if len(raw) > MAX_FILE:
                        raise ValueError('CSV grew beyond limit')
                    import io
                    rows = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
                    headers = next(rows, None)
                    if not headers or len(headers) > 128 or any(not h for h in headers) or len({h.lower() for h in headers}) != len(headers):
                        raise ValueError('CSV needs 1–128 unique, nonempty headers')
                    out.execute(f'CREATE TABLE {qi(name)} ({", ".join(qi(h) + " TEXT" for h in headers)})')
                    statement = f'INSERT INTO {qi(name)} VALUES ({",".join("?" for _ in headers)})'
                    count = 0
                    for row in rows:
                        if len(row) != len(headers):
                            raise ValueError('Ragged CSV record')
                        count += 1
                        if count > 100000:
                            raise ValueError('CSV exceeds 100000 rows')
                        out.execute(statement, row)
                    sources.append({'kind': 'csv', 'table': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'rows': count, 'semantics': 'All cells TEXT; empty string is not SQL NULL.'})
            out.commit()
        if dest.stat().st_size > MAX_FILE:
            raise ValueError('Snapshot exceeds 32 MiB')
        return sources
    except Exception:
        dest.unlink(missing_ok=True)
        raise


def authorize(action, a, b, database, trigger):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (b or '').lower() in SAFE_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def execute(path, sql, seconds=2):
    if not isinstance(sql, str) or len(sql.encode()) > 65536:
        raise ValueError('SQL exceeds 64 KiB')
    bounded(path)
    with closing(connect(path)) as con:
        con.set_authorizer(authorize)
        deadline = time.monotonic() + seconds
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        cur = con.execute(sql)
        if cur.description is None:
            raise ValueError('A result-producing query is required')
        columns = [c[0] for c in cur.description]
        rows = []
        size = 0
        for row in cur:
            if len(rows) >= MAX_ROWS:
                raise ValueError('Result exceeds 10000 rows; narrow the query explicitly')
            values = [encoded(v) for v in row]
            size += len(canonical(values))
            if size > 4 * 1024 * 1024:
                raise ValueError('Result exceeds 4 MiB')
            rows.append(values)
        return {'columns': columns, 'rows': rows}


def profile(path):
    tables = execute(path, "SELECT name FROM sqlite_schema WHERE type='table' AND substr(name,1,7) != 'sqlite_' ORDER BY name")['rows']
    if len(tables) > 32:
        raise ValueError('Profile limited to 32 tables')
    result = []
    for (name,) in tables:
        # Description safely provides column names without allowing user PRAGMAs.
        columns = execute(path, f'SELECT * FROM {qi(name)} LIMIT 0')['columns']
        if len(columns) > 128:
            raise ValueError('Profile limited to 128 columns per table')
        n = execute(path, f'SELECT count(*) FROM {qi(name)}')['rows'][0][0]
        metrics = []
        for col in columns:
            q = qi(col)
            nulls, empty = execute(path, f'SELECT sum({q} IS NULL), sum(typeof({q})=\'text\' AND {q}=\'\') FROM {qi(name)}')['rows'][0]
            metrics.append({'column': col, 'nulls': nulls or 0, 'empty_text': empty or 0})
        result.append({'table': name, 'rows': n, 'columns': metrics})
    return result


def checkcolumn(path, table, column):
    columns = execute(path, f'SELECT * FROM {qi(table)} LIMIT 0')['columns']
    if column not in columns:
        raise ValueError('Unknown column: ' + column)


def keycheck(path, table, key):
    checkcolumn(path, table, key)
    q, t = qi(key), qi(table)
    row = execute(path, f'SELECT count(*), count({q}), count(DISTINCT {q}) FROM {t}')['rows'][0]
    return {'table': table, 'key': key, 'rows': row[0], 'nulls': row[0]-row[1], 'duplicate_nonnull_rows': row[1]-row[2], 'scope': 'Single key using SQLite DISTINCT semantics; no automatic business-key inference.'}


def joincheck(path, left, lk, right, rk):
    checkcolumn(path, left, lk)
    checkcolumn(path, right, rk)
    l, r = qi(left), qi(right)
    a, b = qi(lk), qi(rk)
    # Explicit binary TEXT equality avoids silently predicting SQLite affinity or collation semantics.
    sql = f'''SELECT coalesce(sum(l.n*r.n),0), coalesce(sum(CASE WHEN l.n>1 AND r.n>1 THEN 1 ELSE 0 END),0) FROM (SELECT CAST({a} AS TEXT) COLLATE BINARY k, count(*) n FROM {l} WHERE {a} IS NOT NULL GROUP BY CAST({a} AS TEXT) COLLATE BINARY) AS l JOIN (SELECT CAST({b} AS TEXT) COLLATE BINARY k, count(*) n FROM {r} WHERE {b} IS NOT NULL GROUP BY CAST({b} AS TEXT) COLLATE BINARY) AS r ON l.k=r.k'''
    pairs, groups = execute(path, sql)['rows'][0]
    return {'left': [left, lk], 'right': [right, rk], 'predicted_inner_rows': pairs, 'many_to_many_keys': groups, 'semantics': 'Explicit CAST(key AS TEXT) COLLATE BINARY equality; NULL excluded. Not a prediction for arbitrary SQL JOINs.'}


def create(database, sql, sources=(), keys=(), joins=(), include_rows=False):
    result = execute(database, sql)
    receipt = {'format': 'queryproof/1', 'version': VERSION, 'sqlite_version': sqlite3.sqlite_version, 'snapshot_sha256': filehash(database), 'sql': sql, 'sources': list(sources), 'result': {'columns': result['columns'], 'row_count': len(result['rows']), 'sha256': digest(result)}, 'profile': profile(database), 'key_checks': [keycheck(database, *k) for k in keys], 'join_checks': [joincheck(database, *j) for j in joins], 'limits': {'rows': MAX_ROWS, 'query_seconds': 2}, 'claim': 'Recomputation evidence, not proof of business correctness or authorship. Ordered result hash; use deterministic ORDER BY.'}
    if include_rows:
        receipt['result']['rows'] = result['rows']
    receipt['environment'] = environment()
    receipt['receipt_sha256'] = digest(receipt)
    return receipt


class VerificationError(ValueError):
    def __init__(self, code, stage, message, remedy, **details):
        super().__init__(message)
        self.diagnostic = {'ok': False, 'code': code, 'stage': stage, 'message': message,
                           'remedy': remedy, 'details': details}


def environment():
    # No hostname, username, absolute paths, environment variables or credentials.
    with closing(sqlite3.connect(':memory:')) as con:
        source_id = con.execute('SELECT sqlite_source_id()').fetchone()[0]
        options = sorted(x[0] for x in con.execute('PRAGMA compile_options'))
    return {'python_version': platform.python_version(), 'python_implementation': platform.python_implementation(),
            'os': platform.system(), 'architecture': platform.machine(), 'sqlite_version': sqlite3.sqlite_version,
            'sqlite_source_id': source_id, 'sqlite_compile_options': options, 'queryproof_version': VERSION}


def verify(database, receipt):
    def fail(code, stage, message, remedy, **details):
        raise VerificationError(code, stage, message, remedy, **details)
    if not isinstance(receipt, dict) or receipt.get('format') != 'queryproof/1':
        fail('RECEIPT_FORMAT', 'receipt', 'Unsupported receipt format', 'Request the original receipt.json generated by QueryProof.')
    if not isinstance(receipt.get('sql'), str) or not receipt['sql'].strip():
        fail('SQL_MISSING', 'receipt', 'Exact SQL is missing; receipt integrity cannot be established', 'Request the complete original bundle. Do not reconstruct SQL from an answer or patch its checksum.')
    body = {k: v for k, v in receipt.items() if k != 'receipt_sha256'}
    if digest(body) != receipt.get('receipt_sha256'):
        fail('RECEIPT_CHECKSUM', 'receipt', 'Receipt checksum mismatch', 'Re-transfer the original receipt. Do not re-sign edited JSON to suppress this warning.')
    if not Path(database).is_file():
        fail('SNAPSHOT_MISSING', 'snapshot', 'Snapshot file is missing', 'Request snapshot.sqlite from the same original bundle; a similarly named current database is not a replacement.')
    # Sidecars mean main-file hashing alone is not sufficient to bind the query input.
    if any(Path(str(database)+suffix).exists() for suffix in ('-wal', '-journal')):
        fail('SNAPSHOT_SIDECAR', 'snapshot', 'Snapshot has a WAL or journal sidecar', 'Stop database writers and request a fresh QueryProof bundle. Do not delete sidecars from a live database.')
    actual = filehash(bounded(database))
    if actual != receipt.get('snapshot_sha256'):
        fail('SNAPSHOT_CHECKSUM', 'snapshot', 'Snapshot checksum mismatch', 'Use the exact snapshot shipped with this receipt. An old, changed or unrelated database cannot be distinguished from a hash mismatch alone.', expected_sha256=receipt.get('snapshot_sha256'), actual_sha256=actual)
    current = environment()
    recorded = receipt.get('environment', {})
    required_environment = set(current)
    if (not isinstance(recorded, dict) or set(recorded) != required_environment
            or any(not isinstance(recorded.get(k), str) or not recorded[k] for k in required_environment - {'sqlite_compile_options'})
            or not isinstance(recorded.get('sqlite_compile_options'), list)
            or any(not isinstance(option, str) for option in recorded['sqlite_compile_options'])
            or recorded.get('sqlite_version') != receipt.get('sqlite_version')
            or recorded.get('queryproof_version') != receipt.get('version')):
        fail('RECEIPT_FORMAT', 'receipt', 'Environment metadata is missing, inconsistent or malformed', 'Request the original generated receipt; do not manually repair it.')
    if receipt.get('sqlite_version') != sqlite3.sqlite_version:
        fail('SQLITE_VERSION', 'environment', 'SQLite runtime differs; reproduce with the recorded version', 'Use an isolated Python environment built with the recorded SQLite version. Changing Python alone does not guarantee that SQLite version. Do not edit the receipt; if unavailable, ask the producer to regenerate and label a new bundle.', expected=receipt.get('sqlite_version'), actual=sqlite3.sqlite_version, recorded_environment=recorded, current_environment=current)
    if recorded and (recorded.get('sqlite_source_id') != current['sqlite_source_id'] or recorded.get('sqlite_compile_options') != current['sqlite_compile_options']):
        fail('SQLITE_BUILD', 'environment', 'SQLite source/build options differ', 'Reproduce in the producer SQLite build or request a separately generated bundle. Matching version strings do not guarantee equivalent builds.', recorded_environment=recorded, current_environment=current)
    if receipt.get('version') != VERSION:
        fail('TOOL_VERSION', 'environment', 'QueryProof version differs', 'Use the recorded QueryProof release in an isolated environment, or request a new bundle. Old receipts are not silently upgraded.', expected=receipt.get('version'), actual=VERSION)
    try:
        rebuilt = create(database, receipt['sql'], receipt['sources'], [(x['table'], x['key']) for x in receipt['key_checks']], [(*x['left'], *x['right']) for x in receipt['join_checks']], 'rows' in receipt['result'])
    except (ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        fail('RECOMPUTE_FAILED', 'recompute', 'Query or diagnostic recomputation failed', 'Confirm the original tool/build and limits. Ask the producer to rerun; query text and database contents are not included in this error.', error_type=type(exc).__name__)
    # Python/OS metadata is informational, not a cross-platform equivalence promise.
    rebuilt['environment'] = recorded
    rebuilt['receipt_sha256'] = digest({k:v for k,v in rebuilt.items() if k != 'receipt_sha256'})
    differences = [key for key in sorted(set(rebuilt) | set(receipt)) if rebuilt.get(key) != receipt.get(key) and key != 'receipt_sha256']
    if differences:
        fail('EVIDENCE_DIFFERS', 'recompute', 'Recomputed evidence differs', 'Inspect ORDER BY tie-breakers, aggregate order and the listed evidence sections. Preserve both bundles; never replace the expected answer merely to pass verification.', sections=differences)
    return True


def diagnose(directory):
    folder = Path(directory)
    try:
        if not (folder/'receipt.json').is_file():
            raise VerificationError('RECEIPT_MISSING', 'receipt', 'receipt.json is missing', 'Request the complete original bundle, not only HTML or query results.')
        receipt = json.loads(bounded(folder/'receipt.json').read_text(encoding='utf-8'))
        verify(folder/'snapshot.sqlite', receipt)
        current = environment()
        recorded = receipt.get('environment', {})
        return {'ok': True, 'code': 'VERIFIED', 'stage': 'complete', 'message': 'Snapshot, query result and diagnostics reproduce; this is not proof of correctness or authorship.', 'environment_notes': [key+' differs (informational)' for key in ('python_version','python_implementation','os','architecture') if recorded.get(key) != current.get(key)]}
    except VerificationError as exc:
        return exc.diagnostic
    except (ValueError, OSError, sqlite3.Error, UnicodeError, KeyError, TypeError) as exc:
        return {'ok': False, 'code': 'INVALID_BUNDLE', 'stage': 'input', 'message': 'Bundle cannot be read or parsed', 'remedy': 'Request the complete original bundle and check file permissions and documented limits.', 'details': {'error_type': type(exc).__name__}}


def report(receipt):
    esc = lambda x: html.escape(str(x))
    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>' + ''.join('<th>'+esc(x)+'</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows) + '</tbody></table></div>'
    result = receipt['result']
    sections = '<section><h2>Exact query</h2><pre>'+esc(receipt['sql'])+'</pre></section>'
    if 'rows' in result:
        sections += '<section><h2>Recorded result</h2>' + table(result['columns'], result['rows']) + '</section>'
    else:
        sections += '<section><h2>Result values omitted</h2><p>The receipt records a result checksum, column names and count. The accompanying snapshot still contains the complete source data.</p></section>'
    sections += '<section><h2>Snapshot profile</h2>'
    for item in receipt['profile']:
        sections += '<h3>'+esc(item['table'])+' · '+esc(item['rows'])+' rows</h3>' + table(['Column','SQL NULL','Empty text'], [[x['column'],x['nulls'],x['empty_text']] for x in item['columns']])
    sections += '</section>'
    sections += '<section><h2>Explicit key and JOIN checks</h2>'
    if not receipt['key_checks'] and not receipt['join_checks']:
        sections += '<p>No key or JOIN checks requested. No claim about duplicates or join safety.</p>'
    for check in receipt['key_checks']:
        sections += '<h3>'+esc(check['table']+'.'+check['key'])+'</h3>' + table(['Rows','NULL keys','Extra duplicate non-NULL rows'],[[check['rows'],check['nulls'],check['duplicate_nonnull_rows']]])
    for check in receipt['join_checks']:
        sections += '<h3>'+esc('.'.join(check['left'])+' → '+'.'.join(check['right']))+'</h3>' + table(['Predicted inner rows','Many-to-many keys'],[[check['predicted_inner_rows'],check['many_to_many_keys']]]) + '<p>'+esc(check['semantics'])+'</p>'
    env = receipt.get('environment', {})
    sections += '</section><section><h2>Producer environment</h2>' + table(['Component', 'Recorded value'], [[key, env.get(key, 'not recorded')] for key in ('queryproof_version', 'python_version', 'python_implementation', 'os', 'architecture', 'sqlite_version', 'sqlite_source_id')]) + '<p>Python and operating-system differences are informational. SQLite version, source build and compile options must match for verification; matching them is not a universal portability guarantee.</p></section><details><summary>Full machine-readable receipt</summary><pre>'+esc(json.dumps(receipt,indent=2,ensure_ascii=False))+'</pre></details>'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>QueryProof receipt</title><style>body{max-width:1080px;margin:2rem auto;background:#101b26;color:#dce9f4;font:16px system-ui;padding:20px}h1{font-size:clamp(30px,5vw,52px);color:#70e1bf;margin-bottom:12px}h2{font-size:22px}h3{font-size:16px;color:#a7c6da}section,details{background:#172b3a;padding:24px;border:1px solid #294356;border-radius:16px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}p{line-height:1.65;color:#b8cad8}.warning{padding:16px;border-left:4px solid #f5b75e;background:#352c20;color:#ffe0b4}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:12px;border-bottom:1px solid #375061;vertical-align:top;max-width:480px;overflow-wrap:anywhere}th{color:#70e1bf}code{color:#70e1bf}summary{cursor:pointer}footer{margin-top:30px;font-size:13px}</style><header><p>LOCAL EVIDENCE / NO MODEL REQUIRED</p><h1>Recompute, don’t just trust.</h1><p>QueryProof · '''+esc(result['row_count'])+''' result rows · SQLite '''+esc(receipt['sqlite_version'])+'''</p></header><p class="warning"><strong>Unverified receipt display.</strong> Run <code>python queryproof.py verify PATH</code> against the full bundle. Reproduction does not prove business correctness, source truth or authorship.</p>'''+sections+'''<footer>PRIVATE: SQL, metadata, optional result rows and the full snapshot can contain sensitive data. Nothing is uploaded by QueryProof.</footer></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('run', help='Create a private local evidence directory (never uploaded)')
    source = make.add_mutually_exclusive_group(required=True)
    source.add_argument('--db')
    source.add_argument('--csv', action='append', metavar='TABLE=PATH')
    make.add_argument('--sql', required=True, help='UTF-8 SQL file')
    make.add_argument('--out', required=True, help='New directory; contains a complete sensitive database snapshot')
    make.add_argument('--key', action='append', nargs=2, default=[], metavar=('TABLE','COLUMN'))
    make.add_argument('--join', action='append', nargs=4, default=[], metavar=('LEFT','KEY','RIGHT','KEY'))
    make.add_argument('--include-rows', action='store_true')
    check = sub.add_parser('verify')
    check.add_argument('directory')
    check.add_argument('--json', action='store_true', help='Machine-readable failure code, stage and remedy; no query/row values')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            folder = Path(args.directory)
            outcome = diagnose(folder)
            if args.json:
                print(json.dumps(outcome, indent=2))
            elif outcome['ok']:
                print('VERIFIED: snapshot, ordered query result and diagnostics reproduce. Not a correctness guarantee.')
                for note in outcome['environment_notes']:
                    print('Environment note: '+note)
            else:
                print(f"QueryProof [{outcome['code']}] at {outcome['stage']}: {outcome['message']}\nNext: {outcome['remedy']}", file=sys.stderr)
            return 0 if outcome['ok'] else 1
        else:
            dest = Path(args.out)
            if dest.exists():
                raise ValueError('Output directory must not exist')
            sql = bounded(args.sql).read_text(encoding='utf-8')
            specs = []
            for spec in args.csv or []:
                if '=' not in spec:
                    raise ValueError('Use --csv TABLE=PATH')
                specs.append(spec.split('=', 1))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.queryproof-', dir=dest.parent) as tmp:
                folder = Path(tmp)
                sources = snapshot(folder/'snapshot.sqlite', args.db, specs)
                receipt = create(folder/'snapshot.sqlite', sql, sources, args.key, args.join, args.include_rows)
                (folder/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
                (folder/'report.html').write_text(report(receipt), encoding='utf-8')
                verify(folder/'snapshot.sqlite', receipt)
                # Destination was checked; rename fails if an existing nonempty directory appears.
                os.rename(folder, dest)
            print(f'Created {dest}. PRIVATE: includes full snapshot and SQL. Review before sharing.')
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError, KeyError, TypeError) as exc:
        print(f'QueryProof: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
