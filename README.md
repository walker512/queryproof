# QueryProof

**An answer is easier to trust when somebody else can rerun it.**

Turn a CSV or SQLite query into a local evidence bundle: a consistent database snapshot, exact SQL, ordered result hash, data-quality counters and an offline HTML report. Verify the whole bundle later without an AI model, API key, server or network connection.

QueryProof proves only that the recorded computation reproduces on the recorded snapshot and SQLite runtime. It does **not** prove the query answers the intended question, that the data is true, or who authored the evidence. Checksums are not digital signatures.

## First result in a minute

Python **3.11+**, standard library only. Clone/download this repository; no dependency installation required.

```sh
python queryproof.py run --csv sales=examples/sales.csv --csv labels=examples/labels.csv --sql examples/inflated.sql --key sales customer --join sales customer labels customer --include-rows --out demo-evidence
python queryproof.py verify demo-evidence
```

Open `demo-evidence/report.html` in a browser. This fictional example has three sales totalling **60**, but an incorrect join reports **90** because customer `a` has two sales and two labels. The explicit join check predicts five output rows and one many-to-many key. Verification **passes for the incorrect answer**: this deliberately shows why reproducibility is not correctness.

Compare the corrected query:

```sh
python queryproof.py run --csv sales=examples/sales.csv --csv labels=examples/labels.csv --sql examples/correct.sql --include-rows --out corrected-evidence
```

For existing SQLite:

```sh
python queryproof.py run --db analytics.sqlite --sql question.sql --out evidence
python queryproof.py verify evidence
```

`--out` must be a new directory. Errors return exit code 1, successful creation/verification return 0. Failed runs do not publish a partial output directory. `--key TABLE COLUMN` and `--join LEFT KEY RIGHT KEY` are repeatable. No shell commands or SQL are executed from filenames. `--sql` takes a UTF-8 file, not inline SQL.

## What is inside?

| File | Purpose |
| --- | --- |
| `snapshot.sqlite` | Consistent backup or imported CSVs; complete data, not a sample |
| `receipt.json` | SQL, runtime version, SHA-256 checksums, result column names/count, profile and explicit checks |
| `report.html` | Offline, escaped display of the receipt; no scripts, external assets or network calls |

**The bundle is sensitive.** Snapshot contains **all original tables**, not only query output. SQL literals, column names and statistics may also disclose information. Result rows are omitted from JSON/HTML unless `--include-rows`, but **this does not redact the snapshot**. Nothing is uploaded. Review or regenerate a deliberately reduced source dataset before sharing. Do not commit private bundles. Unix output directories are owner-only; on Windows use your OS account/file permissions. Files are not encrypted or securely erased.

A hash-only receipt can be shared separately if its metadata is appropriate, but verification still needs the exact snapshot. Do not trust the report's appearance: run `verify`. Verification rechecks the receipt checksum, exact snapshot bytes, SQLite version, ordered query result and every diagnostic. Re-signing the JSON after changing a result does not bypass recomputation. Someone who changes both the dataset and receipt can produce another valid bundle: use your own trusted hash or external signing channel if provenance matters.

## Deliberate semantics

- CSV uses UTF-8 (BOM accepted), comma delimiters and strict CSV parsing. All fields are **TEXT**, including `001`, `NULL` and numeric-looking values. Empty string is **not** SQL NULL. Use explicit casts with care: SQLite may coerce invalid numeric text to zero. QueryProof does not infer types or clean data. Quoted multiline fields are supported; ragged records and duplicate/empty headers rejected.
- SQLite snapshots include committed WAL data through SQLite's backup API. Original database is opened read-only; QueryProof never runs write queries against it. The saved snapshot's hash is the backup's hash, not necessarily the original file's byte hash.
- Profiles cover ordinary user tables, not views: row counts, SQL NULL counts, and empty TEXT counts per column.
- `--key` reports duplicate **non-NULL** rows beyond distinct values for one explicitly named column using SQLite DISTINCT/collation semantics. It does not discover business keys or composite uniqueness.
- `--join` explicitly compares `CAST(key AS TEXT) COLLATE BINARY`, excludes NULL and predicts an inner join's row count from group counts, without materializing the join. It flags matching keys duplicated on **both** sides. It does not inspect the submitted SQL, normalize names, infer relationships or cover arbitrary join predicates. These explicit semantics can differ from your query's numeric affinity/collation.
- Result hashes preserve column order, row order and SQLite values. BLOBs use tagged Base64; nonfinite floats use tagged strings. Always write a deterministic `ORDER BY` with a unique tie-breaker for row-producing queries. `group_concat` and floating-point aggregates may also depend on evaluation order. Runtime version mismatch fails closed. No cross-version bit-for-bit promise.
- Query functions use a conservative allowlist. Randomness, clock functions, extension loading, user PRAGMAs, ATTACH and writes are denied. CTEs, window functions and common JSON/scalar/aggregate functions are supported. This is not every SQLite function.

## Bounds and security

32 MiB input/snapshot, 100,000 CSV rows per table, 128 columns, 32 profiled tables, 10,000 result rows, 4 MiB result payload, 64 KiB SQL. Oversize results fail rather than silently truncate. SQL execution has a two-second SQLite VM progress deadline per query, not a hard OS process/memory sandbox. SQLite scalar functions may run between progress checks. Individual SQL values are capped at 1 MiB; SQLite may return NULL rather than error for oversized function results. Backup has a five-second progress deadline. Very wide/many-table profiles may take longer overall. Python/SQLite must be kept patched. Other local processes, compromised runtimes, malicious native SQLite exploits and simultaneous filesystem modifications are outside the threat model. Use a disposable OS sandbox for hostile database files.

No server or telemetry, no remote models, no credentials, no automatic downloads. SQL authorization is an allowlist, not a regular-expression filter. HTML uses escaped text and a restrictive content-security policy. The CLI verifier never follows paths embedded in a receipt; it only opens the explicitly selected directory's fixed filenames. Evidence is a local audit aid, not an access-control boundary.

## Why not Datasette / Join Key Lab?

Datasette is a much more mature data exploration/publishing platform with APIs and a plugin ecosystem. Its Agent already shows SQL and supports local models. QueryProof intentionally does not rebuild that experience. Its narrow workflow is **portable offline evidence with full diagnostic recomputation**. [Comparison and sources](COMPARISON.md).

The author's Join Key Lab explores how normalization changes CSV joins. QueryProof does not reproduce those normalization experiments; its limited explicit join check is context attached to a query receipt.

## Development

```sh
python -m unittest discover -s tests -v
python -m compileall -q queryproof.py
```

Tests cover real CSV/SQLite round trips, committed WAL snapshots, tampering, hostile SQL, time/size/row limits, unknown columns, BLOBs, HTML injection and CLI failure/permission behavior. The 36-test hosted matrix passed on Python 3.11–3.13 on Linux and Python 3.12 on Windows. [Validation records the exact tested commit, run and remaining limits](VALIDATION.md).

MIT. Original implementation. No promise of growth, universal competitor superiority or automatic data correctness.

## When a handoff fails (0.2.0)

```sh
python queryproof.py verify evidence --json
```

Produces a stable `code`, first failed `stage`, diagnosis and `remedy`, with exit 1 on failure. It does not silently repair or modify a receipt. Error output omits SQL/row values; environment diagnostics include recorded/current build metadata.

- `RECEIPT_MISSING` / `SQL_MISSING`: request the original complete bundle. HTML or an answer alone cannot recover the precise query.
- `RECEIPT_CHECKSUM`: receipt was changed or damaged. Re-transfer it; do not re-sign it to silence the warning.
- `SNAPSHOT_CHECKSUM`: different database bytes, whether stale, edited or unrelated. The hash alone cannot tell which. Request the exact snapshot, not the latest database.
- `SNAPSHOT_SIDECAR`: WAL/journal present. Request a newly generated standalone bundle; never delete a live database's sidecars.
- `SQLITE_VERSION` / `SQLITE_BUILD`: inspect recorded/current versions, SQLite source ID and compile options. Use an isolated matching build or ask for a separately regenerated bundle. Installing a particular Python version alone does not ensure a particular SQLite build.
- `TOOL_VERSION`: use the recorded QueryProof release. Old receipts are not silently upgraded.
- `RECOMPUTE_FAILED` / `EVIDENCE_DIFFERS`: examine recorded limits, deterministic ordering and reported differing sections. Preserve the evidence; replacing expected values just to pass defeats verification.

The receipt also records Python version/implementation, OS and architecture, but no hostname, username, paths or environment variables. Python/OS differences are informational and noted after a successful verification; SQLite version/source/build differences fail closed. These metadata help locate mismatches, **not guarantee cross-platform or cross-version behavior**. First failure does not mean all later checks passed.

[Same-data handoff exercise](COMPARISON.md#handoff-fault-exercise-020) compares actual outcomes with a disclosed Datasette export/manual-review recipe, including a stronger manual checksum control that closes the snapshot-identity gap.

## Optional single-table source witnesses (distribution 0.3.0)

[Source witnesses](docs/SOURCE_WITNESSES.md) link a bounded typed projection or COUNT(*) to exact snapshot-local row locators and full source values. Duplicate projected rows stay distinct; paged results report omitted matching rows, while COUNT requires the complete bounded source set. It uses explicit structured specs, not arbitrary SQL parsing, and rejects unsupported table/query forms. Try `python -m queryproof_witness run --csv sales=examples/sales.csv --spec examples/witness_rows.json --out private-witness`, then `python -m queryproof_witness verify private-witness`.

The old `queryproof.py`, its 0.2.0 receipts and all 36 original tests are unchanged. The new installed entry point is `queryproof-witness`; it does not inherit old hosted-CI/browser acceptance merely by sharing this repository. Both modes include a complete sensitive database snapshot and perform no upload.

Witness increment validation: **67 local tests passed, zero skips** (36 original + 31 new), plus offline wheel installation and both installed commands exercised outside the source checkout. See [the separate validation scope](docs/SOURCE_WITNESSES.md#executed-verification-for-this-increment); old hosted/browser acceptance does not imply new-mode acceptance.
