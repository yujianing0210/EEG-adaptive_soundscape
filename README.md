# EEG-Adaptive Spatial Audio MVP (local)

Local prototype that turns a text prompt plus a 120s Mind Monitor EEG CSV into:

- an initial spatial meditation scene (mock assets)
- per-window EEG feature payloads and interpretations
- adaptive Unity-facing JSON scene updates
- a simple Flask UI to step through EEG windows

## Quick start

1. Install Python 3.10+ and create a virtualenv.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your `OPENAI_API_KEY` (optional but enables LLM interpretation).
4. Ensure the EEG CSV is at `data/mindMonitor_2026-03-06--17-46-21.csv` (already copied from `phase1/data`).
5. Run the app: `python app.py`
6. Open http://127.0.0.1:5000, enter a prompt (e.g., "I want a forest scene"), click **Bootstrap scene**, then **Next EEG window** to step through adaptations.

## What happens

- `scripts/eeg_pipeline.py` loads the CSV, applies windowing (60s window / 20s step), extracts features, and writes `outputs/eeg_windows.csv` and payload JSON.
- `scripts/scene_logic.py` bootstraps a scene, interprets each EEG window (LLM when available, deterministic fallback otherwise), and adapts the scene + Unity JSON.
- `app.py` (Flask) stitches UI + logic; it saves per-window JSONs under `outputs/` and keeps the latest Unity JSON in `outputs/current_unity_scene.json`.
- Mock sound assets live in `data/mock_sound_library.json` and are highlighted in the UI when active.

## Files of interest

- `app.py` — Flask server + orchestration
- `ui/templates/index.html` — minimal UI panels
- `scripts/eeg_pipeline.py` — EEG parsing, features, window payloads
- `scripts/scene_logic.py` — bootstrap + interpretation + adaptation
- `data/mock_sound_library.json` — mock assets
- `outputs/` — generated EEG payloads, interpretations, scene updates
- `prompts/` — prompt stubs for LLM calls

## Notes & fallback behavior

- If the OpenAI key is missing or an API call fails, the system falls back to rule-based states and deterministic adaptation heuristics.
- Real audio playback/Unity integration is not included; JSON files are structured for later consumption.
- You can tweak window size/step via env vars `WINDOW_SEC` and `STEP_SEC` in `.env`.
