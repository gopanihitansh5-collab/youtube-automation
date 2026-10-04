"""Fail-closed upload receipts. Session URLs are private recovery credentials."""
import hashlib
import json
import os
from pathlib import Path


class UploadConflict(RuntimeError):
    pass


class Ledger:
    def __init__(self, path, episode, directory, store=None):
        self.sha256 = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                self.sha256.update(chunk)
        self.sha256 = self.sha256.hexdigest()
        self.source_path = str(path)
        self.episode = str(episode)
        self.marker = 'ae-receipt-' + hashlib.sha256(self.episode.encode()).hexdigest()[:24]
        self.store = store
        self.path = Path(directory) / (self.marker + '.json')
        self.data = store.get(self.marker) if store else (json.loads(self.path.read_text()) if self.path.exists() else {})
        if self.data and self.data.get('sha256') != self.sha256:
            raise UploadConflict('Episode already has a different rendered hash; inspect its receipt before replacement')

    def save(self, **changes):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        candidate = dict(self.data, episode=self.episode, sha256=self.sha256, **changes)
        if self.store:
            self.store.put(self.marker, candidate)
        self.data = candidate
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)



class RecordingHttp:
    """Persist the session before the client starts sending media bytes."""
    def __init__(self, inner, ledger):
        self.inner, self.ledger = inner, ledger

    def request(self, *args, **kwargs):
        response, content = self.inner.request(*args, **kwargs)
        if response.status == 200 and 'location' in response:
            self.ledger.save(session_uri=response['location'], state='session_started')
        return response, content
