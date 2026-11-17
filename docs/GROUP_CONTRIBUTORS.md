# Grouped source contributions (0.4.0 candidate)

A total is easier to audit when the contributing rows and NULL exclusions are visible. This optional mode extends single-table source witnesses to explicit grouped COUNT(*) / COUNT(column) / strict integer SUM(column). It recomputes actual SQLite SQL and independently derives values from the complete captured source set; they must agree.

This is **not arbitrary SQL lineage**, a SQL parser, business correctness, authenticated evidence or an automatic explanation. No joins, views, generated columns, expressions, DISTINCT, HAVING, group pagination, AVG, floating SUM or custom collation are supported. The legacy SQL and 0.3 row/count modes keep their original receipt formats.

## Run a real seven-row example

Python 3.11+, SQLite 3.37+, no runtime package dependencies:

```sh
python examples/make_group_demo.py demo-groups.sqlite
python -m queryproof_groups run --db demo-groups.sqlite --spec examples/group_sales.json --out sales-group-evidence
python -m queryproof_groups verify sales-group-evidence
```

Open the generated report.html or groups.json. Two identical North sales remain separate source rows with distinct locators. North has COUNT(*) 3, COUNT(amount) 2 and SUM 240; its NULL amount is explicitly excluded from the latter two. Lowercase north remains a separate BINARY group even though the column declares NOCASE. Zero is a real amount, not missing. The NULL-region group has count 1, known count 0 and NULL SUM, not zero.

The demo creates only fictional local values. To use your own authorized data, supply an exact table and column specification. The output **contains the entire input database snapshot**, not just selected groups; do not upload private datasets. CSV is supported via `--csv TABLE=PATH`, but all CSV cells remain TEXT and empty strings are not SQL NULL. Thus numeric-looking CSV text cannot be passed to strict integer SUM. Perform an explicitly reviewed type conversion in your own prepared SQLite table first; this tool never silently coerces it.

## Exact semantics

- `group_by`: zero to eight unique column names. Zero means a global aggregate. With empty input a global aggregate emits one group with counts zero and SUM NULL; nonempty group_by emits no groups.
- Keys separate SQLite storage classes (integer 1 and real 1.0 are different groups). This intentionally differs from a bare SQLite GROUP BY that may combine numeric classes. Text is BINARY, NULL keys group together, and real +0/-0 form one normalized key. Original source values remain captured separately.
- Output groups use canonical typed-key serialization order, **not numeric or locale order**. No output page truncates the source contribution set.
- COUNT(*) includes every group source ordinal. COUNT(column) includes every non-NULL value including empty TEXT and BLOB. SUM includes only actual integer values and excludes NULL. Any non-NULL real/text/blob rejects the entire SUM bundle, not just that row.
- Both final signed-64-bit overflow and SQLite intermediate integer overflow reject the bundle. A mathematically representable final sum does not override SQLite execution failure.
- Filters reuse the existing explicit typed no-affinity AND predicates. Every aggregate has a unique `as` label, `op` and explicit `column` (null only for count_all).
- Source ordinals index the complete witnesses array. Each witness contains its snapshot-local rowid or composite WITHOUT ROWID primary key and the full source row. Identical values retain independent locators and contributions. NULL exclusions are recorded per aggregate.
- Source tables must be ordinary, non-generated tables with an unambiguous locator. Key values and counts are not claims of identity in another snapshot.

## Bounds and evidence

At most 10,000 matched rows, 1,000 groups, 16 aggregates, eight keys, 32 AND predicates, 4 MiB complete evidence and the legacy 32 MiB snapshot bound. Limits reject rather than truncate. Each SQLite query phase has a two-second progress budget; this is not an OS wall-clock or native-code sandbox. Large values/groups may hit evidence bounds before the row count bound.

The exact six-file bundle includes snapshot.sqlite, spec.json, queries.json, groups.json, receipt.json and report.html. Queries reveal the actual GROUP BY storage-type and BINARY semantics. The receipt binds bytes and SQLite runtime/source/build options. Offline verify copies only the bundled snapshot, re-introspects, reruns SQL, derives all contributions and byte-compares the generated result and HTML. The source database is not needed. Hashes and complete recomputation establish internal consistency, not authorship or source truth; a coordinated rewrite can forge another consistent bundle.

HTML is an escaped static document with a restrictive CSP, no external requests or scripts. No browser-render, accessibility or new interactive GUI acceptance is claimed. Full rows, blobs, filters and complete snapshots can reveal private information beyond the visible totals. No anonymization or redaction is performed. Never publish an evidence bundle without review.

All output is prepared and verified before reserving a new destination. The newly reserved directory requests owner-only mode 0700 on POSIX. Files are copied using exclusive creation so existing directories/files are not replaced; this avoids Windows directory-replacement behavior. Multi-file publication is **not atomic**: interruption may leave an incomplete output. Use a new destination and verify it before sharing. No existing output is automatically deleted. Hostile parent-directory races, malicious local processes and power-loss durability are outside the guarantee.

Exit 0: creation/recomputation succeeded, including intentionally empty results. Exit 2: invalid/unsupported input, bound, storage, environment or verification failure. Never equate success with business correctness.

## Rebuilt candidate provenance

Built from public 0.3.0 commit b5cba5b9dfb4f5f8696bc0260e73d6c8ce30518e. This is a new implementation, not recovery of the previous unpublished 0.4 RC2. Native old receipts remain version-bound. Platform fixes explicitly close test SQLite handles and split FIFO capability checks from non-FIFO checks; true Windows/macOS and remote CI execution remain unverified until actually run.
