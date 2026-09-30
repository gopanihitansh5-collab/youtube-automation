import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import unittest

p = Path(__file__).resolve().parents[1] / 'src' / 'episode_queue.py'
spec = importlib.util.spec_from_file_location('eq', p)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
NOW = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)


class QueueTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(zip(q.BASE_HEADERS, ['', '', '', '', '', '', '', '', '', '']))
        row.update(topic='Example topic', voice='af_heart', privacy='public', status='ready_to_publish',
                   episode_id='ep2', type='short', publish_at='2026-10-02T05:30:00+05:30',
                   timezone='Asia/Calcutta', manifest_ref='DriveFile123', manifest_sha256='a'*64, master_sha256='b'*64)
        row.update(changes)
        return row

    def values(self, *rows):
        h = list(q.BASE_HEADERS + q.MANAGED_HEADERS)
        return [h] + [[r.get(k, '') for k in h] for r in rows]

    def test_old_schema_done_is_inert(self):
        self.assertIsNone(q.select_episode([list(q.BASE_HEADERS), ['old','','','done']], NOW))

    def test_due_selected_exactly(self):
        item=q.select_episode(self.values(self.row()),NOW)
        self.assertEqual((item['episode_id'],item['row_idx']),('ep2',2))

    def test_future_inert(self):
        self.assertIsNone(q.select_episode(self.values(self.row(publish_at='2026-10-02T05:30:01+05:30')),NOW))

    def test_hold_no_master_is_inert(self):
        self.assertIsNone(q.select_episode(self.values(self.row(status='awaiting_master',manifest_ref='',master_sha256='')),NOW))

    def test_duplicate_ids_block(self):
        with self.assertRaises(q.QueueBlocked):q.select_episode(self.values(self.row(),self.row()),NOW)

    def test_date_and_parameter_failures(self):
        for changes in ({'publish_at':'2026-10-02'}, {'publish_at':'2026-10-02T05:30:00Z'},
                        {'timezone':'UTC'}, {'privacy':'private'}, {'voice':'other'},
                        {'manifest_sha256':'bad'}, {'manifest_ref':'https://external.invalid/file'},
                        {'type':'long'}, {'status':'pending'}, {'status':'uploading'}):
            with self.subTest(changes=changes), self.assertRaises(q.QueueBlocked):
                q.select_episode(self.values(self.row(**changes)),NOW)

    def test_unmanaged_pending_blocks(self):
        with self.assertRaises(q.QueueBlocked):q.select_episode(self.values(self.row(episode_id='',status='pending')),NOW)

    def test_duplicate_header_blocks(self):
        values=self.values(self.row());values[0].append('topic')
        with self.assertRaises(q.QueueBlocked):q.select_episode(values,NOW)

    def test_blank_clock_blocks(self):
        with self.assertRaises(q.QueueBlocked):q.select_episode(self.values(self.row()),datetime(2026,10,2))

    def manifest(self,row):
        return {k:row[k] for k in ('episode_id','topic','publish_at','timezone','master_sha256')} | {
            'channel_id':'verified_channel','privacy':'public','voice':'af_heart','master_ref':'DriveMaster123',
            'metadata':{'title':'Example','description':'Example description','tags':['example']},
            'source_evidence':['verified-source-reference'], 'owner_evidence':['private-approved-grant-ref'],
            'qc':{'frames_inspected':True,'audio_inspected':True,'real_generated_motion':True,
                  'facts_checked':True,'final_cut_checked':True,'duration_seconds':20,'master_sha256':row['master_sha256']}}

    def bind(self,manifest,row):
        raw=json.dumps(manifest).encode();row['manifest_sha256']=hashlib.sha256(raw).hexdigest();return raw

    def test_manifest_binding(self):
        row=self.row();m=self.manifest(row);raw=self.bind(m,row)
        self.assertEqual(q.verify_manifest(raw,row,'verified_channel',['private-approved-grant-ref']),m)
        with self.assertRaises(q.QueueBlocked):q.verify_manifest(raw,row,'other',['private-approved-grant-ref'])
        with self.assertRaises(q.QueueBlocked):q.verify_manifest(raw,row,'verified_channel',[])
        with self.assertRaises(q.QueueBlocked):q.verify_manifest(raw+b' ',row,'verified_channel',['private-approved-grant-ref'])

    def test_manifest_qc_and_owner_failures(self):
        for change in ('qc','owner','motion','duration','master','topic'):
            row=self.row();m=self.manifest(row)
            if change=='qc':m['qc']['frames_inspected']=False
            if change=='owner':m['owner_evidence']=[]
            if change=='motion':m['qc']['real_generated_motion']=False
            if change=='duration':m['qc']['duration_seconds']=31
            if change=='master':m['qc']['master_sha256']='c'*64
            if change=='topic':m['topic']='different'
            with self.subTest(change=change),self.assertRaises(q.QueueBlocked):
                q.verify_manifest(self.bind(m,row),row,'verified_channel',['private-approved-grant-ref'])

    def test_master_hash(self):
        row=self.row(master_sha256=hashlib.sha256(b'media').hexdigest());q.verify_master(b'media',row)
        with self.assertRaises(q.QueueBlocked):q.verify_master(b'wrong',row)

    def test_longform_exclusion_precedes_status(self):
        text=(p.parents[1]/'long-videos/main_long.py').read_text()
        start=text.index('def _from_sheet_long():');end=text.index('\ndef ',start+5);chunk=text[start:end]
        self.assertLess(chunk.index('episode_id'),chunk.index('status ='))

    def test_managed_branch_precedes_generation(self):
        text=(p.parents[1]/'main.py').read_text()
        self.assertLess(text.index('managed_master_upload_not_configured'),text.index('llm.generate_plan(topic'))

    def test_no_shorts_fallback(self):
        text=(p.parents[1]/'src/sheets.py').read_text();start=text.index('def get_next_item():');end=text.index('\ndef ',start+5)
        self.assertNotIn('_from_csv()',text[start:end]);self.assertNotIn('FALLBACK_TOPICS',text[start:end])


if __name__ == '__main__':unittest.main()
