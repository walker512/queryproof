# QueryProof

**Hand over a query result that someone else can recompute offline.**

QueryProof turns CSV files or a SQLite database into a local evidence bundle:
a consistent snapshot, the computation, diagnostics and an HTML report.
It runs without a model, API key, server or runtime dependencies.

**Reproducible does not mean correct.** A valid bundle can reproduce a wrong query.
Verification does not establish source truth, business meaning or authorship.
Checksums are not signatures.

## Start with a real example

Use Python **3.11+**. Clone/download this repository and run from its directory;
no installation is needed. Optional installation: `python -m pip install .`
(building requires setuptools; the runtime uses only the standard library).

```sh
python queryproof.py run --csv sales=examples/sales.csv --csv labels=examples/labels.csv --sql examples/inflated.sql --key sales customer --join sales customer labels customer --include-rows --out demo-evidence
python -m queryproof_check demo-evidence --strict-display --json
```

Open `demo-evidence/report.html` after checking it. The fictional sales total is
**60**, but the incorrect join returns **90**. The explicit join diagnostic predicts
five joined rows and one many-to-many key. Verification passes because the recorded
calculation reproduces, not because 90 is the right business answer.

Run the corrected query into a different directory:

```sh
python queryproof.py run --csv sales=examples/sales.csv --csv labels=examples/labels.csv --sql examples/correct.sql --include-rows --out corrected-evidence
python -m queryproof_check corrected-evidence --strict-display --json
```

For your own SQLite data:

```sh
python queryproof.py run --db analytics.sqlite --sql question.sql --out evidence
python -m queryproof_check evidence --strict-display --json
```

`--sql` takes a UTF-8 file, not inline SQL. Every output destination must be new.
Creation/check success returns 0; errors return 1. Nothing is uploaded.

## Choose the evidence you need

| Mode | What it records | Deliberate boundary |
| --- | --- | --- |
| `queryproof` | Read-only SQL result hash, profiles, explicit key/join checks | Does not derive row lineage from arbitrary SQL |
| `queryproof-witness` | Typed single-table projection or COUNT(*) with snapshot-local row locators and full source values | Structured spec, not arbitrary joins; paged rows disclose omitted matches; COUNT requires the complete bounded contributor set |
| `queryproof-groups` | Grouped COUNT(*), COUNT(column), strict integer SUM with all contributing rows and NULL exclusions | Bounded single-table grouping, not general SQL lineage |

These are also available as `python -m queryproof`, `python -m queryproof_witness`
and `python -m queryproof_groups` from the checkout.

```sh
python -m queryproof_witness run --csv sales=examples/sales.csv --spec examples/witness_rows.json --out private-witness
python -m queryproof_check private-witness --json

python examples/make_group_demo.py demo-groups.sqlite
python -m queryproof_groups run --db demo-groups.sqlite --spec examples/group_sales.json --out sales-group-evidence
python -m queryproof_check sales-group-evidence --json
```

Read the exact supported specs and bounds:
[source witnesses](docs/SOURCE_WITNESSES.md),
[grouped contributors](docs/GROUP_CONTRIBUTORS.md).
CSV cells remain TEXT; strict integer SUM needs a prepared SQLite integer column.

## Verify a received bundle

```sh
python -m queryproof_check path/to/evidence --strict-display --json
```

The unified checker accepts three fixed receipt formats and dispatches to their
full offline recomputation. Unknown/mixed/incomplete layouts, symlink members and
malformed receipts fail closed. JSON status omits private SQL, rows and raw errors.
The checker does not repair, upgrade or delete evidence.

- **Default legacy query check is data-only.** It does not check `report.html`.
- **`--strict-display`** additionally rebuilds typed legacy evidence and requires
  exact HTML bytes from the shipped 0.2.0 renderer. Unknown renderer versions fail;
  harmless formatting edits can also fail. No HTML is executed.
- Witness/group verification already checks their regenerated HTML.
- Use the matching recorded tool and SQLite version/source/build. Python version
  alone does not determine SQLite compatibility. Other recorded platform metadata
  is informational, not authenticated.

For legacy diagnosis, `python queryproof.py verify evidence --json` returns a
failure stage and remedy. Keep originals when a check fails; request the exact
snapshot or matching runtime rather than changing expected values to pass.
[Strict display details](docs/STRICT_DISPLAY.md).

## Privacy and safe handling

A legacy bundle contains `snapshot.sqlite`, `receipt.json` and `report.html`;
witness/group formats add their structured evidence. **The snapshot includes all
original tables, not just selected results.** SQL, names, source values and statistics
can reveal private information. Omitting `--include-rows` does not redact the database.
Use a deliberately reduced source dataset before sharing. Do not commit private bundles.

New Unix directories request 0700 and files 0600 at creation, with exclusive creation
rather than overwriting existing destinations. Existing artifacts are not chmodded.
Windows ACL isolation is not guaranteed. Files are not encrypted or securely erased.
Multi-file publication is **not atomic**: interruption can leave an incomplete private
directory. Verify before use and retry into a new destination. Trusted, stable parent
directories are required; hostile same-account modifications and power-loss durability
are outside the guarantee.

## Semantics and limits that matter

- UTF-8 CSV (BOM accepted), strict comma-separated records, quoted multiline fields;
  empty/duplicate headers and ragged rows fail. Every cell is TEXT, including `001`
  and `NULL`; empty string is not SQL NULL. Explicit casts can coerce invalid text.
- SQLite backup includes committed WAL data without writing to the source. Its hash
  identifies the snapshot bytes, not necessarily the original database file bytes.
- Profiles cover ordinary tables. `--key` checks duplicate non-NULL values for one
  named column; it does not discover business keys. `--join` compares BINARY text
  casts, excludes NULL and predicts an inner join. It does not inspect your SQL and
  may differ from its affinity/collation semantics.
- Ordered result hashes require deterministic SQL. Use `ORDER BY` with a unique
  tie-breaker; aggregate evaluation order and SQLite builds can still matter.
- The SQL mode bounds inputs/snapshot at 32 MiB, SQL at 64 KiB, results at 10,000 rows
  and 4 MiB, CSV rows at 100,000 per table, columns at 128 and profiled tables at 32.
  Oversize output is rejected, not silently truncated. Witness/group limits are
  specified in their linked guides.
- Write queries, ATTACH, user PRAGMAs, extension loading, clock/random functions and
  unsupported functions are denied through SQLite authorization. Per-query VM
  progress deadlines and backup deadlines are **not an OS memory/process sandbox**;
  native scalar work can run between checks. Keep Python/SQLite patched and isolate
  hostile database files. Other processes can change evidence after checking it.

## Why use this alongside existing tools?

Datasette offers richer exploration, publishing, APIs and plugins. Join Key Lab offers
normalization and join-contract workflows. QueryProof focuses on a packaged, offline
handoff with reproducible diagnostics and explicit failure guidance. Manual scripts
and checksums can reproduce parts of this workflow. No overall superiority, faster
queries or automatic correctness is claimed. [Disclosed comparison](COMPARISON.md).

## Tests and recorded validation

```sh
python -m unittest discover -s tests -v
```

The strict-display baseline passed **130 local Linux tests, zero skips**, including
actual CLI tampering, numeric-type distinctions and all three evidence formats.
For public commit `4ddcab79ccc2257f11bc7d1aa6ccc38e0eceb655`, the
[GitHub run overview](https://github.com/walker512/queryproof/actions/runs/44274499101)
was checked: overall **Success**, four jobs completed. Individual job logs were not
reviewed in that check. This is not evidence for a later commit or new visual acceptance.

[Current validation scope](VALIDATION.md) · [Version history](CHANGELOG.md)

MIT · walker512
