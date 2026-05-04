# 🧠 EEG Adaptive Soundscape — Debug README (May 2026)

## 📌 Project Overview

This project builds a **real-time closed-loop system**:

```text
EEG → Feature Extraction → LLM Interpretation → Scene Adaptation → Unity Audio
```

Core components:

* Flask UI (`app.py`)
* EEG pipeline (`muse_realtime.py`)
* Scene logic (`scene_logic.py`)
* Unity bridge (`server.py`)
* Translator (`translator.py`)

---

# 🚨 Current Debug Issues Summary

## ❗ 1. Unity shows:

```text
❌ Scene file not found
```

### Root Cause

* `current_unity_scene.json` is **not generated early enough**
* Unity server (`server.py`) reads file every second
* But file is only written in `/step` (not bootstrap)

### Fix

In `app.py` → `/bootstrap`:

```python
write_json(scene, "initial_scene.json")
write_json(scene, "current_unity_scene.json")  # ADD THIS
```

---

## ❗ 2. Realtime EEG not working

### Root Cause

Realtime mode does NOT actually start OSC server.

You only set:

```python
STATE["realtime_active"] = True
```

But never call:

```python
start_realtime_session()
```

---

### Fix

Import:

```python
from muse_realtime import start_realtime_session
```

Then inside `/bootstrap`:

```python
if eeg_mode == "realtime":
    start_realtime_session()
```

---

## ❗ 3. Crash:

```text
AttributeError: 'str' object has no attribute 'get'
```

### Location

```text
scripts/scene_logic.py → adapt_scene()
```

---

### Root Cause

LLM output format mismatch:

Expected:

```json
"scene_implication": {
  "density": 0.4
}
```

Actual:

```json
"audio_action": {
  "sound_density": "reduce"
}
```

(from `muse_realtime.py`)

---

### Fix (robust fallback)

```python
implication = mental.get("scene_implication", {})

if not isinstance(implication, dict):
    implication = {}

audio_action = mental.get("audio_action", {})

if audio_action and not implication:
    density_map = {
        "increase": 0.8,
        "slightly_increase": 0.6,
        "keep": 0.4,
        "slightly_reduce": 0.3,
        "reduce": 0.2,
    }

    implication = {
        "density": density_map.get(audio_action.get("sound_density"), 0.4),
        "motion_intensity": 0.3,
        "spatial_spread": 0.5,
    }

density = implication.get("density", 0.4)
```

---

## ❗ 4. Potential crash in translator (hidden bug)

### Location

`translator.py`

```python
motion = normalize_motion(motion)
```

Inside:

```python
mtype = motion.get("type")
```

If `motion` is string → crash

---

### Fix

```python
if not isinstance(motion, dict):
    return None
```

---

## ❗ 5. Python version issue (critical)

### Error

```text
metadata-generation-failed (numpy)
```

### Root Cause

Using:

```text
Python 3.14 ❌
```

### Fix

Use:

```text
Python 3.11 ✅
```

---

# ⚙️ Correct Run Pipeline

## 🧪 Recorded mode

```text
1. python app.py
2. http://127.0.0.1:5001
3. Bootstrap
4. Next EEG window
5. Check outputs/current_unity_scene.json
6. python server.py
7. Unity Play
```

---

## ⚡ Realtime mode

```text
1. python app.py
2. Bootstrap (Realtime)
3. start_realtime_session() must run
4. Wait for EEG data
5. python server.py
6. Unity Play
```

---

# 📂 File Responsibilities

| File               | Role                   |
| ------------------ | ---------------------- |
| `app.py`           | main controller        |
| `muse_realtime.py` | EEG streaming + LLM    |
| `scene_logic.py`   | scene adaptation       |
| `server.py`        | Unity websocket        |
| `translator.py`    | scene → Unity commands |

---

# 🧠 Key Design Insight

This is a **multi-stage pipeline system**:

```text
EEG → Payload → LLM → JSON → Scene → Unity
```

Common failure pattern:

```text
❌ One stage returns wrong data type → downstream crashes
```

This matches known challenges in multi-library debugging where systems fail due to interface mismatch rather than syntax errors ([arXiv][1])

---

# 🔥 Debug Strategy (for VS Code Codex)

When debugging, check:

### 1️⃣ Data shape at each stage

```python
print(type(mental))
print(mental)
```

---

### 2️⃣ File existence

```powershell
dir outputs
```

---

### 3️⃣ Pipeline flow

```text
Is EEG arriving?
Is JSON written?
Is Unity reading?
```
