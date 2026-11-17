# Local validation

Validated using Python 3.12 / the runtime SQLite version recorded in generated receipts.

- 21 unittest cases passed with `python -m unittest discover -s tests -v`.
- Bytecode compilation passed.
- Documented inflated-JOIN CLI example created a receipt, returned 90.0, and verified successfully. Its diagnostic predicted 5 inner rows and 1 many-to-many key.
- Corrected EXISTS query returned 60.0 and verified successfully.
- These are fictional fixtures, not private user data or claims of production adoption.
- Hostile SQL tests exercise DELETE, DROP, ATTACH, PRAGMA write, extension/file functions, random/clock functions, VACUUM, BEGIN and multiple statements. Source file hash remained unchanged.
- Tampered receipt, tampered database and rechecksummed incorrect result all failed validation.
- CSV import preserves leading zeros, quoted multiline fields and empty strings. Bad headers/width/quotes fail and clean up the partial snapshot.
- Committed WAL data survives snapshot backup.
- HTML escaping is unit-tested with script-shaped text. A headless Chromium visual check was attempted but blocked by this execution sandbox's socket/filesystem constraints before page load. **Visual/browser QA has not passed** and is a review item, not a claimed result.
- Hosted GitHub CI and Windows execution are configured but **not run here**. SQLite connections are explicitly closed to avoid Windows file locks, and Unix-only mode assertions are skipped on Windows.

Independent review and publication remain the parent task's responsibility. No remote repository, package index or release was created by this task. Public author identity is walker512; no real name, credentials or private source data is included.

## Independent audit (2026-11-17)

A separate reviewer reran all 21 tests, bytecode compilation, and both documented CLI create/verify workflows. Inflated JOIN returns 90.0 with 5 predicted pairs / 1 many-to-many key; corrected EXISTS returns 60.0. Both reproduce, as intended.

Three defects found and fixed before publication:
- Tables named `l` or `r` conflicted with internal JOIN CTE names. Derived tables now avoid CTE shadowing, with a regression test.
- The profile's `sqlite_%` pattern excluded legal table names such as `sqliteX`. Exact reserved-prefix filtering now includes these tables.
- A JSON array/null/scalar receipt crashed with an unhandled traceback. These now fail cleanly with exit code 1.

Added adversarial checks for PRAGMA table functions, writable_schema, writefile, temporary tables, CTE DELETE, REINDEX, current_timestamp and unapproved runtime functions. All are denied; original database bytes remain unchanged. HTML-shaped and spreadsheet-formula-shaped output remains escaped inert HTML. There is no CSV/XLSX export, so spreadsheet formula neutralization is not a claimed feature.

No external requests or upload implementation exists in the runtime. SQL and metadata are deliberately not anonymized; full snapshots require an explicit privacy review before sharing. Fixed verifier filenames prevent receipt-controlled path selection, but symlinks/filesystem races and hostile native SQLite vulnerabilities are not sandboxed. Public package/license identity is walker512; bundled fixtures are fictional.

This is a local CLI/evidence tool, not an interactive SQL editor or automatic data-quality inference engine. The report is explicitly labeled unverified until CLI recomputation. No production adoption or competitive performance advantage has been established. Browser visual QA and hosted matrix CI remain separate gates; the static security and CLI audit does not claim those passed.

The independent browser attempt also did not reach report rendering: the cloud browser disallowed the `file:` protocol, and a separate preview-terminal attempt failed with an ambiguous native-window identity before starting an HTTP server. Desktop input was released to avoid interference with other work. This is an environment limitation, not a passed visual inspection.

### Browser follow-up: passed desktop rendering

After coordinated exclusive desktop access, the reviewer served only the fictional generated HTML from a shared QA directory on loopback port 8883. Chromium rendered the real report successfully: readable heading and verification warning, SQL, result/profile contents, full JOIN diagnostics, and native expanded machine-readable receipt. Screenshots showed no overlapping content at the tested desktop viewport. This supersedes the earlier blocked attempt for **desktop report rendering only**; mobile viewport coverage and hosted/Windows CI are still not claimed.

### Comparative release gate

Independent same-input execution against default Datasette 0.65.2 and the existing Join Key Lab is recorded in `benchmarks/results.json`, with a rerunnable harness. Both competitors match the overlapping arithmetic/readonly behaviors; Join Key Lab has richer normalization and contract diagnostics. QueryProof demonstrates a packaged offline evidence/recomputation workflow, not broad superiority. Competitive-superiority release approval is withheld pending concrete evidence under that stronger user requirement. This does not invalidate the passed functional/security checks.

## 0.2.0 handoff diagnostics verification

- 32 unit tests passed after the diagnostic/environment changes; compileall passed for application and benchmark scripts.
- Original same-fixture Datasette/Join Key Lab benchmark rerun successfully; `benchmarks/results.json` refreshed.
- `benchmarks/handoff.py` executed with installed Datasette 0.65.2; all six asserted scenarios passed, full observed results in `benchmarks/handoff-results.json`.
- Outcomes: intact verified; edited answer rejected by receipt checksum; both old-database variants rejected by snapshot checksum; omitted SQL rejected with an actionable missing-query code; simulated version mismatch rejected with recorded/current runtime details.
- Stronger manual control with a supplied SHA-256 also detected the same-answer old database. This is explicitly reported, not hidden.
- Eleven added unit tests cover structured success, missing receipt/SQL/snapshot, version/build mismatch guidance, informational Python metadata differences, snapshot sidecars, exact differing evidence section, malformed environment and tool-version mismatch.
- Version mismatch is deliberately injected metadata, not an executed second SQLite version. No cross-version reliability, speed, human usability or adoption result is claimed.
- HTML now includes a producer-environment section; this change still needs independent visual review. No remote publication performed.

### Independent 0.2.0 re-review

The reviewer reran the 32-test submission and both comparison harnesses, then found a fail-open in the new build-validation gate: an empty environment object with a recomputed receipt checksum was accepted as VERIFIED. The fix requires a complete, typed environment record consistent with both recorded version fields; unknown fields are rejected rather than echoed into diagnostic errors. Three additional tests cover missing build fields, unexpected sensitive fields, and inconsistent versions. **All 35 tests now pass**, as do compileall, the real CLI create → JSON verify workflow, the same-input comparison and all six handoff cases. Benchmark JSON outputs were regenerated from this final reviewed code.

The six-case exercise establishes one narrow benefit: out-of-the-box exact-snapshot identity validation detects a changed database even when the query answer is unchanged, alongside structured recovery guidance. The disclosed Datasette JSON/database/version handoff misses that condition, while the explicitly tested stronger manual hash control catches it. No claim of an exclusive algorithm, superior SQL accuracy, greater security than Datasette, shorter completion time, lower human error, or plugin-ecosystem superiority follows. The pinned competitor version and synthetic version-mismatch injection remain explicit limitations.

Functional/security readiness is approved for the documented local-tool threat model. The specific handoff advantage is now independently reproduced. Universal superiority is not established; release claims must stay within this tested scope, and hosted/Windows CI remains unverified. This reviewer did not publish.

### Final 0.2.0 HTML review

The independent reviewer regenerated a real corrected-query bundle with 0.2.0, verified it through `verify --json`, and rendered its report in Chromium. The new Producer environment section displays the tool version, Python implementation/version, OS, architecture and SQLite version/source ID in readable table columns. The full receipt expands and exposes recorded compile options; the portability warning remains explicit. Desktop screenshot and accessibility checks passed. No mobile-viewport or Windows execution claim is implied. Runtime source and tests were frozen for separate Windows verification; final local suite remains 35/35 passing.
