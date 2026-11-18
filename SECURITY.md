# Security and disclosure

Do not upload real sensitive data in issues. Reproduce bugs with fictional fixtures. Contact the repository owner privately through GitHub if available; if not, file only a non-sensitive request for a private contact channel.

QueryProof is a local tool, not a hardened arbitrary-SQL service. Never wrap it in an unauthenticated public endpoint. The Python process and SQLite runtime must be trusted and patched. Native parser exploits, compromised libraries and other local users/processes are outside scope. Use an OS sandbox for hostile database files.

SQL is restricted by SQLite's authorizer and read-only connections; a function allowlist blocks file/extension/clock/random functions. Bounded results and VM progress deadlines reduce resource risks but are not hard CPU/memory isolation. User input is HTML-escaped; reports load no scripts or remote resources. There is no signature or identity verification, and recomputation is not business correctness.

Bundles contain the complete source database. JSON row omission is not anonymization. Do not publish real bundles unless every included table, query, label and statistic is authorized for disclosure.

New bundle files are exclusively created with requested POSIX mode 0600, inside
0700 directories, without changing the process umask. Old bundles are not repaired.
Publication is multi-file copying after exclusive directory reservation, not atomic:
I/O failure or interruption may leave an incomplete destination. Never reuse it;
verify before sharing. A trusted parent directory and local account are required.
Windows ACL guarantees and hostile same-account path races are not certified.
