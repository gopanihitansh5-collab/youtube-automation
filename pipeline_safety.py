"""Typed worker failures and private diagnostics, without provider imports."""
import json
from pathlib import Path

class ProviderFailure(RuntimeError):
    pass

def call_provider(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:
        name = getattr(fn, "__name__", type(fn).__name__)
        raise ProviderFailure(f"{name} bootstrap exited with code {exc.code}") from exc

def write_failure(exc, stage, path='output_long/failure.json'):
    # Never serialize provider response bodies, environment or credentials.
    result={'stage':stage,'error_type':type(exc).__name__,
            'reason':'provider_bootstrap_exit' if isinstance(exc, (SystemExit,ProviderFailure)) else 'pipeline_exception'}
    out=Path(path);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
