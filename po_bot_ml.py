#!/usr/bin/env python3
"""
patch_ml1_fixes.py - small exact-text patches for po_bot_ml_1.py

Usage:
    python3 patch_ml1_fixes.py [path/to/po_bot_ml_1.py] [--skip=direction]

One concern per patch. Every hunk must match exactly once (or already be
applied). If ANY hunk fails, nothing is written. A .bak copy is made before the
file is touched.
"""
import shutil
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
SKIP = {a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--skip=')}
PATH = args[0] if args else 'po_bot_ml_1.py'


def L(*lines):
    return '\n'.join(lines)


PATCHES = [
    (
        'ema_feature',
        'The first feature (EMA cross) was always computed from the LAST candles, '
        'so every training row got the same value - a dead column. It now uses the '
        'row index i (i = -1 for the live row, so live behaviour is unchanged).',
        [
            (
                "emashort[-2].ema > emalong[-2].ema and emashort[-1].ema < emalong[-1].ema and get_value(",
                "emashort[i - 1].ema > emalong[i - 1].ema and emashort[i].ema < emalong[i].ema and get_value(",
            ),
            (
                "quotes[-1]) < get_value(quotes[-2]) < get_value(quotes[-3]) else 0)",
                "quotes[i]) < get_value(quotes[i - 1]) < get_value(quotes[i - 2]) else 0)",
            ),
        ],
    ),
    (
        'time_split',
        'train_test_split was shuffling candle rows, so the test set sat inside the '
        'training period (leakage). Now the test set is the most recent 20%.',
        [
            (
                "train_test_split(X, y, test_size=0.2, random_state=42)",
                "train_test_split(X, y, test_size=0.2, shuffle=False)",
            ),
        ],
    ),
    (
        'show_n',
        'The Accuracy line now prints the test-set size (n=...) so you can see how '
        'little ~30 rows can tell you.',
        [
            (
                "Accuracy: {acc_emoji} {round(model_accuracy, 2)}  |  '",
                "Accuracy: {acc_emoji} {round(model_accuracy, 2)} (n={len(y_test)})  |  '",
            ),
        ],
    ),
    (
        'direction',
        'The label is 1 when the NEXT close is lower-or-equal, so predict_proba column 1 '
        'is P(down) and column 0 is P(up). The code had them swapped (CALL on P(down)). '
        'Fixed the print and the trigger. Assumes utils.get_value returns the close - '
        'skip with --skip=direction if it does not.',
        [
            (
                "{EMO_PUT} PUT: {round(probe[0][0], 2)}",
                "{EMO_PUT} PUT: {round(probe[0][1], 2)}",
            ),
            (
                "{EMO_CALL} CALL: {round(probe[0][1], 2)}",
                "{EMO_CALL} CALL: {round(probe[0][0], 2)}",
            ),
            (
                L("    if probe[0][0] > 0.60:",
                  "        do_action('put')",
                  "    elif probe[0][1] > 0.60:",
                  "        do_action('call')"),
                L("    if probe[0][1] > 0.60:",
                  "        do_action('put')",
                  "    elif probe[0][0] > 0.60:",
                  "        do_action('call')"),
            ),
        ],
    ),
]


def main():
    with open(PATH, 'r', newline='') as f:
        src = f.read()
    crlf = '\r\n' in src

    def nl(s):
        return s.replace('\n', '\r\n') if crlf else s

    text = src
    results = []
    failed = False

    for name, why, hunks in PATCHES:
        if name in SKIP:
            results.append((name, 'skipped', why))
            continue
        states = []
        for old, new in hunks:
            old, new = nl(old), nl(new)
            n = text.count(old)
            if n == 1:
                text = text.replace(old, new, 1)
                states.append('applied')
            elif n == 0 and new in text:
                states.append('already')
            else:
                states.append(f'FAILED (old text matched {n}x)')
                failed = True
        if any(s.startswith('FAILED') for s in states):
            status = 'FAILED'
        elif all(s == 'already' for s in states):
            status = 'already applied'
        else:
            status = 'applied'
        results.append((name, status, why, states))

    print(f'target: {PATH}')
    for r in results:
        print(f'  [{r[1]}] {r[0]}')
        if r[1] == 'FAILED':
            for s in r[3]:
                print(f'      hunk: {s}')

    if failed:
        print('\nA hunk did not match - NOTHING was written. '
              'Paste me the section around that code and I will re-anchor it.')
        sys.exit(1)

    if text == src:
        print('\nNothing to write.')
        return

    shutil.copyfile(PATH, PATH + '.bak')
    with open(PATH, 'w', newline='') as f:
        f.write(text)

    print(f'\nWritten. Backup: {PATH}.bak\n\nWhat changed, in plain English:')
    for r in results:
        if r[1] == 'applied':
            print(f'  - {r[0]}: {r[2]}')
    print('\nRestart the bot to pick it up.')


if __name__ == '__main__':
    main()
