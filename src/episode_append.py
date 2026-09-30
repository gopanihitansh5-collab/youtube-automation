"""Bounded inert canonical queue append. Never creates publish approval."""
from datetime import datetime
import json
from .episode_queue import BASE_HEADERS, MANAGED_HEADERS, QueueBlocked, SAFE_ID, publish_time

EXTRA_HEADERS = MANAGED_HEADERS + ('youtube_video_id','upload_attempt_id','upload_started_at','source_evidence','editorial_caveats')
FIELDS = {'episode_id','topic','publish_at','timezone','voice','source_evidence','editorial_caveats'}


def validate_records(records):
    if not isinstance(records,list) or not 1 <= len(records) <= 3:
        raise QueueBlocked('append_record_count_invalid')
    ids=set();rows=[]
    for record in records:
        if not isinstance(record,dict) or set(record) != FIELDS:
            raise QueueBlocked('append_fields_invalid')
        if not all(isinstance(record[k],str) for k in ('episode_id','topic','publish_at','timezone','voice','editorial_caveats')):
            raise QueueBlocked('append_field_type_invalid')
        eid=record['episode_id']
        if not SAFE_ID.fullmatch(eid) or eid in ids:
            raise QueueBlocked('append_episode_id_invalid')
        ids.add(eid)
        if not record['topic'].strip() or len(record['topic']) > 1000 or len(record['editorial_caveats']) > 4000 or record['voice'] != 'af_heart':
            raise QueueBlocked('append_content_invalid')
        publish_time(record['publish_at'],record['timezone'])
        if not isinstance(record['source_evidence'],list) or not record['source_evidence'] or not all(isinstance(s,str) and 0 < len(s) <= 1500 for s in record['source_evidence']):
            raise QueueBlocked('append_sources_invalid')
        row={'topic':record['topic'],'voice':'af_heart','privacy':'public','status':'production_hold',
             'episode_id':eid,'type':'short','publish_at':record['publish_at'],'timezone':record['timezone'],
             'source_evidence':json.dumps(record['source_evidence'],ensure_ascii=False,separators=(',',':')),
             'editorial_caveats':record['editorial_caveats']}
        rows.append(row)
    return rows


def plan_append(values, records):
    target=validate_records(records)
    if not values:
        raise QueueBlocked('append_sheet_empty')
    headers=[str(h).strip().lower() for h in values[0]]
    if headers[:10] != list(BASE_HEADERS) or len(headers)!=len(set(headers)):
        raise QueueBlocked('append_sheet_schema_invalid')
    new_headers=headers+[h for h in EXTRA_HEADERS if h not in headers]
    existing={}
    for cells in values[1:]:
        row={h:str(cells[i] if i<len(cells) else '') for i,h in enumerate(headers)}
        eid=row.get('episode_id','').strip()
        if eid:
            if eid in existing:raise QueueBlocked('append_existing_duplicates')
            existing[eid]=row
    append=[];same=0
    for row in target:
        old=existing.get(row['episode_id'])
        if old:
            # Do not reset state or overwrite an episode that has progressed.
            for key in ('topic','voice','privacy','type','publish_at','timezone','source_evidence','editorial_caveats'):
                if old.get(key,'') != row[key]:raise QueueBlocked('append_existing_record_conflict')
            same+=1
        else:append.append([row.get(h,'') for h in new_headers])
    return new_headers,append,same


def append_held(worksheet, records, execute=False):
    before=worksheet.get_all_values()
    headers,rows,same=plan_append(before,records)
    summary={'status':'dry_run' if not execute else 'success','append_count':len(rows),'already_present_count':same,
             'add_header_count':len(headers)-len(before[0])}
    if not execute:return summary
    # Shared workflow concurrency protects our writers. Stop on any unexpected
    # live edit between planning and write; Sheets offers no compare-and-swap.
    if worksheet.get_all_values()!=before:raise QueueBlocked('append_sheet_changed')
    if headers!=before[0]:
        if worksheet.col_count < len(headers):worksheet.add_cols(len(headers)-worksheet.col_count)
        worksheet.update(values=[headers],range_name='A1',value_input_option='RAW')
        if worksheet.row_values(1)!=headers:raise QueueBlocked('append_header_write_unverified')
    if rows:worksheet.append_rows(rows,value_input_option='RAW',insert_data_option='INSERT_ROWS',table_range='A1')
    after=worksheet.get_all_values()
    _,pending,confirmed=plan_append(after,records)
    if pending or confirmed!=len(records):raise QueueBlocked('append_write_unverified')
    # Existing content must remain untouched (header extension aside).
    if after[1:len(before)] != before[1:]:raise QueueBlocked('append_existing_rows_changed')
    return summary
