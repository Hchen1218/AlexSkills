#!/usr/bin/env python3
"""Build a shareable allowlisted archive; never bundle learner data or eval runs."""
from pathlib import Path
import argparse, hashlib, zipfile
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--out',required=True);args=p.parse_args()
out=Path(args.out).expanduser().resolve();out.parent.mkdir(parents=True,exist_ok=True)
files=[root/'SKILL.md',root/'README.md',root/'requirements.txt']
for directory in ('references','mobile','scripts'):
    files.extend(p for p in (root/directory).rglob('*') if p.is_file() and p.suffix in ('.md','.py','.json') and '__pycache__' not in p.parts)
for f in files:
    if f.is_symlink(): raise SystemExit('Refusing symlink in package: '+str(f))
    if f.name.endswith(('.sqlite3','.db')): raise SystemExit('Private database in package')
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(files): z.write(f,'spoken-english/'+str(f.relative_to(root)))
print(str(out));print('sha256 '+hashlib.sha256(out.read_bytes()).hexdigest());print(str(len(files))+' allowlisted files; no learner data or eval transcripts')
