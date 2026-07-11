"""
Run this ONCE on your own computer to mint a YouTube refresh token.

Steps:
  1. In Google Cloud Console, enable "YouTube Data API v3".
  2. Create an OAuth client ID of type "Desktop app".
  3. Download it as client_secret.json and put it next to this file.
  4. pip install google-auth-oauthlib
  5. python get_youtube_token.py
  6. A browser opens -> log in with the channel's Google account -> Allow.
  7. Copy the three printed values into your GitHub repo secrets:
        YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Note: if your OAuth consent screen is in "Testing" mode, add your Google
account as a Test User, otherwise the refresh token expires in 7 days.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
# access_type=offline + prompt=consent guarantees a refresh_token is returned
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

print("\n=== Copy these into your GitHub repo Secrets ===")
print("YT_CLIENT_ID     =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
