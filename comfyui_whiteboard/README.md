# ComfyUI whiteboard provider

This folder maps the optional whiteboard-explainer path without making the
daily workflow depend on an unconfigured GPU service.

## Pipeline map

`scene narration + keyword` -> `build_scene_prompt()` -> API-format workflow ->
ComfyUI `/prompt` -> `/history/{prompt_id}` -> `/view` PNG -> existing long-form
editor's image pan/zoom -> final FFmpeg video.

When `VISUAL_STYLE=whiteboard` and ComfyUI is configured, the provider runs
**before** Pexels and Pixabay. Any ComfyUI error falls through to the existing
stock-video chain and then the gradient fallback.

## Folder contents

- `provider.py`: prompt building, workflow filling, API submission, polling,
  output download, timeouts, and configuration checks.
- `workflow_api.json`: minimal API-format still-image workflow template.
- `prompt_styles.json`: stable whiteboard visual language and negative prompt.
- `config.json`: endpoint/secret names, dimensions, timeout, and model slot.
- `proof_ten_seconds.py`: bounded two-panel, 10-second proof before enabling daily runs.

## Host and model setup

The recommended first host is Comfy Cloud. A persistent self-hosted ComfyUI or
another hosted GPU is also valid. Do not run model downloads inside standard
GitHub-hosted Actions runners: they do not provide the needed GPU and repeated
large downloads make the workflow slow and brittle.

On the selected host:

1. Install a commercially suitable image checkpoint (SDXL/FLUX class) and, if
   desired, line-art/scribble ControlNet or an equivalent conditioning model.
2. Open `workflow_api.json` in ComfyUI, adapt node/model names to what the host
   supports, test it, then export it in API format back to this folder.
3. Replace `checkpoint` in `config.json` with the exact hosted filename.
4. Add `COMFYUI_BASE_URL` and `COMFYUI_API_KEY` as GitHub Actions secrets.
5. Set repository variable or workflow env `VISUAL_STYLE=whiteboard`.
6. Run `python -m comfyui_whiteboard.proof_ten_seconds` and inspect both images and the 10-second MP4 before enabling the daily workflow.

The template intentionally uses only core nodes. ControlNet, IP-Adapter, or
AnimateDiff can be added after the still-image proof, but every custom node and
model must exist on the chosen host and its license must allow the channel's use.

## Guardrails

- No endpoint or key means zero ComfyUI calls.
- The placeholder checkpoint prevents accidental jobs against an unknown model.
- Requests have bounded connect/job timeouts.
- Stock and gradient fallbacks remain available.
- Credentials stay in GitHub secrets, never this folder or logs.
