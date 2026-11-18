# Optional strict display verification

Run `python -m queryproof_check BUNDLE --strict-display --json` (or the installed
`queryproof-check` command). Exit 0 requires supported data verification and exact
HTML byte agreement. Exit 1 is a failed check. No HTML is opened, executed, fetched,
or rewritten. No browser acceptance or Windows/macOS execution is claimed.

For `queryproof/1`, strict display supports the fixed `queryproof` 0.2.0 renderer
shipped in this release only. After the existing snapshot/SQL/diagnostic checks
succeed, it independently rebuilds the receipt and compares canonical JSON bodies
with numeric types preserved (bool, integer, real and signed zero are distinct).
Recorded informational environment fields are retained, not newly authenticated.
This extra recomputation uses the existing per-query bounds; a query can therefore
run twice. Historical Python-equality behavior remains only in the old default.
It then rebuilds HTML from the verified receipt and compares UTF-8 bytes with
`report.html`. Unknown formats/tool versions fail closed. Older bundles produced
by this exact renderer work without editing. A different historical template,
whitespace/newline normalization, reformatted receipt field order, or manual HTML
edit can fail even if data reproduces: there is no heuristic migration or HTML
normalization. Keep the original and use the appropriate recorded release rather
than editing evidence to pass.

Without the flag, legacy data checks remain unchanged and explicitly say HTML is
NOT verified. The old `queryproof.py verify` and `diagnose` commands still check
only their original data scope. Witness/groups formats already compare their HTML;
the flag retains those complete existing checks. Strict success adds
`display_verified: true`; absent/failed verification must not be inferred as success.
The HTML's own historical warning is deliberately not rewritten after a check.

Changed displayed numbers, inserted scripts/images/links, altered CSP, missing or
extra bytes are rejected by exact comparison. Escaped SQL/source text remains
untrusted data, not an endorsement of any URL or factual statement. This is display
consistency, not sanitization of arbitrary HTML, proof of source truth, authorship,
SQL correctness, or permission to share. Coordinated replacement of a snapshot,
receipt and correctly regenerated report can still pass.

The existing exact three-member legacy bundle layout and bounded regular-file
checks apply (32 MiB SQLite; 16 MiB receipt/HTML); rebuilt HTML also has a 16 MiB
limit. Symlink/FIFO members and extra files fail. Verification does not lock the
bundle or protect against another process changing it afterward, hostile parent
paths or malicious same-account filesystem races. Use trusted private local
copies; results describe the bytes read, not a later browser view. No network,
plugins, receipt-selected paths, templates or executable renderers are introduced.

Public regression tests create synthetic SQLite bundles and actually run the CLI.
They cover exact old rendering, legacy default compatibility, numeric/script/image/
link/CSP mutations, unsupported versions, malformed layouts, POSIX FIFO/symlink
rejection, byte limits, private errors and nonmutation. These are code/CLI checks,
not visual or assistive-technology acceptance.

RC2 validation: 130 Linux tests passed, zero skips, including eleven actual CLI
integer/bool/real/signed-zero and nested diagnostic mutations with regenerated
checksums and HTML. No new hosted CI or cross-platform result is claimed.
