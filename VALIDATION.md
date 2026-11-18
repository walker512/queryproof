# Unified offline handoff check candidate (unpublished)

Based on the independently audited publication-safety patch released at
`1827645818b9108b2033b2f4b6d4bfd63fd9be5a`. This candidate adds one optional
`queryproof-check` CLI and does not change existing receipt schemas or computation.

Executed locally on Linux: **118 tests passed, zero skips** (102 existing + 16
new tests), compileall passed, standard-library-only wheel built with no build
isolation, installed without index into a fresh venv. Outside the source checkout,
the installed `queryproof` generated a synthetic CSV bundle and installed
`queryproof-check --json` verified it. A first smoke invocation used the wrong
table alias and correctly failed before output publication; the corrected input
ran successfully. Three-format round trips and subprocess CLI coverage are in
the public tests, along with tampering, duplicate/oversize/malformed receipt,
unsupported-format no-fallback, mixed layout, symlink, private-error suppression,
read-only content preservation, and legacy HTML verification scope tests.

No browser, remote CI, Windows or fresh independent-review result is claimed for
this increment. The legacy HTML display remains unverified; witness and group
HTML is recomputed by their existing verifiers. Exact-layout checks are stricter
than legacy `verify`; recipient must supply a complete clean bundle. Status is
recomputation only, never semantic correctness, source truth or authorship.
Filesystem races / malicious local processes remain outside the threat model.

The first candidate failed independent review: a re-signed legacy receipt with a
non-string key-check table escaped as AttributeError. Revision 2 validates the
legacy nested inputs before dispatch, catches known malformed-shape exceptions,
and has a final Exception boundary returning CHECK_FAILED (never successful
verification). KeyboardInterrupt and SystemExit are not swallowed. New tests run
13 re-signed malformed key/join/result/source/environment cases through the real
CLI --json, requiring exit 1, parseable JSON and empty stderr without private
strings or paths. Unexpected verifier failures are tested in all three modes.
118 tests and compileall above were rerun on this revision; earlier wheel smoke
preceded this revision and is not claimed as its installed-runtime verification.

## Earlier published and historical validation records

# Validation · QueryProof publication-safety candidate

## Current candidate: local publication correction

**102 tests passed, zero skips**, on Linux/Python 3.12; compileall passed. An independent reviewer reproduced 102/102 and checked the candidate file manifest. This increment is based on the locally recovered public 0.4 source, not a new general feature or full-topic completion.

The legacy CLI previously could replace an empty destination created after initial checking. A deterministic test reproduces that failure on the old source. All three output modes now reserve a new directory exclusively, request 0700 directories and 0600 files at creation, and leave existing destinations unchanged. Tests include 24 concurrent publishers, umask 000/022 across all three modes, dangling symlink refusal, and failed-copy verification rejection. No process umask change is made.

Publication is **not atomic**: computation and internal verification finish before reservation, but interruption or I/O failure during copying can leave an incomplete private output directory. Verify before use and retry with a fresh destination; no existing output is recursively removed or reused. Old files are not chmodded. Trusted parent directories/account are required; malicious same-account replacement, ACL overrides, Windows ACL privacy and power-loss durability are not guaranteed.

No browser, Windows/macOS, installed-wheel, hosted CI or competitive benchmark was run for this increment. Historical results below apply only to their recorded versions and must not be inherited by this candidate. This candidate has not been published.

## Historical 0.2.0 verified state (not current candidate results)

- **36 tests pass locally.** Bytecode compilation and the documented create → verify CLI workflows pass. A clean virtual environment installation was also exercised outside the repository: the installed `queryproof` entry point created and verified a real fictional-data bundle.
- **Hosted CI passed on Linux Python 3.11, 3.12 and 3.13, and Windows Python 3.12.** [Successful run 43997341003](https://github.com/walker512/queryproof-candidate/actions/runs/43997341003) tested remote commit `b14ba2b59972a247257003812c8bd7b123f1b5a6`. Its downloaded source archive matched all 18 tracked file SHA-256 hashes of reviewed local commit `5aff7205ee3a78659da169988f6d92bb9338ee69`. Each matrix job runs the full unittest suite and compileall. This is hosted Windows execution, not a claim of testing every Windows installation.
- **Desktop Chromium report review passed.** The actual generated report displays SQL, results, diagnostics, verification/privacy warnings, the producer-environment table and an expandable full receipt. No overlapping content was observed at the tested desktop viewport. Mobile viewports are not verified.
- **Both comparison harnesses pass.** `benchmarks/compare.py` runs identical SQL/data against Datasette 0.65.2 and optionally the existing Join Key Lab. `benchmarks/handoff.py` asserts all six disclosed handoff conditions. Recorded results are included; these are fictional fixtures, not private data or production-adoption evidence.
- This documentation cleanup changes no runtime, tests, fixtures, dependencies or workflow. The hosted run above covers the preceding source state; later documentation commits must not be described as that run's tested commit.

## Historical 0.2.0 functional and security coverage

The deliberately inflated JOIN returns **90.0**; the corrected EXISTS query returns **60.0**. Both reproduce. Explicit diagnostics predict five pairs and one many-to-many key. Reproduction does not establish business correctness.

Tests cover CSV and SQLite round trips, committed WAL backup, leading zeros, LF/CRLF quoted multiline fields, empty strings, invalid CSV, BLOB results, row/payload/time limits, unknown columns and pre-publication computation-failure cleanup in that historical version. The current multi-file publication can leave an incomplete destination, as described above. Tampered receipts, changed databases and rechecksummed incorrect results fail verification. Missing or inconsistent environment/build metadata and live snapshot sidecars fail closed.

Adversarial SQL checks include DELETE, DROP, ATTACH, PRAGMA writes/table functions, extension/file functions, random/clock functions, temporary tables, CTE DELETE, REINDEX, VACUUM, BEGIN and multiple statements. They are denied; original database bytes remain unchanged. HTML-shaped values are escaped and the report has a restrictive CSP. Spreadsheet-formula-shaped values remain inert text in HTML; no CSV/XLSX export or formula-neutralization feature is claimed.

The runtime performs no network requests or uploads. Bundles deliberately contain the full source snapshot, SQL and metadata: they are not anonymized. Limits and progress deadlines are not a hard OS sandbox. Symlink/race attacks by other local processes, native SQLite vulnerabilities and compromised runtimes remain outside the documented threat model. Public author identity is walker512; bundled source/examples contain no real name, credentials or private dataset.

## Historical 0.2.0 competitive finding and limits

The independent handoff exercise demonstrates a narrow benefit: the integrated verifier detects changed snapshot bytes even when the query answer remains unchanged, and returns a structured failure stage plus recovery guidance. The disclosed Datasette JSON/database/version handoff misses this condition. The **stronger manual SHA-256 control also detects it**, and is included rather than hidden.

This is a packaged workflow improvement, not an exclusive algorithm or proof of superior SQL accuracy, security, speed, human usability, adoption, or superiority over Datasette's plugin ecosystem. Join Key Lab has richer normalization and cardinality-contract features. See [the full comparison](COMPARISON.md).

The SQLite version-mismatch case uses deliberately altered metadata; it does not execute two different SQLite runtimes. Matching version/build metadata does not guarantee universal cross-platform portability. Receipts are checksummed, not signed; an adversary who changes both data and receipt can create a different valid bundle.

## Review history (superseded intermediate states)

1. Initial implementation passed 16 tests. Independent review found and fixed JOIN CTE alias collisions with tables named `l`/`r`, incorrect filtering of legal `sqliteX` table names, and crashes on scalar/array receipts. Expanded suite: 21 tests.
2. Initial browser attempts were blocked by execution/preview limitations. A later loopback preview successfully rendered the real report, superseding the earlier unverified visual state.
3. The initial competition review withheld approval because mere feature existence did not prove an advantage. Version 0.2.0 added failure-stage diagnostics and the explicit six-case handoff comparison with its stronger manual control.
4. The 32-test 0.2.0 submission had a build-verification gap: a rechecksummed empty environment object could be accepted. Required typed fields, consistent version fields and rejection of unknown environment fields closed it. Independent suite: 35 tests. New environment HTML then passed desktop visual review.
5. [Initial hosted run 43996609514](https://github.com/walker512/queryproof-candidate/actions/runs/43996609514) found one Windows fixture issue: text-mode output translated embedded LF to CRLF, but the test expected LF. The fix writes explicit LF bytes and adds a separate CRLF-preservation test; it does not weaken the assertion or change runtime code. The resulting 36-test matrix passed in the successful run linked above.

Runtime SHA-256 after review and the Windows fixture fix:
`f953f9d48e671a64eb25f0bac45590815b1c3666877a49e930376036e75654b1`

No claim of publication is made by this validation record. Nonblocking hosted warnings concerned action runtime deprecation/runner-label migration; they are not product test failures.

## Separate 0.3.0 single-table witness increment

The distribution now also installs `queryproof-witness`; the preceding 0.2.0 hosted-CI/browser observations do not cover this new module. Local verification: **67 tests passed, zero skips** on Linux/Python 3.12 / SQLite 3.53.1 (original 36 tests unchanged + 31 witness tests). A locally built, offline-installed wheel was exercised from outside the checkout in a new virtual environment: rows and COUNT bundles, their verification, and unchanged legacy CSV receipt → snapshot → new witness all ran. See [SOURCE_WITNESSES.md](docs/SOURCE_WITNESSES.md) for precise source-row evidence, limits and non-authentication boundaries. No new browser/Windows/macOS/hosted-CI or competitor claim is made.
