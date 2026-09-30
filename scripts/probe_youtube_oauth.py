"""Read-only refresh probe. Never prints or persists credentials/access tokens."""
import json
import os

SCOPES={'upload':'https://www.googleapis.com/auth/youtube.upload',
        'readonly':'https://www.googleapis.com/auth/youtube.readonly'}
ERRORS={'invalid_grant','invalid_scope','invalid_client','unauthorized_client','access_denied','temporarily_unavailable'}

def probe(session, env):
    if not all(env.get(k) for k in ('YT_CLIENT_ID','YT_CLIENT_SECRET','YT_REFRESH_TOKEN')):
        return [{'scope':scope,'status':'not_configured'} for scope in SCOPES.values()]
    out=[]
    for scope in SCOPES.values():
        try:
            response=session.post('https://oauth2.googleapis.com/token',data={
                'client_id':env['YT_CLIENT_ID'],'client_secret':env['YT_CLIENT_SECRET'],
                'refresh_token':env['YT_REFRESH_TOKEN'],'grant_type':'refresh_token','scope':scope},timeout=30)
            data=response.json()
            if response.status_code==200 and isinstance(data.get('access_token'),str):
                granted=[s for s in str(data.get('scope','')).split() if s.startswith('https://www.googleapis.com/auth/')]
                out.append({'scope':scope,'status':'success','granted_scopes':granted})
            else:
                error=data.get('error');out.append({'scope':scope,'status':'error','category':error if error in ERRORS else 'oauth_error'})
        except Exception:
            out.append({'scope':scope,'status':'error','category':'transport_or_response_error'})
    return out

if __name__=='__main__':
    import requests
    print(json.dumps({'oauth_probe':probe(requests,os.environ)},sort_keys=True))
