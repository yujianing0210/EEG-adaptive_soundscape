# NeuroScape System Design Spec

## 1. Project Goal

NeuroScape is an EEG-adaptive spatial audio meditation system. The user first describes a desired mental world through text. The system generates a meditation scene, previews it, and then enters a real-time session where EEG-derived mental states continuously influence the spatial auditory environment.

The system should not behave like a static audio player. It should behave like a real-time adaptive auditory ecosystem.

---

# 2. Core User Flow

## Page 1 — World Initialization

User sees:

- Title: `NEUROSCAPE`
- Input field: `Describe your world...`
- Example prompts:
  - “I want a forest scene...”
  - “Any place that can bring me calmness...”
  - “Bring me somewhere fun...”

User enters a text prompt.

The prompt may be:

- concrete scene-based: “I want a forest”
- affective goal-based: “I want to feel calm”
- abstract / imaginative: “Take me somewhere inspiring”

After submit, go to loading page.

---

## Page 2 — World Construction

Show:

- soft blurred blob / generative loading visual
- text: `Your world is under construction`

During this state, the system converts:

```text
user input → scene model → sound layer plan → initial spatial audio config
```

Then navigate to preview page.

---

## Page 3 — Scene Preview

Show:

- generated scene type, e.g. `[forest]`
- background image / preview image
- short generated description
- consent notice:
  - EEG data will be monitored during the meditation session

- `ENTER` button

On enter, start real-time session.

---

## Page 4 / 5 — Real-Time Adaptive Session

The session page has three main columns.

### Center Panel — Scene Preview + Spatial Map

Show:

- scene background
- user-centered spatial map
- concentric distance rings:
  - `NEAR: 0–3m`
  - `MIDDLE: 3–6m`
  - `FAR: 6m+`

- user point at center
- active spatial sound sources as moving dots
- meditation guidance text
- timer
- play / pause button

### Left Panel — Scene Design + Sound Library

Show current scene model:

```json
{
  "environment_type": "forest",
  "ambient_layer": [],
  "event_layer": [],
  "action_layer": [],
  "spatial_behavior": [],
  "phase": 1,
  "density": "low",
  "dynamics": "stable"
}
```

Show sound library grouped by:

- Ambient Sound
- Event Sound
- Action Sound

Active sounds should be highlighted.

### Right Panel — Brain State

Show:

- EEG band power:
  - Alpha
  - Beta
  - Theta
  - Delta
  - Gamma

- inferred mental states:
  - Anxiety
  - Attention
  - Stability

- scene change recommendation

Example:

```text
if anxiety ↑:
  reduce event density
  increase low-frequency ambient

if attention ↓:
  add spatial movement
  introduce directional cues
```

---

# 3. Spatial Audio Concept

The spatial auditory experience should be built from three sound layers.

## 3.1 Ambient Sound Layer

Ambient sound defines the environment.

Examples:

- forest bed (30s x 2)
- ocean waves (30s x 2)
- desert wind (30s x 1)
- city distant hum (30s x 1)
- rain ambience (30s x 1)
- (mountain air)

Ambient sound is usually continuous, looping, slow-changing, and spatially diffuse.

Function:

```text
Creates the feeling of being inside a place.
```

Ambient sound should be strongly determined by the user’s initial input.

Example:

```text
User input: “I want a calm forest”
Ambient layer: forest wind, distant leaves, soft low-frequency forest bed
```

---

## 3.2 Event Sound Layer

Event sound creates dynamic spatial moments.

Examples:

- bird calls
- wind gusts
- leaves rustling
- water drops
- distant thunder
- boat horn
- animal movement
- branch cracking

Event sounds are usually short, intermittent, and spatially located.

Function:

```text
Makes the world feel alive and responsive.
```

Event sound should be influenced by both:

1. the initial scene type
2. the user’s EEG-derived mental state

Example:

```text
If attention is low:
  introduce more directional event sounds

If anxiety is high:
  reduce sudden events
  make events softer and farther away
```

---

## 3.3 Action Sound Layer

Action sound reflects the user’s embodied movement.

Examples:

- footsteps on grass
- footsteps on sand
- soft clothing movement
- breathing
- slow hand movement
- walking through leaves

Action sounds are not necessarily spatialized. They are body-centered or user-proximal.

Function:

```text
Enhances embodied presence and first-person experience.
```

Action sound should be determined by:

1. scene type
2. meditation phase
3. interaction mode

Example:

```text
Forest scene:
  slow footsteps on grass
  soft leaf-crunching

Ocean scene:
  slow footsteps on wet sand

Rain scene:
  soft steps on wooden floor or wet ground
```

Action sound is less directly affected by EEG than event sound. It should remain stable unless the system enters a major scene transition.

---

# 4. Scene Data Model

Create a central `SceneModel` object.

```ts
type SceneModel = {
  id: string;
  environmentType: EnvironmentType;
  userIntent: UserIntent;
  emotionalTarget: EmotionalTarget;

  description: string;
  visualTheme: VisualTheme;

  phase: MeditationPhase;
  density: DensityLevel;
  dynamics: DynamicsLevel;

  ambientLayer: AmbientSound[];
  eventLayer: EventSound[];
  actionLayer: ActionSound[];

  spatialBehavior: SpatialBehavior[];
  adaptationPolicy: AdaptationPolicy;
};
```

---

## 4.1 Environment Type

```ts
type EnvironmentType =
  | "forest"
  | "ocean"
  | "rain"
  | "desert"
  | "mountain"
  | "city"
  | "river"
  | "night"
  | "abstract";
```

---

## 4.2 User Intent

```ts
type UserIntent = {
  rawInput: string;
  sceneKeywords: string[];
  affectiveKeywords: string[];
  abstractKeywords: string[];
};
```

Example:

```json
{
  "rawInput": "I want a forest scene to get relaxed",
  "sceneKeywords": ["forest"],
  "affectiveKeywords": ["relaxed", "calm"],
  "abstractKeywords": []
}
```

---

## 4.3 Emotional Target

```ts
type EmotionalTarget = {
  calmness: number;
  focus: number;
  imagination: number;
  grounding: number;
  energy: number;
};
```

Scale: `0–1`.

Example:

```json
{
  "calmness": 0.9,
  "focus": 0.5,
  "imagination": 0.3,
  "grounding": 0.8,
  "energy": 0.2
}
```

---

# 5. Sound Data Models

## 5.1 Base Sound Object

```ts
type SoundBase = {
  id: string;
  name: string;
  layer: "ambient" | "event" | "action";
  sceneTags: EnvironmentType[];
  affectTags: string[];
  audioUrl?: string;
  isActive: boolean;
  volume: number;
};
```

---

## 5.2 Ambient Sound

```ts
type AmbientSound = SoundBase & {
  layer: "ambient";
  loop: true;
  texture: "diffuse" | "directional" | "low_frequency" | "wide";
  intensity: number;
};
```

Example:

```json
{
  "id": "forest_wind_bed",
  "name": "Soft Forest Wind",
  "layer": "ambient",
  "sceneTags": ["forest"],
  "affectTags": ["calm", "grounding"],
  "loop": true,
  "texture": "diffuse",
  "intensity": 0.4,
  "isActive": true,
  "volume": 0.6
}
```

---

## 5.3 Event Sound

```ts
type EventSound = SoundBase & {
  layer: "event";
  loop: false;
  triggerMode: "scheduled" | "random" | "eeg_triggered";
  frequency: number;
  suddenness: number;
  spatialPosition: SpatialPosition;
  movementPath?: MovementPath;
};
```

Example:

```json
{
  "id": "bird_call_far_right",
  "name": "Distant Bird Call",
  "layer": "event",
  "sceneTags": ["forest"],
  "affectTags": ["attention", "alive"],
  "triggerMode": "eeg_triggered",
  "frequency": 0.3,
  "suddenness": 0.2,
  "spatialPosition": {
    "distanceZone": "far",
    "angle": 45,
    "elevation": 20
  },
  "isActive": true,
  "volume": 0.5
}
```

---

## 5.4 Action Sound

```ts
type ActionSound = SoundBase & {
  layer: "action";
  loop: false;
  bodyAnchored: true;
  actionType: "footstep" | "breath" | "fabric" | "gesture";
  rhythm: "slow" | "medium" | "still";
};
```

Example:

```json
{
  "id": "soft_grass_footsteps",
  "name": "Soft Grass Footsteps",
  "layer": "action",
  "sceneTags": ["forest"],
  "affectTags": ["embodied", "grounding"],
  "bodyAnchored": true,
  "actionType": "footstep",
  "rhythm": "slow",
  "isActive": true,
  "volume": 0.35
}
```

---

# 6. Spatial Data Model

```ts
type SpatialPosition = {
  distanceZone: "near" | "middle" | "far";
  angle: number;
  elevation: number;
};
```

```ts
type MovementPath = {
  type: "static" | "linear" | "orbit" | "approach" | "recede" | "overhead_pass";
  start: SpatialPosition;
  end?: SpatialPosition;
  duration: number;
  repeat: boolean;
};
```

Example:

```json
{
  "type": "overhead_pass",
  "start": {
    "distanceZone": "far",
    "angle": -90,
    "elevation": 40
  },
  "end": {
    "distanceZone": "far",
    "angle": 90,
    "elevation": 40
  },
  "duration": 8,
  "repeat": false
}
```

---

# 7. EEG Data Model

```ts
type EEGState = {
  timestamp: number;

  bands: {
    alpha: number;
    beta: number;
    theta: number;
    delta: number;
    gamma: number;
  };

  mentalState: {
    anxiety: number;
    attention: number;
    stability: number;
  };

  trend: {
    anxiety: "up" | "down" | "stable";
    attention: "up" | "down" | "stable";
    stability: "up" | "down" | "stable";
  };
};
```

Scale for mental states: `0–10`.

---

# 8. Adaptation Logic

The system should map EEG changes to sound layer changes.

## 8.1 General Rule

```text
Initial user input determines the world.
EEG determines how the world behaves over time.
```

More specifically:

```text
User input → environment type + emotional target + initial sound set

EEG change → density + dynamics + event frequency + spatial movement
```

---

## 8.2 Layer-Specific Adaptation

### Ambient Layer

Ambient is mostly stable.

Affected by:

- initial input
- scene type
- emotional target
- large EEG shifts only

Rules:

```ts
if anxiety increases strongly:
  increase calming ambient volume
  reduce high-frequency ambient
  add low-frequency diffuse texture

if stability increases:
  keep ambient stable
  reduce unnecessary changes

if attention drops:
  slightly increase texture variation
```

---

### Event Layer

Event is the most adaptive layer.

Affected by:

- attention
- anxiety
- stability
- meditation phase

Rules:

```ts
if attention decreases:
  increase event frequency slightly
  add directional cues
  use middle/far spatial events

if anxiety increases:
  decrease event suddenness
  reduce event frequency
  move events farther away
  avoid sharp or surprising sounds

if stability increases:
  allow richer but still gentle event patterns

if stability decreases:
  simplify event layer
```

---

### Action Layer

Action is embodied and stable.

Affected by:

- scene type
- meditation phase
- major transition only

Rules:

```ts
if phase is settling:
  use slow breathing or very soft body-centered sounds

if phase is immersion:
  allow slow footsteps or gentle movement sounds

if anxiety is high:
  reduce footsteps
  emphasize breathing or stillness

if attention is low:
  add subtle footstep rhythm to create embodied continuity
```

---

# 9. Meditation Phase State Machine

The session should have a phase-based structure.

```ts
type MeditationPhase =
  | "initializing"
  | "settling"
  | "immersion"
  | "adaptive_shift"
  | "integration"
  | "closing";
```

---

## 9.1 Phase Timeline

For MVP, use a simple time-based phase system.

```text
0–30s: settling
30–90s: immersion
90–120s: adaptive_shift
120s+: integration / closing
```

If using 120-second EEG mock data:

```text
0–30s:
  establish scene

30–60s:
  first EEG-based update

60–90s:
  second EEG-based update

90–120s:
  final adaptation and soft closing
```

---

## 9.2 Phase Behavior

### Settling

Goal:

```text
Help user enter the scene.
```

Sound behavior:

- low density
- stable ambient
- minimal event sound
- possible body-centered breathing

---

### Immersion

Goal:

```text
Make the scene feel alive.
```

Sound behavior:

- ambient continues
- event sounds appear occasionally
- spatial map begins to animate
- action sounds may be introduced

---

### Adaptive Shift

Goal:

```text
Respond to EEG-derived state changes.
```

Sound behavior:

- modify event frequency
- update spatial positions
- update guidance text
- show recommendation

---

### Integration

Goal:

```text
Stabilize the experience after adaptation.
```

Sound behavior:

- reduce excessive movement
- maintain useful changes
- return to coherent scene identity

---

### Closing

Goal:

```text
Bring user back.
```

Sound behavior:

- reduce density
- fade event sounds
- keep ambient soft
- stop action sounds gradually

---

# 10. System State Machine

Use a global app state.

```ts
type AppState =
  | "home"
  | "constructing_world"
  | "scene_preview"
  | "session_running"
  | "session_paused"
  | "session_complete";
```

---

## 10.1 Transitions

```text
home
  submit prompt →
constructing_world
  scene generated →
scene_preview
  click ENTER →
session_running
  click pause →
session_paused
  click resume →
session_running
  timer ends →
session_complete
```

---

# 11. API / Service Design

## 11.1 Generate Scene API

```ts
POST / api / generate - scene;
```

Input:

```json
{
  "userInput": "I want a forest scene to get relaxed"
}
```

Output:

```json
{
  "sceneModel": {
    "environmentType": "forest",
    "description": "You are standing in a quiet forest clearing...",
    "emotionalTarget": {
      "calmness": 0.9,
      "focus": 0.5,
      "imagination": 0.3,
      "grounding": 0.8,
      "energy": 0.2
    },
    "ambientLayer": [],
    "eventLayer": [],
    "actionLayer": [],
    "phase": "settling",
    "density": "low",
    "dynamics": "stable"
  }
}
```

---

## 11.2 Get EEG Frame API

For MVP, this can read from a prerecorded EEG CSV or mock data.

```ts
GET /api/eeg-frame?t=30
```

Output:

```json
{
  "timestamp": 30,
  "bands": {
    "alpha": 0.4,
    "beta": 0.7,
    "theta": 0.5,
    "delta": 0.3,
    "gamma": 0.4
  },
  "mentalState": {
    "anxiety": 8.2,
    "attention": 5.4,
    "stability": 6.0
  },
  "trend": {
    "anxiety": "up",
    "attention": "down",
    "stability": "stable"
  }
}
```

---

## 11.3 Adapt Scene API

```ts
POST / api / adapt - scene;
```

Input:

```json
{
  "sceneModel": {},
  "eegState": {},
  "sessionTime": 30
}
```

Output:

```json
{
  "updatedSceneModel": {},
  "recommendation": {
    "summary": "Anxiety increased and attention decreased.",
    "actions": [
      "Reduce event density",
      "Increase low-frequency ambient",
      "Add gentle directional cues"
    ]
  },
  "spatialUpdates": [
    {
      "soundId": "bird_call_far_right",
      "position": {
        "distanceZone": "far",
        "angle": 45,
        "elevation": 20
      },
      "movementPath": {
        "type": "linear",
        "duration": 6,
        "repeat": false
      }
    }
  ],
  "guidanceText": "Notice your breath while soft forest air surrounds you."
}
```

---

# 12. LLM Prompt Design

## 12.1 Scene Generation Prompt

Use this prompt to convert user input into structured scene data.

```text
You are generating a meditation soundscape scene for an EEG-adaptive spatial audio system.

The user input is:
{USER_INPUT}

Generate a structured scene model.

The scene must include:
1. environment type
2. emotional target
3. scene description
4. ambient sound layer
5. event sound layer
6. action sound layer
7. initial density
8. initial dynamics
9. adaptation policy

Important:
- Ambient sound defines the environment.
- Event sound creates dynamic spatial moments.
- Action sound reflects embodied human movement.
- The initial user input should strongly determine the environment and emotional target.
- EEG changes will later modify density, dynamics, event frequency, and spatial behavior.

Return valid JSON only.
```

---

## 12.2 Scene Adaptation Prompt

```text
You are adapting a meditation soundscape based on EEG-derived mental states.

Current scene:
{SCENE_MODEL}

Current EEG state:
{EEG_STATE}

Session time:
{SESSION_TIME}

Adapt the scene according to these principles:

- Preserve the original scene identity unless there is a major shift.
- Ambient sound should remain mostly stable.
- Event sound should be the most responsive layer.
- Action sound should remain body-centered and stable.
- If anxiety increases, reduce sudden events and increase calming ambient support.
- If attention decreases, add gentle spatial movement or directional cues.
- If stability decreases, simplify the scene.
- If stability increases, allow richer but still gentle spatial detail.

Return valid JSON with:
1. updatedSceneModel
2. recommendation
3. spatialUpdates
4. guidanceText
```

---

# 13. Frontend Components

Recommended components:

```text
HomePage
ConstructingWorldPage
ScenePreviewPage
SessionPage
SpatialMap
SceneDesignPanel
SoundLibraryPanel
BrainStatePanel
EEGBandChart
MentalStateCards
RecommendationBox
TimerControls
```

---

# 14. MVP Implementation Priorities

## Must Have

- Implement full user flow from page 1 to session page
- Store scene model globally
- Mock or CSV-based EEG state updates
- Show real-time timer
- Update brain state every 30 seconds
- Generate scene recommendation based on EEG
- Show active sounds in three layers
- Animate spatial sound dots on the center map

## Nice to Have

- Actual audio playback
- Real spatial audio rendering
- Real LLM API integration
- User feedback input during session
- Scene regeneration based on feedback

For MVP, mock audio and mock LLM output are acceptable as long as the data structure is ready for real integration.

---

# 15. Key Design Principle

The core logic should follow this rule:

```text
The user creates the world.
The EEG changes the behavior of the world.
The sound layers make the world perceivable:
ambient = place
event = life
action = body
```

Final system behavior:

```text
User input determines what world the user enters.
EEG determines how that world breathes, moves, simplifies, or becomes richer over time.
```
