"""Read-only metadata for actual stored Sheet binding. No ID/content output."""
import json
import os

def probe():
    try:
        import gspread
        gc=gspread.service_account_from_dict(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']))
        book=gc.open_by_key(os.environ['SHEET_ID'].strip())
        return {'status':'success','title':book.title,'row_count':book.sheet1.row_count}
    except Exception:
        return {'status':'error','category':'sheet_metadata_unavailable'}

if __name__=='__main__':
    print(json.dumps(probe(),sort_keys=True))
