"""Read-only summary. Never print, save, or upload row contents."""
import collections
import json
import os


def build_inventory(book):
    summaries = []
    for ws in book.worksheets():
        rows = ws.get_all_values()
        header = rows[0] if rows else []
        data = [row for row in rows[1:] if any(str(v).strip() for v in row)]
        normalized = [str(h).strip().lower() for h in header]
        def counts(column):
            if column not in normalized:
                return None
            idx = normalized.index(column)
            return dict(sorted(collections.Counter(
                str(row[idx] if idx < len(row) else '').strip().lower() or '(blank)'
                for row in data).items()))
        summaries.append({'worksheet_title': ws.title, 'allocated_row_count': ws.row_count,
                          'populated_data_row_count': len(data), 'headers': header,
                          'status_counts': counts('status'), 'type_counts': counts('type')})
    return {'status': 'success', 'title': book.title, 'worksheets': summaries}


def main():
    try:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']))
        book = gc.open_by_key(os.environ['SHEET_ID'].strip())
        summary = build_inventory(book)
        print(json.dumps(summary, sort_keys=True))
    except Exception:
        print(json.dumps({'status':'error','category':'sheet_inventory_unavailable'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
