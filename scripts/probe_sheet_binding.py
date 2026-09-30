"""Read-only binding proof. No secret values or row bodies in output."""
import json
import os
EXPECTED='1h42nbh2Tn-0xXIxd4Vf_ttbdqjGx8JFhDZm5YCCZj8g'

def probe(env, client_factory=None):
    if env.get('SHEET_ID')!=EXPECTED:
        return {'sheet_binding':'no_match'}
    result={'sheet_binding':'match'}
    try:
        if client_factory is None:
            import gspread
            client_factory=gspread.service_account_from_dict
        client=client_factory(json.loads(env['GOOGLE_SERVICE_ACCOUNT_JSON']))
        sheet=client.open_by_key(EXPECTED);ws=sheet.sheet1
        result.update({'title':sheet.title,'header':ws.row_values(1),
                       'row_ids':[n for n in (377,378,379) if n<=ws.row_count]})
    except Exception:
        result['read_status']='unavailable'
    return result

if __name__=='__main__':
    print(json.dumps(probe(os.environ),sort_keys=True))
