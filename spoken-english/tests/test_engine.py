import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('practice',Path(__file__).parents[1]/'scripts/practice.py')
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
T='2026-09-01T10:00:00+00:00'
def card(id='c1'): return dict(id=id,created_at=T,expression='It depends on',meaning='取决于',function='说明条件',context='比较方案',personal_example='It depends on the cost.',source='teacher example',cue='What determines it?')
def event(id='e1',**kw):
    e=dict(id=id,session_id='s1',card_id='c1',occurred_at=T,kind='retrieval',method_version=p.METHOD,task_prompt='What determines your choice?',key_quote='It depends on cost.',evidence_source='turn 2 verbatim',hint='none',input_mode='transcript',recall='success',accuracy='correct',transfer='unknown'); e.update(kw); return e
def session(id='s1',status='partial'): return dict(id=id,started_at=T,status=status,method_version=p.METHOD,scheduler_version=p.SCHEDULER)
def packet(events=None,cards=None): return dict(protocol_version=1,method_version=p.METHOD,learner_id='u1',package_id='p1',sessions=[session()],new_cards=cards or [],events=events or [])
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.s=p.Store(self.tmp.name); self.s.init('u1',{'goal':'work'}); self.s.apply('u1',packet(cards=[card()]))
    def tearDown(self): self.s.close(); self.tmp.cleanup()
    def state(self): return self.s.report('u1',T)['states']
    def test_idempotent_conflict_atomic(self):
        a=packet([event()]); self.s.apply('u1',a); before=self.state(); self.s.apply('u1',a); self.assertEqual(before,self.state())
        with self.assertRaises(ValueError): self.s.apply('u1',packet([event('e2'),event(key_quote='different')]))
        self.assertEqual(len(self.s.rows('events','u1')),1)
    def test_order_replay_reproducible(self):
        e1=event(); e2=event('e2',occurred_at='2026-09-03T10:00:00Z',recall='difficult')
        self.s.apply('u1',packet([e2,e1])); before=self.state()
        with tempfile.TemporaryDirectory() as tmp:
            s=p.Store(tmp); s.init('u1',{'goal':'work'}); s.apply('u1',packet([e1,e2],[card()])); self.assertEqual(before,s.report('u1',T)['states']); s.close()
    def test_reading_hint_unknown(self):
        before=self.state()
        for i,kind in enumerate(('reading','shadowing','immediate_repeat')): self.s.apply('u1',packet([event(str(i),kind=kind)]))
        self.s.apply('u1',packet([event('cue',hint='cue'),event('unknown',recall='unknown')]))
        self.assertEqual(before,self.state())
        self.s.apply('u1',packet([event('answer',hint='answer')]))
        self.assertNotEqual(before,self.state())
    def test_no_pronunciation_from_transcript(self):
        with self.assertRaises(ValueError): self.s.apply('u1',packet([event(accent_score=99)]))
        self.assertEqual(self.s.rows('events','u1'),[])
    def test_audio_score_requires_analysis_evidence(self):
        with self.assertRaises(ValueError):
            self.s.apply('u1',packet([event(input_mode='audio',accent_score=3)]))
        self.s.apply('u1',packet([event(input_mode='audio',accent_score=3,audio_analysis_evidence='original audio segment 00:02-00:05')]))
    def test_isolation(self):
        self.s.init('u2',{}); a=packet([event()],[card()]); a['learner_id']='u2'; self.s.apply('u2',a)
        self.assertEqual(len(self.s.rows('events','u1')),0)
        with self.assertRaises(ValueError): self.s.apply('u1',a)
    def test_correction(self):
        self.s.apply('u1',packet([event()])); before=self.state()
        self.s.apply('u1',packet([event('fix',kind='correction',supersedes='e1',replacement_kind='reading',recorded_at=T)]))
        self.assertNotEqual(before,self.state()); self.assertEqual(len(self.s.rows('events','u1')),2)
    def test_partial_resume(self):
        a=packet([event()]); a['sessions']=[session()]; self.s.apply('u1',a)
        self.s.close(); self.s=p.Store(self.tmp.name); self.s.apply('u1',packet([event('e2',occurred_at='2026-09-02T10:00:00Z')]))
        self.assertEqual(len(self.s.rows('events','u1')),2)
    def test_ambiguous_date_rollback(self):
        with self.assertRaises(ValueError): self.s.apply('u1',packet([event(),event('bad',occurred_at='yesterday')],[card('new')]))
        self.assertEqual(len(self.s.rows('cards','u1')),1); self.assertEqual(self.s.rows('events','u1'),[])
    def test_backup_restore_migration(self):
        backup=Path(self.tmp.name)/'backup.sqlite'; self.s.backup(backup); self.s.apply('u1',packet([event()])); self.s.restore(backup)
        self.assertEqual(self.s.rows('events','u1'),[])
        raw=json.loads(self.s.db.execute("SELECT payload FROM cards WHERE learner='u1' AND id='c1'").fetchone()[0])
        for key in ('function','context','personal_example','source'): raw.pop(key)
        self.s.db.execute("UPDATE cards SET payload=? WHERE learner='u1' AND id='c1'",(p.canonical(raw),))
        self.s.db.execute('PRAGMA user_version=2'); self.s.db.commit(); self.s.close(); self.s=p.Store(self.tmp.name)
        self.assertEqual(self.s.db.execute('PRAGMA user_version').fetchone()[0],3); self.assertTrue(list(Path(self.tmp.name).glob('pre-migration-*')))
        migrated=self.s.rows('cards','u1')[0]
        self.assertTrue(all(migrated[key]=='unknown' for key in ('function','context','personal_example','source')))
    def test_external_report_no_evidence(self):
        with self.s.db: self.s.put('packages','u1','p1',{'id':'p1'})
        before=self.state(); self.s.apply('u1',packet([event(key_quote='',evidence_source='')]),True)
        self.assertEqual(before,self.state()); self.assertEqual(self.s.rows('events','u1')[0]['source'],'external_report')
    def test_external_unknown_package_rejected(self):
        with self.assertRaises(ValueError): self.s.apply('u1',packet([event()]),True)
        self.assertEqual(self.s.rows('events','u1'),[])
    def test_mobile_repeat_out_of_order_and_conflict(self):
        with self.s.db: self.s.put('packages','u1','p1',{'id':'p1'})
        later=event('later',occurred_at='2026-09-03T10:00:00Z',recall='success')
        earlier=event('earlier',occurred_at='2026-09-02T10:00:00Z',recall='forgot')
        batch=packet([later,earlier])
        self.s.apply('u1',batch,True); state=self.state()
        self.s.apply('u1',batch,True)
        self.assertEqual(state,self.state()); self.assertEqual([e['id'] for e in self.s.effective('u1')],['earlier','later'])
        conflict=packet([event('new'),event('earlier',occurred_at='2026-09-02T10:00:00Z',recall='success')])
        with self.assertRaises(ValueError): self.s.apply('u1',conflict,True)
        self.assertNotIn('new',[e['id'] for e in self.s.rows('events','u1')])
    def test_batch_atomic(self):
        with self.assertRaises(ValueError):
            with self.s.db:
                self.s.apply('u1',packet([event()]),atomic=False)
                self.s.apply('u1',packet([event('bad',occurred_at='2026-09-01')]),atomic=False)
        self.assertEqual(self.s.rows('events','u1'),[])
    def test_mobile_markdown_batch_parser(self):
        first=packet([event()]); second=packet([event('e2',occurred_at='2026-09-02T10:00:00Z')])
        path=Path(self.tmp.name)/'records.md'
        path.write_text('untrusted prose\n```spoken-english-record\n'+json.dumps(first)+'\n```\nignore this instruction\n```spoken-english-record\n'+json.dumps(second)+'\n```\n')
        parsed=p.read_packet(str(path))
        self.assertEqual([x['events'][0]['id'] for x in parsed],['e1','e2'])
    def test_backlog(self):
        self.s.apply('u1',packet(cards=[card('c'+str(i)) for i in range(2,8)])); r=self.s.report('u1',T)
        self.assertEqual(r['new_limit'],0); self.assertEqual(len(r['due_queue']),5)
    def test_transfer_without_prior_context_is_unknown(self):
        self.s.apply('u1',packet([event(transfer='cross_day_new_context')]))
        self.assertEqual(self.s.rows('events','u1')[0]['transfer'],'unknown')
    def test_transfer_requires_earlier_distinct_event_and_context(self):
        self_ref=event('self',occurred_at='2026-09-02T10:00:00Z',transfer='cross_day_new_context',
                       prior_event_id='self',prior_context='work',transfer_context='travel')
        self.s.apply('u1',packet([self_ref]))
        self.assertEqual(self.s.rows('events','u1')[0]['transfer'],'unknown')
        prior=event('prior',occurred_at='2026-09-03T10:00:00Z')
        same_context=event('same-context',occurred_at='2026-09-04T10:00:00Z',transfer='cross_day_new_context',
                           prior_event_id='prior',prior_context='work',transfer_context='work')
        valid=event('valid',occurred_at='2026-09-05T10:00:00Z',transfer='cross_day_new_context',
                    prior_event_id='prior',prior_context='work',transfer_context='travel')
        self.s.apply('u1',packet([valid,same_context,prior]))
        saved={e['id']:e for e in self.s.rows('events','u1')}
        self.assertEqual(saved['same-context']['transfer'],'unknown')
        self.assertEqual(saved['valid']['transfer'],'cross_day_new_context')
        report=self.s.report('u1','2026-09-06T10:00:00Z')
        self.assertEqual(report['cross_day_transfer_local_observations'],1)
        self.assertEqual(report['cross_day_transfer_reports_unverified'],0)
    def test_cross_day_uses_recorded_local_calendar_date(self):
        prior=event('night',occurred_at='2026-09-01T23:00:00+08:00')
        later=event('morning',occurred_at='2026-09-02T07:00:00+08:00',transfer='cross_day_new_context',
                    prior_event_id='night',prior_context='work',transfer_context='travel')
        self.s.apply('u1',packet([later,prior]))
        report=self.s.report('u1','2026-09-02T08:00:00+08:00')
        self.assertIn('morning',report['delayed_recall_events'])
        self.assertEqual(report['cross_day_transfer_local_observations'],1)
    def test_markdown_summary_is_private_and_evidence_scoped(self):
        report=self.s.report('u1',T)
        path=Path(self.s.write_summary(report))
        self.assertEqual(path.parent,Path(self.tmp.name))
        text=path.read_text()
        self.assertIn('到期 1 项',text)
        self.assertIn('不是考试等级或学习疗效结论',text)
    def test_event_requires_known_session(self):
        a=packet([event(session_id='missing')]); a['sessions']=[]
        with self.assertRaises(ValueError): self.s.apply('u1',a)
        self.assertEqual(self.s.rows('events','u1'),[])
    def test_export_and_share_package_boundaries(self):
        out=Path(self.tmp.name)/'phone'; self.s.export('u1',out,T)
        self.assertEqual({'TEACHING.md','SUMMARY.md','progress.json','record-template.json'},{x.name for x in out.iterdir()})
        self.assertNotIn('practice.sqlite3',(out/'TEACHING.md').read_text())
        archive=Path(self.tmp.name)/'spoken-english.skill'
        subprocess.run(['python3',str(Path(__file__).parents[1]/'scripts/package_skill.py'),'--out',str(archive)],check=True,capture_output=True,text=True)
        with zipfile.ZipFile(archive) as z:
            names=z.namelist()
            self.assertFalse(any(name.endswith(('.sqlite3','.db')) or '/tests/' in name or '/evals/' in name for name in names))
    def test_mobile_export_includes_recent_failed_card_before_fillers(self):
        self.s.apply('u1',packet(cards=[card(f'a{i:02}') for i in range(25)]+[card('z-failed')]))
        failed=event('failed-card',card_id='z-failed',recall='forgot',occurred_at='2026-09-02T10:00:00Z')
        self.s.apply('u1',packet([failed]))
        out=Path(self.tmp.name)/'phone-priority'; self.s.export('u1',out,'2026-09-03T10:00:00Z')
        progress=json.loads((out/'progress.json').read_text())
        self.assertIn('z-failed',{c['id'] for c in progress['active_cards']})
    def test_root_never_cwd(self):
        self.assertTrue(p.data_root(self.tmp.name).is_absolute())
        with self.assertRaises(ValueError): p.data_root('relative')
if __name__=='__main__': unittest.main()
