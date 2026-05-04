# EEG-Adaptive Spatial Audio MVP Spec

## Purpose

Build a local MVP for an EEG-adaptive spatial audio system for meditation.

The MVP has two connected phases:

1. **Phase 1: Prompt-to-Scene bootstrap**
   - User types one sentence such as: `I want a forest scene`
   - The system generates an initial ~60 second meditation scene package
   - The package includes scene description, short narration, sound source plan, and Unity-readable spatial JSON

2. **Phase 2: EEG-driven scene adaptation**
   - The system reads a pre-recorded 120-second Muse / Mind Monitor EEG CSV from the local folder
   - It extracts structured features from the EEG data
   - It interprets the mental state conservatively
   - It updates the scene plan and spatial audio JSON based on the interpreted state and prior scene memory

**Important scope decision:**
This MVP does **not** need to render real spatial audio in Unity yet.
It only needs to generate the JSON package that Unity will later consume.

**Important constraint:**
There is currently **no real sound library** in the local folder.
Use **mock sound assets** and **mock asset metadata** for now.
Do not block implementation on missing audio files.

---

## Product definition

This is **not** just an EEG classifier and **not** just a text-to-audio toy.
It is a local prototype of a **bio-adaptive scene planning interface** for spatial meditation audio.

The system should demonstrate a closed loop:

`user prompt -> initial scene -> EEG feature extraction -> mental state interpretation -> scene adaptation -> updated spatial JSON`

The user should be able to see, in one simple interface:

- what scene was requested
- what scene was generated
- what sound sources are active
- what the EEG analysis currently says
- how the system decided to adapt the next soundscape segment

---

## Available local input

Assume the current local folder already contains:

- one pre-recorded EEG CSV exported from Mind Monitor
  - example filename and file path: "phase1/data/mindMonitor_2026-03-06--17-46-21.csv"
- an existing Python EEG analysis prototype or related code may already exist
  - reuse existing code where possible rather than rewriting from scratch

No real sound library exists yet.

---

## Non-goals for this MVP

Do **not** implement the following unless trivial:

- real Unity integration
- real-time WebSocket streaming to Unity
- real audio synthesis pipeline
- HRTF / HRIR rendering
- voice TTS generation
- database setup
- authentication
- deployment
- multi-user support
- long-term storage beyond local JSON files

---

## High-level user story

A user opens the local app and enters a text prompt such as:

> I want a forest scene.

The app generates:

- a short scene brief
- a short guided narration
- a mock list of active sound sources
- a spatial audio plan in JSON

Then the app loads the local EEG CSV and simulates a session timeline.
At regular update intervals, the app:

- analyzes the next EEG window
- interprets the current mental state
- decides whether the user is becoming calmer, more stable, more distracted, or more effortful
- updates the scene plan and sound source arrangement accordingly
- outputs a new JSON package for the next segment

The interface makes this process visible and understandable.

---

## MVP deliverables

The implementation should produce the following:

### 1. Local web UI

A simple local app, preferably using a lightweight frontend stack.
A single-page app is enough.

### 2. Backend or local orchestration layer

A local service that:

- accepts the user prompt
- loads the EEG CSV
- runs feature extraction
- calls the OpenAI API for interpretation and planning
- writes intermediate JSON outputs

### 3. Mock sound asset system

A local mock asset registry that stands in for a future sound library.

### 4. Spatial scene JSON generator

A JSON schema and generator for Unity-facing sound plans.

### 5. Reproducible local setup

A `.env` file for API keys and a README with setup steps.

---

## Recommended implementation approach

### Suggested stack

Use a simple stack that Copilot can implement quickly and reliably.

Recommended:

- **Frontend:** Next.js or React with simple local UI
- **Backend:** Node route handlers or a small Python API
- **EEG processing:** Python preferred, because the existing EEG code is likely already in Python
- **Interop:** frontend/backend can call Python scripts or use a lightweight API route

If one stack is easier given the current folder contents, prefer reuse over elegance.

### Preferred architecture

#### Option A: Next.js + Python scripts

- Next.js for UI and API routes
- Python for EEG feature extraction and CSV processing
- Next.js API route spawns Python scripts or reads their outputs

This is the preferred option if there is already Python EEG code in the folder.

#### Option B: Pure Python + lightweight frontend

- Flask or FastAPI backend
- simple HTML/JS frontend

Use this only if frontend scaffolding is currently missing and speed matters more than polish.

---

## Functional requirements

## FR-1. Prompt input and session bootstrap

The app must provide a text input box where the user can enter a scene prompt.

Example prompts:

- `I want a forest scene`
- `I want a beach meditation scene`
- `I want a quiet night forest`

When the user submits the prompt, the app must generate an initial **scene package** with:

- `scene_id`
- `scene_type`
- `atmosphere`
- `narrative_brief`
- `narration_script`
- `sound_sources`
- `spatial_plan`
- `world_state`

This initial package may be generated by an OpenAI call and should remain conservative and structured.

### Acceptance criteria

- User can submit one sentence.
- System generates a valid structured initial scene package.
- Output is visible in the UI.

---

## FR-2. Mock sound library

Because there is no real sound library yet, create a local mock asset registry.

### Required file

Create:

`data/mock_sound_library.json`

### Required content pattern

It should contain 10–20 mock assets such as:

- forest_ambient_bed
- light_wind_through_leaves
- distant_birds_left
- branch_creak_far
- soft_stream_front
- ocean_waves_front
- seagull_overhead
- soft_footsteps_ground
- guided_narration_neutral
- guided_narration_grounding

Each asset entry should include:

- `asset_id`
- `label`
- `category` (`ambient`, `event`, `narration`)
- `description`
- `mock_file_path`
- `default_duration_sec`
- `default_volume`
- `spatial_profile`
- `tags`

The files do not need to exist physically yet.
The registry is the source of truth for selectable sound sources.

### Acceptance criteria

- Mock asset file exists.
- App can read it.
- UI can display the available assets.
- Active assets can be highlighted.

---

## FR-3. EEG CSV loading

The system must load the local pre-recorded Mind Monitor EEG CSV.

### Requirements

- Read the CSV from a configurable path.
- Handle `TimeStamp` parsing.
- Derive relative elapsed time.
- Support Mind Monitor style column names.
- Filter unusable rows using `HeadBandOn` and `HSI` columns when available.

### Config behavior

The EEG file path should be configurable in one place.

Suggested default:

- `data/mindMonitor_2026-03-06--17-46-21.csv`

### Acceptance criteria

- App can load the EEG file from disk.
- It fails gracefully with a helpful error if the path is wrong.

---

## FR-4. EEG feature extraction

Reuse existing EEG analysis logic where possible.

The feature extraction layer should compute a structured feature summary from the EEG CSV.

### Required features

At minimum:

- band means for `Delta`, `Theta`, `Alpha`, `Beta`, `Gamma`
- band std for each band
- `alpha_beta_ratio`
- `theta_beta_ratio`
- `alpha_theta_ratio`
- `relaxation_score`
- `attention_score`
- `variance_score`
- `stability_score`

If accelerometer or gyro exists, also compute:

- `acc_mean`
- `acc_std`
- `gyro_mean`
- `gyro_std`

### Windowing strategy for this MVP

Because the available EEG file is about 120 seconds long, do **not** require a full long-session streaming design.

Use one of these approaches:

#### Preferred approach

- `window_sec = 60`
- `step_sec = 20`

This creates multiple overlapping windows from the 120-second file and is better for adaptation demos.

#### Fallback approach

- `window_sec = 40`
- `step_sec = 20`

Use fallback only if too much data is lost after signal filtering.

### Acceptance criteria

- Feature extraction runs locally.
- Multiple time windows are produced from the 120-second CSV.
- Output is saved as JSON and/or CSV.

---

## FR-5. Rule-based baseline mental state

Before calling the LLM, the system must derive a conservative baseline state label from extracted EEG features.

### Required labels

Use a small fixed set such as:

- `distracted_or_unstable`
- `effortful_focus`
- `settling`
- `stable_relaxation`

### Purpose

This rule layer provides:

- interpretability
- fallback behavior if API fails
- a stable prior for the LLM

### Acceptance criteria

- Each EEG window gets a rule-based label.
- The label is shown in the UI.

---

## FR-6. LLM-based mental state interpretation

The LLM should **not** receive raw EEG waveforms.
It should receive only structured features, deltas, current rule state, and brief recent history.

### Required output structure

The LLM response for each EEG window must be strict JSON with at least:

```json
{
  "state_label": "settling",
  "confidence": 0.78,
  "trend": "improving",
  "interpretation": "Alpha is rising relative to beta and the pattern is becoming more stable.",
  "attention": 0.58,
  "relaxation": 0.72,
  "stability": 0.61,
  "mind_wandering_risk": 0.34,
  "scene_implication": {
    "density": 0.35,
    "motion_intensity": 0.2,
    "eventfulness": 0.18,
    "guidance_intensity": 0.4,
    "proximity": 0.55
  }
}
```

### Important behavior

The prompt must instruct the model to:

- be conservative
- avoid diagnosis
- use only provided EEG summaries
- infer trend relative to the previous window
- output scene-relevant control variables

### Acceptance criteria

- The response is valid JSON.
- The UI shows the interpretation and trend.
- If the API call fails, the app falls back to the rule-based state and a default scene implication.

---

## FR-7. Scene memory / world state

The app must maintain a lightweight `world_state` object across scene updates.

### Why this matters

The soundscape must evolve continuously.
It must feel like the user is still in the same world, not like a new random scene starts every update.

### Required world state fields

At minimum:

```json
{
  "scene_family": "forest",
  "current_phase": "settling_in",
  "atmosphere": "quiet, enclosed, soft morning air",
  "dominant_elements": ["forest_ambient_bed", "light_wind_through_leaves"],
  "active_sources": [
    "forest_ambient_bed",
    "light_wind_through_leaves",
    "distant_birds_left"
  ],
  "retired_sources": [],
  "continuity_notes": "Keep forest identity stable; avoid sudden scene jumps."
}
```

### Acceptance criteria

- World state is created during Phase 1.
- World state is updated during each EEG interpretation step.
- Scene changes reference the previous state.

---

## FR-8. Adaptive scene planning

After each EEG interpretation step, the system must generate a **next scene segment**.

This segment should not replace the world; it should evolve it.

### Required sub-planners

Implement the logic as three conceptual stages, even if they live in one function.

#### A. Scene Planner

Decides:

- scene phase
- atmosphere
- continuity from last scene
- openness / density / calmness / motion character

#### B. Sound Source Planner

Decides:

- which 2–5 sound sources are active in the next segment
- which sources are newly introduced
- which are reduced or retired
- the role of each source

#### C. Spatial Planner

Decides for each active source:

- position `(x, y, z)`
- distance category or scalar
- volume
- motion type
- trajectory if any
- fade in / fade out

### Required adaptation logic

Use your prior findings as heuristics:

- if relaxation decreases or stability fluctuates strongly:
  - reduce discrete events
  - strengthen continuous ambient sources
  - keep the world coherent
- if attention drops or mind-wandering risk rises:
  - add one subtle directional cue
  - do not overload the scene
- if the state becomes stable and relaxed:
  - let ambient sound circulate slowly or broaden spatially
  - reduce intervention pressure

### Acceptance criteria

- Each EEG window yields a next-segment scene adaptation.
- Adaptation is visible in the UI.
- Adaptation updates the Unity JSON.

---

## FR-9. Unity-facing spatial JSON

The MVP must generate Unity-readable JSON plans for the current scene and each adapted segment.

### Required file outputs

For example:

- `outputs/initial_scene.json`
- `outputs/eeg_window_00_interpretation.json`
- `outputs/eeg_window_00_scene_update.json`
- `outputs/current_unity_scene.json`

### Required schema

At minimum:

```json
{
  "scene_id": "forest_session_001",
  "segment_id": "segment_000",
  "duration_sec": 60,
  "scene_type": "forest",
  "atmosphere": "quiet morning forest",
  "narration_script": "You are standing in a quiet forest...",
  "sources": [
    {
      "source_id": "forest_ambient_bed",
      "category": "ambient",
      "asset_ref": "mock://forest_ambient_bed.wav",
      "start_sec": 0,
      "end_sec": 60,
      "volume": 0.72,
      "loop": true,
      "position": { "x": 0, "y": 0, "z": 2.5 },
      "motion": {
        "type": "none"
      },
      "fade_in_sec": 2,
      "fade_out_sec": 3,
      "role": "continuous grounding ambience"
    }
  ],
  "world_state": {},
  "mental_state": {}
}
```

### Notes

- Keep the schema human-readable.
- Prioritize clarity and stability over completeness.
- Use normalized coordinates or a documented local coordinate system.

### Acceptance criteria

- JSON is valid.
- JSON updates after each adaptation step.
- Files are saved locally.

---

## FR-10. UI visualization

The frontend should visualize the workflow in a way that makes the MVP understandable.

### Required UI sections

#### A. Prompt panel

- text box for initial prompt
- optional text box for short feedback like `make it calmer`
- start button

#### B. Current scene panel

Show:

- scene type
- atmosphere
- short narration
- current phase
- continuity notes

#### C. Sound library panel

Show all mock assets.
Visually highlight active assets.

#### D. Active sources panel

For current segment, show:

- source name
- category
- volume
- position
- motion type

#### E. EEG analysis panel

Show:

- current window id
- current time range
- key ratios
- rule-based state
- LLM state
- trend
- confidence

#### F. Adaptation rationale panel

Show:

- previous state summary
- current interpreted state
- why the scene changed
- what changed in the sound plan

#### G. Optional simple scene map

If feasible, include a very simple 2D top-down diagram showing sound source positions.
This can be symbolic circles or icons.
No need for detailed graphics.

### Acceptance criteria

- User can understand what the system is doing.
- The app updates across multiple EEG windows.

---

## FR-11. Mock playback timeline behavior

Because real audio playback is not required, simulate the session timeline.

### Required behavior

- Once session starts, step through EEG windows automatically or via a `Next step` button.
- Either behavior is acceptable.
- A manual `Next step` button is preferred for debugging and demos.

### Acceptance criteria

- The user can step through the 120-second EEG sequence.
- Each step updates interpretation and scene JSON.

---

## FR-12. Local file outputs for debugging

The app must save intermediate outputs locally for inspection.

### Required outputs

Create an `outputs/` folder and save:

- extracted EEG feature table
- per-window EEG payloads
- per-window LLM interpretation JSON
- per-window scene update JSON
- latest combined Unity scene JSON

### Acceptance criteria

- A developer can inspect outputs without the UI.

---

## Environment and API requirements

## ENV-1. `.env` support

The OpenAI API key must be stored in a local `.env` file.

### Required file

Create:

`.env`

### Required key

```env
OPENAI_API_KEY=your_key_here
```

### Requirements

- Do not hardcode API keys anywhere in source code.
- Load `.env` using appropriate tooling for the chosen stack.
- Add `.env` to `.gitignore`.

### Acceptance criteria

- The app reads the key from `.env`.
- If the key is missing, the app shows a helpful local error.

---

## ENV-2. Optional model configuration

Allow model name to be configurable via `.env` or a config file.

Example:

```env
OPENAI_MODEL=gpt-4o-mini
```

Fallback to a sensible default if unset.

---

## File and folder structure

Create or normalize toward this structure as much as practical:

```text
project-root/
  app/ or src/
  components/
  scripts/
  data/
    mindMonitor_2026-03-06--17-46-21.csv
    mock_sound_library.json
  outputs/
  prompts/
  lib/
  .env
  .env.example
  .gitignore
  README.md
```

### Suggested important files

```text
README.md
.env.example
prompts/
  eeg_interpreter_prompt.md
  scene_bootstrap_prompt.md
  scene_adaptation_prompt.md

scripts/
  eeg_pipeline.py
  scene_bootstrap.py
  scene_adaptation.py

lib/
  mockSoundLibrary.ts or mock_sound_library.py
  unitySceneSchema.ts or unity_scene_schema.py
```

---

## Suggested implementation plan

## Phase A. Stabilize EEG pipeline first

1. Locate and reuse existing EEG processing code.
2. Refactor it into a reusable script or module.
3. Make file path configurable.
4. Change windowing to work well with a 120-second file.
5. Save feature outputs to `outputs/`.

### Done when

- The app can produce multiple structured windows from the EEG CSV.

---

## Phase B. Build mock sound and JSON pipeline

1. Create the mock sound library JSON.
2. Create the Unity-facing scene JSON schema.
3. Implement prompt-to-scene bootstrap.
4. Save initial scene JSON.

### Done when

- A user prompt can generate a stable initial scene package.

---

## Phase C. Add mental state interpretation

1. Build LLM payload from EEG window features.
2. Add strict JSON schema response.
3. Implement fallback behavior if API fails.
4. Save interpretation outputs.

### Done when

- Each EEG window yields a mental state object.

---

## Phase D. Add scene adaptation

1. Create world state.
2. Build adaptation prompt or rule-assisted planner.
3. Update active sound sources per EEG window.
4. Save updated Unity JSON after each step.

### Done when

- The scene evolves across multiple windows rather than resetting.

---

## Phase E. Build the UI

1. Add prompt input.
2. Add scene panels.
3. Add EEG interpretation panel.
4. Add sound library and active source visualization.
5. Add `Next step` or autoplay controls.

### Done when

- A demo can be run end-to-end locally.

---

## Detailed behavior expectations

## Initial bootstrap behavior

When the prompt is `I want a forest scene`, the initial scene should remain simple.
Do not overcomplicate it.

A good initial result:

- scene type: forest
- atmosphere: soft, enclosed, calm
- narration: grounding and slow
- active sources:
  - forest ambient bed
  - light wind
  - distant birds
  - optional narrator

Do not generate sudden dramatic events in the first segment.

---

## Adaptation behavior examples

### Example 1: user becomes calmer

If EEG interpretation suggests improving relaxation and higher stability:

- maintain forest identity
- reduce discrete bird events
- make wind slightly broader or slower
- lower narration intensity
- optionally add a slow circular ambient motion

### Example 2: user becomes distracted

If EEG interpretation suggests distraction or instability:

- maintain same scene family
- reduce overall complexity
- introduce one subtle directional cue
- make narration slightly more grounding
- avoid sudden new sound families

### Example 3: user is effortfully focusing

If interpretation suggests effortful focus:

- keep ambient present but not dense
- avoid too many discrete events
- use one stable front or side anchor
- keep guidance moderate

---

## Prompting guidance for OpenAI calls

Create three separate prompts rather than one giant prompt.

### Prompt 1: scene bootstrap

Input:

- user prompt
- mock sound library summary

Output:

- initial scene package JSON

### Prompt 2: EEG interpreter

Input:

- structured EEG features
- rule-based state
- previous history summary

Output:

- mental state JSON

### Prompt 3: scene adaptation planner

Input:

- prior world state
- prior scene JSON
- current mental state JSON
- mock sound library summary

Output:

- updated scene package JSON

This separation is preferred for controllability and debugging.

---

## Error handling requirements

### If OpenAI API fails

- Do not crash the app.
- Show a warning in the UI.
- Fall back to rule-based mental state plus deterministic adaptation heuristics.

### If EEG CSV parsing fails

- Show a clear local error message.
- Do not silently fail.

### If mock sound library fails to load

- Fall back to a tiny inline default library.

---

## Minimal deterministic fallback rules

Implement a local fallback planner that can run without OpenAI.

### Suggested fallback rules

If `stable_relaxation`:

- `density = low`
- `motion = slow`
- `guidance = low`
- favor ambient sources

If `settling`:

- `density = medium-low`
- `motion = slow`
- `guidance = medium`

If `effortful_focus`:

- `density = medium`
- `motion = minimal`
- `guidance = medium`
- keep one directional anchor

If `distracted_or_unstable`:

- `density = low`
- `motion = minimal`
- `guidance = medium-high`
- reduce event sounds
- add one grounding directional source

---

## Data contracts

## EEG window payload contract

```json
{
  "window_id": 0,
  "time_range_sec": [0, 60],
  "current_features": {},
  "current_rule_state": "settling",
  "history_summary": [],
  "feature_deltas": {}
}
```

## Mental state contract

```json
{
  "state_label": "settling",
  "confidence": 0.74,
  "trend": "improving",
  "interpretation": "...",
  "attention": 0.58,
  "relaxation": 0.71,
  "stability": 0.62,
  "mind_wandering_risk": 0.3,
  "scene_implication": {
    "density": 0.3,
    "motion_intensity": 0.18,
    "eventfulness": 0.2,
    "guidance_intensity": 0.4,
    "proximity": 0.55
  }
}
```

## Scene package contract

```json
{
  "scene_id": "forest_session_001",
  "segment_id": "segment_001",
  "scene_type": "forest",
  "atmosphere": "quiet morning forest",
  "narrative_brief": "...",
  "narration_script": "...",
  "sources": [],
  "world_state": {},
  "mental_state": {}
}
```

---

## UI polish level

Keep styling simple.
Do not spend time on visual polish before the logic works.

The UI should prioritize legibility:

- clean panels
- readable JSON previews
- obvious active sound highlighting
- visible scene evolution across steps

---

## README requirements

Create a README that explains:

- what this MVP does
- how to install dependencies
- how to create `.env`
- how to run the app locally
- where to place the EEG CSV
- where outputs are saved
- what is mocked versus real

Also create `.env.example` like:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
```

---

## Implementation priorities

Use this priority order:

### Priority 1

- EEG pipeline works on local CSV
- initial scene bootstrap works
- JSON outputs are valid

### Priority 2

- LLM interpretation works
- adaptive scene updates work
- mock sound library is visible

### Priority 3

- polished UI
- simple scene map
- autoplay timeline

---

## What “done” means for this MVP

The MVP is considered complete when all of the following are true:

1. A user can enter a scene prompt locally.
2. The app generates an initial scene package.
3. The app reads the 120-second EEG CSV from disk.
4. The EEG data is converted into multiple structured windows.
5. Each window produces a mental state interpretation.
6. Each interpretation updates the scene plan and Unity JSON.
7. The UI shows prompt, scene, sound library, EEG interpretation, and adaptation rationale.
8. The OpenAI API key is loaded from `.env`.
9. Missing real sound assets do not block the demo.
10. A developer can inspect all outputs in local files.

---

## Final instruction to implementer

Favor **clarity, determinism, and debuggability** over architectural perfection.

This MVP is a research prototype.
The goal is to make the logic of the closed loop visible and runnable on the current local folder, using:

- one local EEG CSV
- mock sound assets
- OpenAI calls via `.env`
- local UI panels
- generated JSON for future Unity use

Do not wait for a full sound library or Unity integration before making the system work.
