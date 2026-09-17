from pathlib import Path
import json,re
root=Path(__file__).resolve().parent.parent/'concept-shurachang'
checks=[]
for p in root.rglob('*.md'):
 s=p.read_text()
 for url in re.findall(r'\]\(([^)]+)\)',s):
  if url.startswith(('https:','http:','#')): continue
  target=(p.parent/url.split('#')[0])
  checks.append({'check':f'{p.relative_to(root)} -> {url}','passed':target.exists()})
 checks.append({'check':f'{p.relative_to(root)} 无个人绝对路径','passed':'/Users/' not in s})
checks.append({'check':'SKILL.md 不超过500行','passed':len((root/'SKILL.md').read_text().splitlines())<500})
for f in ['originals.md','templates.md','voice.md','source-notes.md']:
 checks.append({'check':f'必要资源 {f}','passed':(root/'references'/f).exists()})
p=Path(__file__).parent/'structure-check.json';p.write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print(json.dumps({'checks':len(checks),'failed':[x for x in checks if not x['passed']]},ensure_ascii=False))
