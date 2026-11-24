# Dynamic colour-coded 3D video toolkit

The approved visual direction is the **dynamic 12-second build demo**, not the
older fixed-camera dial smoke test below. The camera changes angle, a computer
assembles from separate parts, its fan and flow particles move, and a colour
legend distinguishes structure, compute and flow. This is original conceptual
geometry, not a hardware schematic or performance claim. No visible code overlay.

## Approved dynamic demo

Open `dynamic/vertical-preview.html` through a local server, or view
`dynamic/approved-build-demo.mp4`. Source uses pinned Three.js 0.170.0, included
locally with its MIT license. No external models, inference, credentials or APIs.

To capture from this directory:

```sh
cd dynamic
python capture-preview.py
ffmpeg -framerate 24 -i frames/%04d.png -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart new-build-demo.mp4
node test-motion.mjs
```

Output is 12 seconds, 720x1280, 24fps, 288 frames, silent. `renderFrame(seconds)`
controls the exact frame time. Capture needs Chrome and Python websocket-client.
The optional original motion-helper.mjs exposes validated shot-keyed camera paths,
assembly easing and the role palette. The approved scene keeps its original
continuous camera sweep; importing the helper is optional, not claimed execution.

This is an opt-in capability, not automatic episode rotation. Real episodes still
need topic-specific facts, narration, captions and existing quality/release checks.
User approved this dynamic visual direction November 24 after rejecting the older
static diagram. No website or public-video upload is part of this toolkit change.

## Earlier route-validation smoke (not the approved visual target)


Opt-in local toolkit addition. Not selected automatically by any production scene planner.
Upstream: https://github.com/wheresryan22/anatomy
Pinned commit: 1482e8469b0a9e0d8cc18ea2740a01423d29ae80. MIT notice in source/LICENSE.

## Run the tested vertical preview

Requires local Node 20.10+, Chrome, Python 3 with websocket-client, and FFmpeg.
No APIs, signup, npm install, paid inference or CI are required by these commands.

From this directory:

```sh
node source/examples/dial-indicator/build.mjs --light
node build-preview.mjs
python capture-preview.py
ffmpeg -framerate 24 -i frames/%04d.png -c:v libx264 -pix_fmt yuv420p -crf 19 -movflags +faststart anatomy-vertical-smoke.mp4
```

This produces 192 frames, 8 seconds, 720x1280 at 24fps. Silent by design.
The sample adapts the upstream dial-indicator geometry. It is not an original
finished episode. The deterministic renderFrame(seconds) hook replaces live
pointer timing for reproducible frame capture. Numbers are model coordinates,
not physical calibrated readings. Full upstream license retained.

## Verified opt-in Shorts composition

```sh
python -m unittest -v test_adapter
python compose_local.py --asset anatomy-vertical-smoke.mp4 --manifest sample-asset.json --duration 8 --output composed-shorts-test.mp4
```

This calls the existing src/editor.py local video normalizer directly and produces
1080x1920 at 30fps, 240 frames for 8 seconds. It writes a hash-bound receipt and
never edits the planner or accepted episode bank. The guard checks local MP4,
9:16 aspect, hash, explicit illustration provenance and sufficient source duration.
Missing assets, wrong provenance, hash mismatch and attempted silent looping fail.
Output must be a new path. Input audio is discarded by the existing normalizer.
Tests are local, no Actions run. Seven adapter tests passed. Final composed pixels
were inspected at first/middle/last frames. This is a working opt-in local-media
composition path, not automatic rotation or full episode acceptance.

## Production boundary

The canonical main checked for this patch was 6f900544df3b3bc0a71522f076f96041219ed805.
There was no central style registry. Do not allocate a letter or silently change
prompt_styles.json. The existing authored_diagram lane is a bounded 2-4 node
schematic contract, not a generic browser-code execution lane. Do not relabel
Anatomy output as authored_diagram or stock.

Use this adapter as an offline authored asset generator. To include a new
original Anatomy mechanism in an episode, author its explanatory model against
verified topic facts, render deterministically, inspect actual encoded frames,
then use the producer's existing reviewed local-media composition path. If no
such path is available, keep the asset isolated rather than weakening validation.
Long-form needs its own 1920x1080 composition and 170px bottom subtitle reserve;
this vertical smoke sample does not demonstrate that mode.

The implementation proves offline assets can enter the existing Shorts local
video normalizer through compose_local.py. Planner integration and automatic
rotation are deliberately absent.
Narration, subtitles, fact checks, hearing/continuous-AV review, cover provenance,
served-artifact checks, slot limits and publication holds remain unchanged.
No automatic publish, network submission or website modification is included.

## Checks actually performed

- Upstream minimal build runs locally.
- Deterministic capture and H.264 encode run locally.
- Actual final encoded first/middle/last-frame contact sheet inspected.
- Caption corrected to remove unused pointer-interaction instructions.
- No runtime installation into any agent system or global skill folder.
- No push, merge, deployment or YouTube upload.

Light shading is faithful to the reference but low contrast at small display
sizes. Before a real episode, increase illustration scale/contrast and reduce
supporting copy. Do not call this smoke preview a finished production video.

Capture reliability: CHROME_PATH overrides browser discovery. DevTools startup is
bounded to20seconds, page hook to10seconds, and socket commands to15seconds.
Browser, WebSocket and temporary profile are cleaned up on failure or completion.
The dial probe can span a block edge; between-block labels refer to probe center
while contact height uses its finite tip footprint. Explain this before teaching
from the model; do not interpret it as a calibrated physical gauge.

V3 guard validation decodes video frame timings, rejects gaps/unverifiable durations,
and uses picture span instead of audio/container length. Adversarial1second-picture
with3second-audio is rejected for2seconds. Existing receipt blocks composition.
Exact dependency: canonical main6f900544df3b3bc0a71522f076f96041219ed805,
src/editor.py, copied unchanged to verification/canonical-editor.py in handoff.
