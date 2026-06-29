# NeuroScape: EEG-Adaptive Soundscape

NeuroScape is a local prototype for EEG-adaptive spatial audio meditation. A user describes a desired mental world, the system generates an initial soundscape, then EEG-derived mental state estimates adapt the scene over time. The app supports both prerecorded Mind Monitor CSV playback and realtime Muse OSC streaming.

## Current Flow

1. The user enters a meditation prompt in the Flask UI.
   The meditation duration defaults to 10 minutes and can be changed on the
   prompt screen. Elapsed meditation time starts only after the first valid EEG
   sample is received; reaching the target ends the session automatically.
2. `scripts/scene_logic.py` generates an initial scene with mock sound assets.
3. EEG data is processed as sliding windows:
   - CSV mode reads `EEG_FILE` from `.env`.
   - Muse mode listens for OSC band data from Mind Monitor.
4. Each EEG window is converted into feature payloads, interpreted into mental state, and used to adapt the active soundscape.
5. The latest Unity-facing scene is written to `outputs/current_unity_scene.json`.
6. Ending the session builds a summary dashboard at `/summary`, including mental timeline, audio timeline, average metrics, and session insight.

## Quick Start

1. Create and activate a Python 3.10+ virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`.
4. Add `OPENAI_API_KEY` if you want LLM-backed scene generation and interpretation.
5. Run the app:

   ```bash
   python app.py
   ```

6. Open `http://127.0.0.1:5000`.

## EEG Modes

### CSV Mode

CSV mode uses a prerecorded Mind Monitor CSV:

```env
EEG_FILE=data/mindMonitor_2026-03-06--17-19-44.csv
WINDOW_SEC=60
STEP_SEC=40
```

The app precomputes EEG windows with `scripts/eeg_pipeline.py`, then the UI can step through or play through those windows.

### Muse Realtime Mode

Realtime mode listens for Mind Monitor OSC messages from Muse:

```env
OSC_IP=0.0.0.0
OSC_PORT=5000
REALTIME_WINDOW_SEC=60
REALTIME_STEP_SEC=40
REALTIME_WARMUP_SEC=20
REALTIME_BUFFER_SEC=180
```

Meaning:

- `REALTIME_WARMUP_SEC`: wait this long before the first realtime EEG window.
- `REALTIME_STEP_SEC`: update cadence after the first window.
- `REALTIME_WINDOW_SEC`: maximum recent signal span used for each window.
- `REALTIME_BUFFER_SEC`: how much raw realtime EEG history is kept in memory.

In Mind Monitor, enable OSC streaming and point it to the machine running Flask on port `5000`.

## Signal Handling

Realtime Muse data can sometimes arrive with all EEG bands as `0`. Earlier versions could turn that into fake high scores such as attention `88` and stability `100` because of division-by-zero protection in the feature formulas.

The current system guards against that:

- realtime windows with all-zero EEG bands are rejected before interpretation;
- if an old or malformed payload still reaches the app, it is labeled `insufficient_eeg_signal`;
- realtime UI mental scores show waiting/blank values instead of fake scores;
- the summary dashboard does not count those windows as valid mental metrics.

## Outputs

Generated session artifacts live under `outputs/`:

- `initial_scene.json`: first generated soundscape.
- `current_unity_scene.json`: latest Unity-facing scene state.
- `eeg_payloads.json` / `eeg_payloads.jsonl`: processed EEG window payloads.
- `eeg_windows.csv`: CSV-mode or realtime-compatible feature table.
- `eeg_window_XX_interpretation.json`: per-window mental-state interpretation.
- `eeg_window_XX_scene_update.json`: per-window adapted scene.
- `session_dashboard_summary.json`: saved summary data used by `/summary`.
- `sessions/YYYYMMDD_HHMMSS_session_NNN/`: immutable archive created whenever
  `/api/end_session` is called. Each archive includes the original prompt,
  session metadata, recorded or realtime EEG data, window payloads, LLM
  input/output traces and prompt templates, full scene/audio action history,
  Unity command history, dashboard data, and a file manifest. Starting the next
  meditation clears only the working output files and keeps these archives.
  Realtime archives contain both `realtime_eeg_raw.csv` (the synchronized
  band-feature stream used by NeuroScape) and `mind_monitor_osc_raw.jsonl`
  (every original OSC address and argument received from Mind Monitor, before
  averaging, filtering, or feature extraction). They also contain
  `mind_monitor_record_compatible.csv`, reconstructed with the same columns as
  a Mind Monitor Record upload. When OSC supplies one aggregate value for a
  frequency band, that value is copied into its four channel columns; the
  companion schema JSON records this conversion.
- `llm_payloads.json` / `llm_payloads.jsonl`: realtime pipeline payload logs.
- `sliding_window_features.csv`: realtime feature table.
- `realtime_payload_history.json`: recent realtime payload history.

Older root-level `llm_payloads.json` and `llm_payloads.jsonl` files may exist from previous runs, but new realtime sessions write them into `outputs/`.

## Important Files

- `app.py`: Flask server, session state, API routes, realtime consumer, summary builder.
- `muse_realtime.py`: Muse OSC listener, realtime buffer, feature extraction, realtime payload logs.
- `scripts/eeg_pipeline.py`: prerecorded CSV loading, cleaning, feature extraction, window payload generation.
- `scripts/scene_logic.py`: prompt-to-scene logic, EEG interpretation, adaptive scene update logic.
- `translator.py`: scene-to-command translation for Unity-facing state.
- `ui/templates/`: Flask UI and summary dashboard templates.
- `lib/mock_sound_library.py`: mock sound library loader.
- `.env.example`: runtime configuration template.

## API Surface

The UI mainly uses these endpoints:

- `POST /api/bootstrap`: start a CSV or realtime session from a prompt.
- `POST /api/step`: advance CSV mode or consume a pending realtime window.
- `GET /api/state`: current scene, current EEG payload, mental history.
- `GET /api/eeg_sample`: latest sample for realtime display or CSV playback.
- `POST /api/end_session`: stop session and save dashboard summary.
- `GET /api/session_summary`: structured summary data for `/summary`.
- `GET /api/unity_state`: current scene translated for Unity consumption.

## Fallback Behavior

- If the OpenAI API key is missing or a call fails, deterministic rule-based interpretation and adaptation are used where possible.
- Realtime scene adaptation runs asynchronously after Muse windows arrive.
- Summary timeline alignment now uses `window_id` instead of simple array position, so realtime auto-summary records do not shift the final dashboard timeline.

## Git Hygiene

`.env`, `outputs/`, `data/`, virtual environments, generated CSVs, images, and audio files are ignored. Keep secrets in `.env`; do not commit API keys.
