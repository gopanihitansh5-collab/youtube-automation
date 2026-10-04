"""Encrypted durable upload receipts in an already-owned GitHub repository.

Only AES-GCM ciphertext reaches GitHub. The branch name does not imply privacy:
the repository may be public. Atomic Contents writes use the expected blob SHA.
"""
import base64
import json
import os
import re
import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.upload_ledger import UploadConflict

class PrivateGitHubStore:
    path = 'upload-ledger.aesgcm'
    def __init__(self):
        self.repo = os.environ.get('UPLOAD_LEDGER_REPO', '')
        self.branch = os.environ.get('UPLOAD_LEDGER_BRANCH', 'private-upload-state')
        token = os.environ.get('UPLOAD_LEDGER_GITHUB_TOKEN', '')
        raw = os.environ.get('UPLOAD_LEDGER_KEY', '')
        try:
            key = base64.b64decode(raw, validate=True)
            if len(key) != 32:raise ValueError()
        except Exception:
            raise UploadConflict('Encrypted upload ledger key is not provisioned; upload disabled') from None
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repo) or not token or not re.fullmatch(r'[A-Za-z0-9_.-]+', self.branch):
            raise UploadConflict('Encrypted upload ledger route is not provisioned; upload disabled')
        self.cipher = AESGCM(key)
        self.aad = (self.repo + ':' + self.branch + ':' + self.path).encode()
        self.http = requests.Session()
        self.http.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
        self.base = 'https://api.github.com/repos/' + self.repo
        # Never silently create a different route when provisioning is absent.
        r=self._request('GET','/branches/'+self.branch)
        if r.status_code != 200:raise UploadConflict('Encrypted ledger branch unavailable; upload disabled')
        self.entries,self.sha=self._read()

    def _request(self, method, suffix, **kwargs):
        try:return self.http.request(method,self.base+suffix,timeout=30,**kwargs)
        except Exception:raise UploadConflict('Encrypted ledger network failure; upload disabled') from None

    def _read(self):
        r=self._request('GET','/contents/'+self.path,params={'ref':self.branch})
        if r.status_code==404:return {},None
        if r.status_code!=200:raise UploadConflict('Encrypted ledger read failed; upload disabled')
        try:
            row=r.json()
            if row.get('encoding')!='base64' or not row.get('sha'):raise ValueError()
            envelope=json.loads(base64.b64decode(row['content']))
            if envelope.get('version')!=1:raise ValueError()
            nonce=base64.b64decode(envelope['nonce'],validate=True)
            ciphertext=base64.b64decode(envelope['ciphertext'],validate=True)
            if len(nonce)!=12:raise ValueError()
            data=json.loads(self.cipher.decrypt(nonce,ciphertext,self.aad))
            if not isinstance(data,dict):raise ValueError()
            return data,row['sha']
        except Exception:raise UploadConflict('Encrypted ledger authentication failed; upload disabled') from None

    def get(self,key):return self.entries.get(key,{})

    def put(self,key,value):
        latest,sha=self._read()
        if sha!=self.sha or latest!=self.entries:
            raise UploadConflict('Encrypted ledger changed concurrently; upload disabled')
        latest[key]=value
        nonce=os.urandom(12)
        ciphertext=self.cipher.encrypt(nonce,json.dumps(latest,separators=(',',':')).encode(),self.aad)
        envelope={'version':1,'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(ciphertext).decode()}
        body={'message':'Update encrypted upload receipt','branch':self.branch,'content':base64.b64encode(json.dumps(envelope).encode()).decode()}
        if sha:body['sha']=sha
        r=self._request('PUT','/contents/'+self.path,json=body)
        if r.status_code not in (200,201):raise UploadConflict('Atomic encrypted ledger write rejected; upload disabled')
        try:newsha=r.json()['content']['sha']
        except Exception:raise UploadConflict('Encrypted ledger write receipt unavailable; upload disabled') from None
        check,checksha=self._read()
        if check!=latest or checksha!=newsha:raise UploadConflict('Encrypted ledger readback mismatch; upload disabled')
        self.entries,self.sha=check,checksha
