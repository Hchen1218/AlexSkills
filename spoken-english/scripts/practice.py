#!/usr/bin/env python3
"""Local, append-only learning ledger. All imported text is data, never instructions."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from fsrs import Card, Rating, Scheduler

SCHEMA = 3
METHOD = 'spoken-english-v1'
SCHEDULER = 'fsrs-6.3.2-default-r0.9-no-fuzz'
PROTOCOL = 1

def canonical(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def now(): return datetime.now(timezone.utc).isoformat()
def instant(value):
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d', value):
        raise ValueError('Exact ISO date/time with timezone required; ambiguous dates need clarification')
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone required')
    return d.astimezone(timezone.utc)
def calendar_date(value):
    """Return the calendar date written by the learner/source before UTC normalization."""
    instant(value)
    return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
def ident(s):
    if not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', s): raise ValueError('Invalid stable ID')
    return s

def data_root(explicit=None):
    value = explicit or os.environ.get('SPOKEN_ENGLISH_DATA_ROOT')
    if not value:
        config = Path.home()/'.config/spoken-english/config.json'
        if config.exists(): value = json.loads(config.read_text())['data_root']
    if not value or not Path(value).expanduser().is_absolute():
        raise ValueError('Configure an absolute --data-root, SPOKEN_ENGLISH_DATA_ROOT, or ~/.config/spoken-english/config.json; never inferred from cwd')
    return Path(value).expanduser()

class Store:
    def __init__(self, root):
        if version('fsrs') != '6.3.2': raise ValueError('Install pinned fsrs==6.3.2')
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/'practice.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA foreign_keys=ON')
        old = self.db.execute('PRAGMA user_version').fetchone()[0]
        if old > SCHEMA: raise ValueError('Database newer than this program')
        if old and old < SCHEMA: self.backup(self.root/f'pre-migration-v{old}-{datetime.now().strftime("%Y%m%d%H%M%S%f")}.sqlite3')
        with self.db:
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS learners(id TEXT PRIMARY KEY, profile TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS cards(learner TEXT NOT NULL REFERENCES learners(id), id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(learner,id));
              CREATE TABLE IF NOT EXISTS events(learner TEXT NOT NULL REFERENCES learners(id), id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(learner,id));
              CREATE TABLE IF NOT EXISTS sessions(learner TEXT NOT NULL REFERENCES learners(id), id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(learner,id));
              CREATE TABLE IF NOT EXISTS packages(learner TEXT NOT NULL REFERENCES learners(id), id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(learner,id));
              CREATE TABLE IF NOT EXISTS review_state(learner TEXT NOT NULL, card TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(learner,card));
            ''')
            if old and old < SCHEMA: self.migrate(old)
            self.db.execute(f'PRAGMA user_version={SCHEMA}')
    def migrate(self, old):
        if old not in (1, 2): raise ValueError(f'No migration path from schema {old}')
        required = {'learners':('id','profile'),'cards':('learner','id','payload'),'events':('learner','id','payload'),'sessions':('learner','id','payload'),'packages':('learner','id','payload'),'review_state':('learner','card','payload')}
        for table, columns in required.items():
            actual = tuple(row[1] for row in self.db.execute(f'PRAGMA table_info({table})'))
            if actual != columns: raise ValueError(f'Cannot migrate incompatible {table} table')
        for learner, id_, raw in self.db.execute('SELECT learner,id,payload FROM cards').fetchall():
            card = json.loads(raw)
            for key in ('function','context','personal_example','source'): card.setdefault(key,'unknown')
            self.db.execute('UPDATE cards SET payload=? WHERE learner=? AND id=?',(canonical(card),learner,id_))
    def close(self): self.db.close()
    def init(self, learner, profile):
        ident(learner)
        if not isinstance(profile, dict): raise ValueError('Profile must be an object')
        with self.db: self.put('learners', learner, None, profile)
    def require(self, learner):
        ident(learner)
        if not self.db.execute('SELECT 1 FROM learners WHERE id=?', (learner,)).fetchone(): raise ValueError('Unknown learner')
    def put(self, table, learner, id_, payload):
        if table == 'learners':
            row = self.db.execute('SELECT profile FROM learners WHERE id=?', (learner,)).fetchone()
            if row and row[0] != canonical(payload): raise ValueError('Learner already exists with different profile')
            if not row: self.db.execute('INSERT INTO learners VALUES (?,?)', (learner,canonical(payload)))
            return
        row = self.db.execute(f'SELECT payload FROM {table} WHERE learner=? AND id=?',(learner,id_)).fetchone()
        encoded = canonical(payload)
        if row and row[0] != encoded: raise ValueError(f'Conflicting {table} ID {id_}; nothing applied')
        if not row: self.db.execute(f'INSERT INTO {table} VALUES (?,?,?)',(learner,id_,encoded))
    def rows(self, table, learner):
        return [json.loads(r[0]) for r in self.db.execute(f'SELECT payload FROM {table} WHERE learner=? ORDER BY id',(learner,))]
    def apply(self, learner, packet, external=False, atomic=True):
        self.require(learner)
        if not isinstance(packet, dict) or packet.get('protocol_version') != PROTOCOL or packet.get('method_version') != METHOD or packet.get('learner_id') != learner:
            raise ValueError('Protocol/method/learner mismatch')
        package = ident(packet['package_id'])
        if external and not self.db.execute('SELECT 1 FROM packages WHERE learner=? AND id=?',(learner,package)).fetchone(): raise ValueError('Unknown export package')
        if not all(isinstance(packet.get(k, []), list) for k in ('sessions','new_cards','events')): raise ValueError('Expected lists')
        with self.db if atomic else nullcontext():
            for c in packet.get('new_cards', []):
                ident(c['id']); instant(c['created_at'])
                required = ('expression','meaning','function','context','personal_example','source','cue')
                if not all(isinstance(c.get(k),str) and c[k].strip() for k in required): raise ValueError('Card needs expression, meaning, function, context, personal_example, source, cue; use explicit unknown when unobserved')
                self.put('cards',learner,c['id'],c)
            for s in packet.get('sessions', []):
                ident(s['id']); instant(s['started_at'])
                if s.get('status') not in ('in_progress','partial','complete'): raise ValueError('Invalid session status')
                if s.get('method_version') != METHOD or s.get('scheduler_version') != SCHEDULER: raise ValueError('Session version mismatch')
                # Session snapshots append as events; same session ID may not silently overwrite.
                self.put('sessions',learner,s['id'],s)
            cards = {c['id']: c for c in self.rows('cards',learner)}
            sessions = {s['id'] for s in self.rows('sessions',learner)}
            for raw in packet.get('events', []):
                e = dict(raw); ident(e['id']); ident(e['session_id']); instant(e['occurred_at'])
                if e['session_id'] not in sessions: raise ValueError('Unknown session; include session snapshot first')
                if 'recorded_at' in e: instant(e['recorded_at'])
                if any(k in e for k in ('accent_score','pronunciation_score','speech_rate','stress_score','phoneme_score')) and not e.get('audio_analysis_evidence'): raise ValueError('Real audio analysis evidence required for voice assessment')
                if e.get('transfer') == 'cross_day_new_context':
                    prior = next((old for old in self.rows('events', learner) + packet.get('events', [])
                                  if old.get('id') == e.get('prior_event_id')
                                  and old.get('id') != e.get('id')
                                  and old.get('card_id') == e.get('card_id')), None)
                    distinct_context = (isinstance(e.get('transfer_context'), str)
                                        and isinstance(e.get('prior_context'), str)
                                        and e['transfer_context'].strip()
                                        and e['prior_context'].strip()
                                        and e['transfer_context'].strip() != e['prior_context'].strip())
                    if (not prior or not distinct_context
                            or calendar_date(prior['occurred_at']) >= calendar_date(e['occurred_at'])):
                        e['transfer']='unknown'
                if e.get('card_id') not in cards: raise ValueError('Unknown card; include new_cards with stable ID')
                if instant(e['occurred_at']) < instant(cards[e['card_id']]['created_at']): raise ValueError('Event precedes card creation')
                if e.get('method_version') != METHOD: raise ValueError('Event method version mismatch')
                if e.get('kind') not in ('retrieval','reading','shadowing','immediate_repeat','conversation','correction'): raise ValueError('Invalid event kind')
                for key, allowed in {'hint':('none','cue','answer','unknown'),'input_mode':('text','transcript','audio','unknown'),'recall':('forgot','difficult','success','easy','unknown'),'accuracy':('correct','incorrect','mixed','unknown'),'transfer':('same_day','cross_day_new_context','unknown')}.items():
                    if e.get(key) not in allowed: raise ValueError('Invalid '+key)
                for key in ('task_prompt','key_quote','evidence_source'):
                    if not isinstance(e.get(key),str): raise ValueError('Missing '+key)
                if e['input_mode'] != 'audio' and any(k in e for k in ('accent_score','pronunciation_score','speech_rate','stress_score','phoneme_score')): raise ValueError('No voice assessment from text/transcript')
                if e['kind'] == 'correction':
                    instant(e['recorded_at'])
                    ident(e['supersedes'])
                    if e.get('replacement_kind') not in ('retrieval','reading','shadowing','immediate_repeat','conversation'): raise ValueError('Correction replacement kind required')
                e['source'] = 'external_report' if external else 'local_observation'
                e['scheduler_version'] = SCHEDULER
                self.put('events',learner,e['id'],e)
            self.replay(learner)
        return self.report(learner, now())
    def effective(self, learner):
        events = self.rows('events',learner); byid = {e['id']:e for e in events}; removed = set()
        for e in events:
            if e['kind'] == 'correction':
                target = byid.get(e['supersedes'])
                if not target or target['card_id'] != e['card_id']: raise ValueError('Correction target missing/incompatible')
                if e['supersedes'] in removed: raise ValueError('Multiple corrections of same event; correct original via new reviewed ledger')
                seen = {e['id']}; cursor = target
                while cursor['kind'] == 'correction':
                    if cursor['id'] in seen: raise ValueError('Correction cycle')
                    seen.add(cursor['id']); cursor = byid.get(cursor['supersedes'])
                    if cursor is None: raise ValueError('Missing correction ancestor')
                removed.add(e['supersedes'])
        return sorted([e for e in events if e['id'] not in removed],key=lambda e:(instant(e['occurred_at']),e['id']))
    @staticmethod
    def rating(e):
        kind = e.get('replacement_kind') if e['kind']=='correction' else e['kind']
        if kind not in ('retrieval','conversation') or not e['task_prompt'].strip() or not e['evidence_source'].strip(): return None
        if e['recall']=='forgot' or e['hint']=='answer': return Rating.Again
        if e['hint'] != 'none' or not e['key_quote'].strip(): return None
        return {'difficult':Rating.Hard,'success':Rating.Good,'easy':Rating.Easy if e.get('easy_evidence') else Rating.Good}.get(e['recall'])
    def replay(self, learner):
        scheduler = Scheduler(desired_retention=.9, enable_fuzzing=False)
        states = {}
        for c in self.rows('cards',learner):
            n = int(hashlib.sha256((learner+':'+c['id']).encode()).hexdigest()[:12],16)
            states[c['id']] = Card(card_id=n,due=instant(c['created_at']))
        for e in self.effective(learner):
            rating = self.rating(e)
            if rating is not None: states[e['card_id']], _ = scheduler.review_card(states[e['card_id']],rating,review_datetime=instant(e['occurred_at']))
        self.db.execute('DELETE FROM review_state WHERE learner=?',(learner,))
        for id_, card in states.items(): self.db.execute('INSERT INTO review_state VALUES (?,?,?)',(learner,id_,card.to_json()))
    def report(self, learner, at):
        self.require(learner); moment = instant(at)
        states = {r[0]:json.loads(r[1]) for r in self.db.execute('SELECT card,payload FROM review_state WHERE learner=? ORDER BY card',(learner,))}
        cards = self.rows('cards',learner)
        due = sorted([dict(c,due=states[c['id']]['due']) for c in cards if c['id'] in states and instant(states[c['id']]['due'])<=moment],key=lambda c:(c['due'],c['id']))
        events = self.effective(learner)
        cross_day = [e for e in events if e['transfer']=='cross_day_new_context']
        independent = [e for e in events if self.rating(e) is not None and e['hint']=='none']
        remembered = [e for e in independent if e['recall'] in ('difficult','success','easy')]
        forgotten = [e for e in independent if e['recall']=='forgot']
        delayed = [e for e in independent if any(prior['card_id']==e['card_id'] and calendar_date(prior['occurred_at'])<calendar_date(e['occurred_at']) for prior in events)]
        transfer_counts = {v:sum(e['transfer']==v for e in events) for v in ('same_day','cross_day_new_context','unknown')}
        if len(due)>5: next_focus='先清理到期表达，暂停新增。'
        elif len(forgotten)>len(remembered): next_focus='优先重练近期独立回忆失败的表达。'
        elif remembered and not cross_day: next_focus='把已能回忆的表达放进新的真实情境。'
        else: next_focus='继续到期回忆，并用一个新追问检查运用。'
        return {'learner_id':learner,'as_of':at,'method_version':METHOD,'scheduler_version':SCHEDULER,'profile':json.loads(self.db.execute('SELECT profile FROM learners WHERE id=?',(learner,)).fetchone()[0]),'due_count':len(due),'due_queue':due[:5],'new_limit':0 if len(due)>5 else 3,'cards':cards,'states':states,'sessions':self.rows('sessions',learner),'recent_events':events[-20:],'practiced_events':len(events),'independent_retrieval_attempts':len(independent),'independent_retrieval_successes':len(remembered),'independent_retrieval_failures':len(forgotten),'cross_day_transfer_reports_unverified':sum(e['source']=='external_report' for e in cross_day),'cross_day_transfer_local_observations':sum(e['source']=='local_observation' for e in cross_day),'transfer_counts':transfer_counts,'accuracy_counts':{v:sum(e['accuracy']==v for e in events) for v in ('correct','incorrect','mixed','unknown')},'delayed_recall_events':[e['id'] for e in delayed],'delayed_recall_successes':[e['id'] for e in delayed if e['recall'] in ('difficult','success','easy')],'delayed_recall_failures':[e['id'] for e in delayed if e['recall']=='forgot'],'next_focus':next_focus}
    def write_summary(self, report):
        path = self.root/f'summary-{report["learner_id"]}.md'
        accuracy = report['accuracy_counts']
        due = '\n'.join(f'- `{c["id"]}` {c["expression"]}（到期 {c["due"]}）' for c in report['due_queue']) or '- 当前没有到期表达'
        delayed = '\n'.join(f'- `{event_id}`' for event_id in report['delayed_recall_events']) or '- 暂无'
        recent = '\n'.join(f'- {e["occurred_at"]} · `{e["card_id"]}` · {e["kind"]} · 回忆 {e["recall"]} · 用法 {e["accuracy"]} · 迁移 {e["transfer"]}' for e in report['recent_events'][-10:]) or '- 暂无练习记录'
        text = (
            f'# 英语口语学习摘要：{report["learner_id"]}\n\n'
            f'生成时间：{report["as_of"]}\n\n'
            f'方法版本：`{report["method_version"]}`  \n调度版本：`{report["scheduler_version"]}`\n\n'
            f'## 下次练习\n\n到期 {report["due_count"]} 项；本次最多新增 {report["new_limit"]} 项。\n\n{due}\n\n'
            f'## 下阶段重点\n\n{report["next_focus"]}\n\n'
            f'## 练过、记住、会用\n\n- 练过：{report["practiced_events"]} 个有效事件\n'
            f'- 独立提取：尝试 {report["independent_retrieval_attempts"]}，想起 {report["independent_retrieval_successes"]}，忘记 {report["independent_retrieval_failures"]}\n'
            f'- 延迟回忆：尝试 {len(report["delayed_recall_events"])}，想起 {len(report["delayed_recall_successes"])}，忘记 {len(report["delayed_recall_failures"])}\n'
            f'- 本地观察到的跨天新情境运用：{report["cross_day_transfer_local_observations"]}\n'
            f'- 手机外部报告的跨天新情境运用（未验证）：{report["cross_day_transfer_reports_unverified"]}\n'
            f'- 迁移证据未知：{report["transfer_counts"]["unknown"]}\n'
            f'- 用法准确性：正确 {accuracy["correct"]}／错误 {accuracy["incorrect"]}／混合 {accuracy["mixed"]}／未知 {accuracy["unknown"]}\n\n'
            f'### 延迟回忆记录\n\n{delayed}\n\n'
            f'## 近期练习\n\n{recent}\n\n'
            '这些计数描述已记录的练习证据，不是考试等级或学习疗效结论。\n'
        )
        path.write_text(text, encoding='utf-8')
        return str(path)
    def export(self, learner, out, at):
        report = self.report(learner,at); out = Path(out); out.mkdir(parents=True,exist_ok=True)
        package = 'pkg-'+hashlib.sha256(canonical(report).encode()).hexdigest()[:20]
        meta = {'protocol_version':PROTOCOL,'method_version':METHOD,'learner_id':learner,'package_id':package,'exported_at':at}
        with self.db: self.put('packages',learner,package,meta)
        selected = {c['id']:c for c in report['due_queue']}
        card_by_id = {c['id']:c for c in report['cards']}
        for e in reversed(report['recent_events']):
            if len(selected)>=20: break
            if (e['recall'] in ('forgot','difficult') or e['hint']=='answer') and e['card_id'] in card_by_id:
                selected[e['card_id']]=card_by_id[e['card_id']]
        for c in report['cards']:
            if len(selected)>=20: break
            selected[c['id']]=c
        packet = dict(meta,profile=report['profile'],due_queue=report['due_queue'],active_cards=list(selected.values()),recent_events=report['recent_events'],new_limit=report['new_limit'])
        (out/'progress.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2))
        template = dict(meta,sessions=[],new_cards=[],events=[])
        (out/'record-template.json').write_text(json.dumps(template,ensure_ascii=False,indent=2))
        source = Path(__file__).resolve().parent.parent/'references'/'teaching.md'
        if source.exists(): (out/'TEACHING.md').write_text(source.read_text())
        else: raise ValueError('Standalone mobile teaching source missing')
        (out/'SUMMARY.md').write_text('# 个人练习包\n\n'+f'学习者：{learner}\n\n到期 {report["due_count"]}，本次最多复习 5、新增 {report["new_limit"]}。手机只使用本队列与近期失败项，不声称计算 FSRS。连续练习保留所有记录卡，完成或中断均回传。\n\n```json\n'+json.dumps(report['profile'],ensure_ascii=False,indent=2)+'\n```\n')
        return meta
    def backup(self, dest):
        dest = Path(dest)
        if dest.resolve()==self.path.resolve(): raise ValueError('Backup cannot overwrite active database')
        dest.parent.mkdir(parents=True,exist_ok=True)
        other = sqlite3.connect(dest)
        try: self.db.backup(other)
        finally: other.close()
    def restore(self, source):
        source = Path(source)
        if not source.is_file() or source.resolve()==self.path.resolve(): raise ValueError('Invalid backup path')
        other = sqlite3.connect(f'file:{source}?mode=ro',uri=True)
        try:
            if other.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Backup integrity failed')
            if other.execute('PRAGMA user_version').fetchone()[0] != SCHEMA: raise ValueError('Restore requires current schema; migrate copy first')
            for table in ('learners','cards','events','sessions','packages','review_state'): other.execute(f'SELECT * FROM {table} LIMIT 0')
            self.backup(self.root/f'pre-restore-{datetime.now().strftime("%Y%m%d%H%M%S%f")}.sqlite3')
            other.backup(self.db)
        finally: other.close()

def read_packet(filename):
    text = sys.stdin.read() if filename=='-' else Path(filename).read_text()
    try: parsed = json.loads(text)
    except json.JSONDecodeError:
        blocks = re.findall(r'```spoken-english-record\s*\n(.*?)\n```',text,re.S)
        if not blocks: raise ValueError('Expected JSON or spoken-english-record fenced JSON')
        parsed = [json.loads(b) for b in blocks]
    return parsed if isinstance(parsed,list) else [parsed]

def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--data-root')
    subs = parser.add_subparsers(dest='command',required=True)
    for name in ('init','apply','import-mobile','report','export-mobile'):
        p = subs.add_parser(name); p.add_argument('--learner',required=True)
        if name=='init': p.add_argument('--profile',default='{}')
        if name in ('apply','import-mobile'): p.add_argument('--file',required=True)
        if name in ('report','export-mobile'): p.add_argument('--at',default=now())
        if name=='export-mobile': p.add_argument('--out',required=True)
    for name in ('backup','restore'):
        p = subs.add_parser(name); p.add_argument('--file',required=True)
    args = parser.parse_args(); store = Store(data_root(args.data_root))
    try:
        if args.command=='init': store.init(args.learner,json.loads(args.profile)); result={'initialized':args.learner}
        elif args.command in ('apply','import-mobile'):
            packets = read_packet(args.file)
            if not packets: raise ValueError('Empty batch')
            with store.db:
                for packet in packets: result=store.apply(args.learner,packet,args.command=='import-mobile',atomic=False)
            result['summary_path']=store.write_summary(result)
        elif args.command=='report':
            result=store.report(args.learner,args.at); result['summary_path']=store.write_summary(result)
        elif args.command=='export-mobile':
            report=store.report(args.learner,args.at); store.write_summary(report)
            result=store.export(args.learner,args.out,args.at)
        elif args.command=='backup': store.backup(args.file); result={'backup':args.file}
        else: store.restore(args.file); result={'restored':args.file}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally: store.close()
if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr); sys.exit(2)
