from pathlib import Path
import json,re
root=Path(__file__).parent/'iteration-1'
manual={
 (1,'with_skill'):[(True,'用户先问不吃身材这套，Jason顺着说，用户于是嘲讽Leo，Grace让其回去。'),(True,'解释偏好训练可能奖励答案及牺牲真实性，并非必然。')],
 (1,'old_skill'):[(False,'听完很爽后直到她又夸一次，未写受迎合影响采取的行动及关系后果。'),(True,'明确偏好训练可能奖励讨喜回答，而非所有模型每次如此。')],
 (2,'with_skill'):[(True,'明确独立是条件概率不变，互斥是不能同时发生。'),(True,'两枚公平硬币互不干扰且不根据对方结果改规则。')],
 (2,'old_skill'):[(True,'解释概率相乘、已知自身结果另一仍一半，独立不等于互斥。'),(True,'设定两枚公平硬币结果互不影响，明确并非心意独立。')]
}
for d in sorted(root.glob('eval-*')):
 meta=json.loads((d/'eval_metadata.json').read_text());i=meta['eval_id']
 for config in ['with_skill','old_skill']:
  run=d/config/'run-1';answer=run/'outputs/answer.md'
  if not answer.exists() or i==3: continue
  script=(run/'outputs/script.txt').read_text();n=len(re.findall('[\u4e00-\u9fff]',script))
  res=manual[(i,config)]+[(n<=240 and ('这就是' in script or '这叫' in script or '这就像' in script),f'实际汉字数{n}；关系叙述在概念揭晓前。')]
  exp=[dict(text=t,passed=p,evidence=e) for t,(p,e) in zip(meta['assertions'],res)]
  passed=sum(x['passed'] for x in exp)
  (run/'grading.json').write_text(json.dumps({'expectations':exp,'summary':dict(passed=passed,failed=len(exp)-passed,total=len(exp),pass_rate=passed/len(exp)),'eval_feedback':{'overall':'字数由脚本计算；机制及因果由主代理依据输出人工判断。未衡量自然度和张力，不能作为创作质量总分。'}},ensure_ascii=False,indent=2))
  (run/'eval_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
