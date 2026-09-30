"""Manual held-row dispatch adapter. Emits counts only, never row data."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.episode_append import append_held
from src.episode_queue import QueueBlocked


def main():
    try:
        import gspread
        records=json.loads(os.environ['HELD_EPISODES_JSON'])
        gc=gspread.service_account_from_dict(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']))
        ws=gc.open_by_key(os.environ['SHEET_ID'].strip()).sheet1
        result=append_held(ws,records,execute=os.environ.get('EXECUTE_HELD_APPEND')=='true')
        print(json.dumps(result,sort_keys=True))
    except QueueBlocked as exc:
        print(json.dumps({'status':'blocked','category':str(exc)}));raise SystemExit(1)
    except Exception:
        print(json.dumps({'status':'blocked','category':'append_external_failure'}));raise SystemExit(1)


if __name__=='__main__':main()
