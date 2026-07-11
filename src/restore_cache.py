"""Restore used-visuals cache from the previous GitHub Actions artifact."""
import os, json, requests, zipfile, io

os.makedirs("output", exist_ok=True)
url = ("https://nightly.link/gopanihitansh5-collab/youtube-automation/"
       "workflows/daily-video/main/video-output.zip")
try:
    r = requests.get(url, timeout=30)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    if "output/used_visuals.json" in z.namelist():
        data = json.loads(z.read("output/used_visuals.json"))
        with open("output/used_visuals.json", "w") as f:
            json.dump(data, f)
        print(f"Restored {len(data)} used visual URLs from last run")
    else:
        print("No used_visuals.json in previous artifact")
except Exception as e:
    print(f"Could not restore used-visuals cache: {e}")
