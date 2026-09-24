#!/usr/bin/env python3
"""Merge deqp-runner results.csv files per arm and compare arms.

usage: compare.py --a LABEL=dir1,dir2,... --b LABEL=dir1,... [--fails fails.txt]
Prints tests whose status differs between arms, and each arm's tests that
are not Pass/Skip/ExpectedFail (i.e. what a baseline update would need).
"""
import argparse, csv, os, sys

def load(dirs):
    res = {}
    for d in dirs:
        with open(os.path.join(d, 'results.csv')) as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    res[row[0]] = row[1]
    return res

ap = argparse.ArgumentParser()
ap.add_argument('--a', required=True)
ap.add_argument('--b')
ap.add_argument('--fails')
a = ap.parse_args()
la, da = a.a.split('=', 1)
A = load(da.split(','))
base = {}
if a.fails:
    for line in open(a.fails):
        line = line.strip()
        if line and not line.startswith('#') and ',' in line:
            n, s = line.rsplit(',', 1)
            base[n] = s
bad = {'Fail', 'Crash', 'Timeout', 'UnexpectedPass', 'Flake', 'UnexpectedImprovement(Pass)',
       'UnexpectedImprovement(Fail)', 'UnexpectedImprovement(Skip)'}
def summarize(label, R):
    from collections import Counter
    c = Counter(R.values())
    print(f'== {label}: {len(R)} results: ' + ', '.join(f'{k} {v}' for k, v in c.most_common()))
    for n, s in sorted(R.items()):
        if s in bad or (s == 'Pass' and n in base) :
            print(f'   {label} {s:14s} {n}' + (f'   [baseline {base[n]}]' if n in base else ''))
summarize(la, A)
if a.b:
    lb, db = a.b.split('=', 1)
    B = load(db.split(','))
    summarize(lb, B)
    common = set(A) & set(B)
    diff = sorted(n for n in common if A[n] != B[n])
    print(f'== differing between {la} and {lb} ({len(common)} common tests): {len(diff)}')
    for n in diff:
        print(f'   {n}: {la}={A[n]} {lb}={B[n]}')
