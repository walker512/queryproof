"""One offline entry point for QueryProof's three fixed evidence formats."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import queryproof as legacy
import queryproof_witness as witness
import queryproof_groups as groups

FORMATS = {
    'queryproof/1': ('query', {'snapshot.sqlite', 'receipt.json', 'report.html'}),
    'queryproof-witness/1': ('witness', witness.FILES),
    'queryproof-groups/1': ('groups', groups.FILES),
}


def legacy_structure(receipt):
    """Validate nested fields used as inputs before the legacy recomputation."""
    def name(value):
        if type(value) is not str or not value or '\0' in value:
            raise ValueError('Identifier must be a nonempty string')
    for field in ('key_checks', 'join_checks', 'sources', 'profile'):
        if type(receipt.get(field)) is not list:
            raise ValueError('Expected list')
    if type(receipt.get('result')) is not dict or type(receipt.get('environment')) is not dict:
        raise ValueError('Expected object')
    for item in receipt['key_checks']:
        if type(item) is not dict:
            raise ValueError('Expected key check object')
        name(item.get('table')); name(item.get('key'))
    for item in receipt['join_checks']:
        if type(item) is not dict:
            raise ValueError('Expected join check object')
        for side in ('left', 'right'):
            pair = item.get(side)
            if type(pair) is not list or len(pair) != 2:
                raise ValueError('Expected table/key pair')
            for value in pair:
                name(value)


def check(directory, *, strict_display=False):
    """No inferred SQL, paths, commands, plugins or fallback verifiers from a receipt."""
    mode = None
    stage = 'input'
    try:
        if type(strict_display) is not bool:
            raise ValueError('Boolean display policy required')
        root = Path(directory)
        if root.is_symlink() or not root.is_dir():
            raise ValueError('Directory required')
        raw = witness.read(root / 'receipt.json', witness.MAX_OUTPUT)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate receipt key')
                result[key] = value
            return result
        receipt = json.loads(raw.decode('utf8'), object_pairs_hook=unique)
        if type(receipt) is not dict:
            raise ValueError('Receipt object required')
        fmt = receipt.get('format')
        if type(fmt) is not str or fmt not in FORMATS:
            return outcome(False, None, 'UNSUPPORTED_FORMAT', 'format')
        mode, files = FORMATS[fmt]
        stage = 'layout'
        if {p.name for p in root.iterdir()} != files:
            raise ValueError('Exact files required')
        for name in files:
            witness.regular(root / name, legacy.MAX_FILE if name == 'snapshot.sqlite' else witness.MAX_OUTPUT)
        stage = 'verification'
        if mode == 'query':
            legacy_structure(receipt)
            legacy.verify(root / 'snapshot.sqlite', receipt)
            if strict_display:
                stage = 'display'
                # Only this fixed legacy renderer is supported. No template, path,
                # script or renderer is selected from untrusted receipt fields.
                if receipt.get('version') != '0.2.0' or legacy.VERSION != '0.2.0':
                    return outcome(False, mode, 'UNSUPPORTED_DISPLAY_VERSION', stage)
                # Legacy verification intentionally retains its historical Python
                # equality semantics. Strict mode additionally distinguishes JSON
                # bool/int/float at every rebuilt depth, including diagnostics.
                rebuilt = legacy.create(
                    root / 'snapshot.sqlite', receipt['sql'], receipt['sources'],
                    [(x['table'], x['key']) for x in receipt['key_checks']],
                    [(*x['left'], *x['right']) for x in receipt['join_checks']],
                    'rows' in receipt['result'])
                rebuilt['environment'] = receipt['environment']
                def typed_body(value):
                    body = {k: v for k, v in value.items() if k != 'receipt_sha256'}
                    return json.dumps(body, sort_keys=True, ensure_ascii=True,
                                      separators=(',', ':'), allow_nan=False)
                if typed_body(rebuilt) != typed_body(receipt):
                    return outcome(False, mode, 'TYPED_EVIDENCE_MISMATCH', stage)
                expected = legacy.report(receipt).encode('utf-8')
                if len(expected) > witness.MAX_OUTPUT:
                    raise ValueError('Rendered display exceeds limit')
                actual = witness.read(root / 'report.html', witness.MAX_OUTPUT)
                if actual != expected:
                    return outcome(False, mode, 'DISPLAY_MISMATCH', stage)

        elif mode == 'witness':
            witness.verify(root)
        else:
            groups.verify(root)
        result = outcome(True, mode, 'VERIFIED', 'complete')
        if strict_display:
            result['display_verified'] = True
            result['scope'] = ('Snapshot, SQL result and diagnostics recomputed; fixed legacy 0.2.0 HTML bytes matched.'
                               if mode == 'query' else result['scope'])
        return result
    except (ValueError, OSError, sqlite3.Error, UnicodeError, KeyError, TypeError, RecursionError, OverflowError, AttributeError, IndexError):
        return outcome(False, mode, 'INVALID_BUNDLE', stage)
    except Exception:
        # Last-resort output-contract boundary. Never claim verification succeeded;
        # do not expose exception strings or paths. Interrupts/SystemExit propagate.
        return outcome(False, mode, 'CHECK_FAILED', stage)


def outcome(ok, mode, code, stage):
    result = {'ok': ok, 'mode': mode, 'code': code, 'stage': stage,
              'semantic_correctness_verified': False, 'authorship_verified': False}
    if ok:
        result['scope'] = ('Snapshot, SQL result and diagnostics recomputed; HTML display is NOT verified.'
                           if mode == 'query' else 'Complete fixed-format evidence and HTML recomputed.')
    else:
        result['remedy'] = 'Keep the original bundle. Request its complete supported format and matching SQLite/tool build; do not edit evidence to make verification pass.'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--json', action='store_true', help='Fixed metadata only; no SQL, source values or exception text')
    parser.add_argument('--strict-display', action='store_true',
                        help='Also require exact supported HTML bytes; never opens or executes HTML')
    args = parser.parse_args(argv)
    result = check(args.directory, strict_display=args.strict_display)
    if args.json:
        print(json.dumps(result, indent=2))
    elif result['ok']:
        print('VERIFIED (' + result['mode'] + '): ' + result['scope'])
        print('Reproduction is not source truth, semantic correctness or authorship.')
    else:
        print(result['code'] + ' at ' + result['stage'] + '. ' + result['remedy'], file=sys.stderr)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
