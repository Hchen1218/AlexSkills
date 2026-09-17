#!/usr/bin/env python3
"""Build the standalone phone entry from the canonical teaching text."""
from pathlib import Path
import argparse
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
source=(root/'references/teaching.md').read_bytes()
dest=root/'mobile/START-HERE.md'
if args.check:
    if not dest.exists() or dest.read_bytes()!=source: raise SystemExit('Mobile teaching is stale; run sync_mobile.py')
else:
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(source)
print('Mobile teaching matches canonical source')
