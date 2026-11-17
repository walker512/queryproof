# Scope comparison · 2026-11-17

Sources reviewed, not a performance benchmark:

- [Datasette official project](https://datasette.io/): established data exploration/publishing, interactive API, plugin ecosystem. Keep using it for those workflows.
- [datasette-llm 0.1a11 release, 2026-11-14](https://simonwillison.net/2026/Nov/14/datasette-llm/): OpenAI-compatible endpoints permit local models; published screenshot already exposes SQL and results. Neither local AI nor “show SQL” is a QueryProof invention.
- [Join Key Lab](https://github.com/walker512/join-key-lab), local README inspected: normalization policies, composite keys, relationship contracts and changed-pair analysis. QueryProof is narrower in JOIN analysis, but attaches explicit checks to a durable query/snapshot receipt.

QueryProof borrows the good conventions of visible SQL, local execution, structured outputs and explicit data semantics. It adds one focused implementation: rerun the exact query **and** recorded diagnostics against a bounded snapshot, compare ordered results and file checksums offline. This is a workflow comparison, not a claim that no Datasette plugin or other system can do this. No competitor source code was copied; no performance/usability superiority was measured.

Current gaps: no AI natural-language interface, browser query editor, remote DB adapters, composite-key contracts, row-level lineage or trusted signatures. These are not secretly simulated. In particular, a valid receipt can accompany an incorrect business answer; the included inflated-join demo makes that visible.

## Same-fixture independent comparison

Reproduce in an isolated environment with `datasette==0.65.2` installed:

```sh
python benchmarks/compare.py /path/to/join-key-lab
```

The optional Join Key Lab path refers to its existing source checkout. Results and its tested engine hash are in `benchmarks/results.json`. The comparison uses Datasette's in-process ASGI client, not an exposed server. These are tiny fictional fixtures, not a speed benchmark; the pinned Datasette version is not claimed to be the latest version or to represent all plugins.

| Task on identical sales/labels data | Observed result |
| --- | --- |
| Execute inflated and corrected SQL | Datasette and QueryProof both return 90.0 and 60.0. No accuracy advantage. |
| Prevent DELETE through query interface | Datasette rejects it with HTTP 400; QueryProof rejects it with SQLite authorization. Read-only SQL is not novel. |
| Predict exact join cardinality | Join Key Lab and QueryProof both return 5 pairs and 1 many-to-many group. No diagnostic superiority. |
| Explain normalization / enforce declared one-to-one | Join Key Lab reports five normalization policies and failed one-to-one contract. QueryProof does not supply this feature. |
| Hand an offline query evidence package to another reviewer | QueryProof creates the snapshot, SQL, result digest, diagnostic receipt and HTML, then independently recomputes them. The tested default Datasette JSON response contains SQL, columns, rows and query timing, but not this bundled verifier workflow. |

The last row is a **demonstrated workflow increment**, not proof that Datasette plus plugins/scripts cannot do it. No timed usability study, plugin ecosystem survey or third-party adoption evidence was collected. Therefore the user's stronger requirement of being demonstrably better than competing projects is **not yet established**: do not advertise general superiority or publish on that premise.

Official references checked: [Datasette SQL queries](https://docs.datasette.io/en/stable/sql_queries.html), [Datasette JSON API](https://docs.datasette.io/en/stable/json_api.html), and [Join Key Lab](https://github.com/walker512/join-key-lab). Datasette already offers visible/shareable SQL, structured results and query restrictions; Join Key Lab already offers local, explicit cardinality semantics. Those strengths are retained where applicable, not claimed as inventions.

## Handoff fault exercise (0.2.0)

Reproduce: `/path/to/datasette-venv/bin/python benchmarks/handoff.py > benchmarks/handoff-results.json` with Datasette 0.65.2. The checked-in output is from an actual local run. Both workflows use the **same SQLite snapshot, sales/labels fixture and `correct.sql`**, producing 60.0. An additional `revision` table makes a stale snapshot that leaves this answer unchanged observable. No human participants or timing claims.

**Baseline, stated precisely:** export Datasette's standard JSON response (which already includes SQL), copy the SQLite file, separately record SQLite version. The recipient inspects the saved SQL, compares recorded/current version, reruns the SQL via Datasette and manually compares ordered columns/rows. The benchmark automates that disclosed manual recipe to make results repeatable; these manual checks are **not** claimed to be Datasette built-ins. No optional plugins are loaded.

**QueryProof:** producer runs `run`; recipient runs `verify PATH --json`. It checks receipt structure/integrity, snapshot identity, runtime/build, then result and diagnostic reproduction, returning the first failed stage, a stable code and next-step guidance. These are workflow actions, not measured elapsed times or a claim of fewer human mistakes.

| Injected handoff condition | Datasette + disclosed manual recipe | QueryProof actual result |
| --- | --- | --- |
| Intact | Ordered result matches | `VERIFIED` |
| Recorded answer changed to 999 | Rerun reveals different result | `RECEIPT_CHECKSUM`; request original receipt, do not re-sign |
| Old DB, revision metadata changed, answer still 60 | Result matches; this recipe cannot establish exact snapshot identity | `SNAPSHOT_CHECKSUM`; request exact matching snapshot |
| Old DB, sales changed, answer becomes 30 | Rerun reveals different result | `SNAPSHOT_CHECKSUM` before query execution |
| Exact SQL removed from both exported responses | Recipient detects missing SQL | `SQL_MISSING`; request original bundle, not guessed SQL |
| Recorded SQLite version incompatible with receiver | Separate manual version check detects mismatch | `SQLITE_VERSION`; recorded/current environment and specific recovery guidance |

The version case deliberately changes the recorded version to `0.0.0-test-fixture` and recomputes the receipt checksum to reach the version gate. **It tests mismatch handling, not execution on two SQLite versions.** It is not compatibility evidence.

**Measured narrow advantage:** compared with this standard JSON/database handoff, QueryProof detects the deliberately stale but same-answer snapshot and produces a machine-readable failure stage and repair instruction with one verifier invocation. It also bundles version/build checking and diagnostic recomputation rather than requiring the recipient to assemble them. This is an observed identity-checking/diagnostic workflow improvement on these fixtures, not an overall capability or accuracy win.

**Fair stronger control:** provide a separately recorded producer SHA-256 with the manual handoff and check it. The benchmark actually executes that control: it also detects the stale same-answer database (`provided_digest_matches_changed_database: false`). Thus the advantage is integrated, repeatable handoff verification, not an exclusive algorithm; a careful manually assembled hashing/recomputation workflow can close the gap. Datasette remains stronger for exploration, publishing, APIs and extensibility. No evidence here proves QueryProof is superior to its entire ecosystem or guarantees cross-version reproduction. Release eligibility still requires independent review of this specifically scoped benefit.
