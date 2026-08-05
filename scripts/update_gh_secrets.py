"""Encrypt + upload GitHub Actions secrets using the repo's libsodium public
key. This version reads secret values from environment variables so no secrets
are hardcoded in the file.

Usage (PowerShell):
    $env:GH_TOKEN = "..."
    $env:SEC_YT_CLIENT_ID = "..."
    $env:SEC_YT_CLIENT_SECRET = "..."
    $env:SEC_YT_REFRESH_TOKEN = "..."
    python scripts/update_gh_secrets.py
"""
import base64
import json
import os
import urllib.request
from nacl import encoding, public

REPO = "gopanihitansh5-collab/youtube-automation"
API = f"https://api.github.com/repos/{REPO}"

# name in GitHub  ->  env var carrying the value (read from env at runtime)
SECRET_ENV = {
    "YT_CLIENT_ID": "SEC_YT_CLIENT_ID",
    "YT_CLIENT_SECRET": "SEC_YT_CLIENT_SECRET",
    "YT_REFRESH_TOKEN": "SEC_YT_REFRESH_TOKEN",
}


def api(path, method="GET", body=None, token=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"token {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else None


def encrypt(public_key: str, secret_value: str) -> str:
    pub = public.PublicKey(public_key.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pub)
    encrypted = box.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def main():
    token = os.environ["GH_TOKEN"]
    pub_key = api("/actions/secrets/public-key", token=token)
    key_id = pub_key["key_id"]
    for name, env_name in SECRET_ENV.items():
        value = os.environ.get(env_name)
        if not value:
            print(f"SKIP {name}: env {env_name} not set")
            continue
        payload = {
            "encrypted_value": encrypt(pub_key["key"], value),
            "key_id": key_id,
        }
        api(f"/actions/secrets/{name}", method="PUT", body=payload, token=token)
        print(f"{name} -> updated")


if __name__ == "__main__":
    main()