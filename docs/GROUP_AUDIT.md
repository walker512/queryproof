# Independent review: QueryProof rebuilt 0.4.0 grouped contributors

Reviewed queryproof_groups.py, witness publication changes, final tests, group specification/demo, README and GROUP_CONTRIBUTORS.md. This is a new extension of public 0.3.0, not a recovered earlier RC2.

## Corrected finding
The original copy-publication implementation created a destination with default POSIX permissions, changing prior 0700 private output to 0755 under umask 022. Independently reproduced using synthetic data. Final code explicitly requests mkdir(mode=0o700), adds a regression test, and the installed-wheel output was observed as 0700. Existing-output refusal and non-atomic interruption limits remain explicit.

## Independent evidence
- Final complete Linux/Python 3.12 suite: 96 tests passed, zero skips.
- Independently authored randomized oracle: 80 real temporary SQLite trials, single/two-column/global groups, integer/REAL/text/BLOB/NULL keys, signed zero, case-sensitive and embedded-NUL strings, NOCASE/RTRIM declared columns, empty sets and integer sums. All expected results matched.
- Explicit intermediate-overflow input [9223372036854775807,1,-1] was correctly rejected by SQLite/tool although mathematical final total is representable.
- Built wheel and installed into new venv, then ran console entry point outside source checkout. Module path confirmed venv site-packages, not checkout.
- Actual seven-row SQLite example: four groups; North=[3,2,240], north=[1,1,-20], South=[2,2,75], NULL=[1,0,NULL]. Seven complete source witnesses, one duplicate-value row beyond first, report verification passed without original-source dependence.
- git diff --check passed.

## Identities
queryproof_groups.py SHA-256: 23902bcd6552f367b01bb63165e4b080cefadbc5c44293fccc50e23c1f1e9b0d
queryproof_witness.py SHA-256: 23fb6c120562201692bf81f181757ce35cdd6275d86fec87b8c994571fe8689c
tests/test_groups.py SHA-256: 5fcffec343776f52c677e064d03b58583e7b0b3dc0834b10828b4c565d998de0
wheel SHA-256: 1245138bcd14068271874f905699f57c8e6e8e5328535f5eddc2f929480987f8

## Conclusion
No remaining release-blocking defect established in the reviewed Linux CLI scope. Typed grouping intentionally separates integer and REAL keys rather than adopting bare SQLite numeric-key merging. SUM rejects coercion and overflow. Complete contributors/null exclusions and offline SQL recomputation are verified; they do not establish business truth or evidence authenticity. Bundles retain the full private snapshot.

Real Windows/macOS and remote CI were not executed. The directory-copy approach avoids reliance on replacing an existing Windows directory, but that is a code-review conclusion, not a Windows test pass. Publication is non-atomic and hostile parent-directory races are outside its guarantee. No new browser/GUI or accessibility validation, arbitrary SQL lineage, external publication, or competitor superiority claim.
