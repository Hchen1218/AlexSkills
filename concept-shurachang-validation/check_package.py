"""Check only this deliverable; standard-library-only, no network or rewriting."""
from pathlib import Path
import hashlib
import json
import re
import sys

root = Path(__file__).resolve().parent.parent / 'concept-shurachang'
allowed = {'SKILL.md', 'agents/openai.yaml', 'references/method.md', 'references/cases.md'}
files = {p.relative_to(root).as_posix(): p for p in root.rglob('*') if p.is_file()}
errors = []
if set(files) != allowed:
    errors.append('Unexpected or missing package files: ' + repr(set(files) ^ allowed))
for name, path in files.items():
    if path.is_symlink():
        errors.append(f'{name}: symlink is not self-contained')
    content = path.read_text()
    for marker in ('/Users/', '/private/', 'ai-content/', 'TODO', 'TBD', 'app://', 'thread://'):
        if marker in content:
            errors.append(f'{name}: private dependency or placeholder: {marker}')
    for target in re.findall(r'\]\(([^)]+)\)', content):
        if target.startswith(('https://', '#')):
            continue
        resolved = (path.parent / target.split('#')[0]).resolve()
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            errors.append(f'{name}: missing or escaping reference: {target}')
entry = files.get('SKILL.md')
if entry:
    text = entry.read_text()
    if not text.startswith('---\nname: concept-shurachang\n'):
        errors.append('Entrypoint naming/frontmatter mismatch')
ui = files.get('agents/openai.yaml')
if ui and '$concept-shurachang' not in ui.read_text():
    errors.append('UI invocation does not name the Skill')
print(json.dumps({
    'status': 'PASS' if not errors else 'FAIL',
    'checks': ['package allowlist', 'no local dependencies/placeholders', 'relative references', 'entry and UI invocation'],
    'files': {name: {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in sorted(files.items())},
    'errors': errors,
}, ensure_ascii=False, indent=2))
sys.exit(bool(errors))
