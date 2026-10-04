# Private upload recovery

Uploads fail closed until UPLOAD_LEDGER_KEY and private-upload-state are provisioned.
The branch lives in the existing repository. Its name is not a privacy boundary.
Only AES-GCM ciphertext is committed as upload-ledger.aesgcm. Recovery session URLs,
video receipts and plaintext must never be included in logs or uploaded artifacts.

Provisioning:
- Set UPLOAD_LEDGER_KEY to standard base64 of32 cryptographically random bytes,
  directly through the approved secret writer. Do not paste it into chat/logs.
- Create branch private-upload-state from the reviewed main commit. Do not create
  upload-ledger.aesgcm manually: the first authenticated smoke creates ciphertext.
- Run Manual encrypted upload-ledger smoke. Check encrypted write/readback and stale
  revision rejection pass. No media upload occurs. Keep the key stable: replacing
  it without migrating the ledger makes all existing receipts unreadable.
- Daily Short/long and manual smoke share youtube-upload concurrency, no cancellation.
  GitHub permits one running and one pending workflow per concurrency group; extra
  queued runs can replace pending runs. The scheduler owner must reconcile missed slots.

Each upload has an immutable episode marker and media SHA256. A receipt is written
before initiation and the resumable Location is durably saved before any media chunk.
The video ID is saved before processing checks. Ambiguous initiation without a stored
session is reconciled by exact episode-marker tag on the existing channel, never by
blind insertion. A changed hash under the same episode is blocked. Private local
receipts are0600 and excluded from artifact output paths.

Public processing success is insufficient. Anonymous served video/audio must download,
match duration, fully decode, and show changing frames before the public-media receipt.
That mechanical proof does not replace factual, audio, caption or full-player review.
Full publication stack remains a separate UI gate, including playlists, related video,
reviewed captions and a real sourced comment/pin. YouTube Data API does not pin comments.
No Sheet done or success heartbeat is emitted while this review is pending. These
workflow failures are genuine incomplete work, never clear them with fake success pings.

The Drive empty ledger is unused and remains owner-only. No new Drive share is needed.
