from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import random
from dotenv import load_dotenv
from openai import OpenAI

from lib.mock_sound_library import load_audio_library
from lib.unity_scene_schema import new_scene_id, base_world_state, build_unity_scene

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

PROMPT_DIR = Path("prompts")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def select_scene_family(user_prompt: str) -> str:
    text = user_prompt.lower()
    if "beach" in text or "ocean" in text:
        return "beach"
    if "forest" in text or "woods" in text:
        return "forest"
    if "night" in text:
        return "night_forest"
    return "forest"


def choose_sources(library: List[Dict[str, Any]], scene_family: str, density: float) -> List[Dict[str, Any]]:
    # Filter by tags
    filtered = [a for a in library if scene_family.split("_")[0] in " ".join(a.get("tags", [])) or scene_family in " ".join(a.get("tags", []))]
    if not filtered:
        filtered = library
    # density 0-1 -> pick number of sources
    num = max(2, min(5, int(2 + density * 3)))
    random.shuffle(filtered)
    return filtered[:num]


def place_sources(assets: List[Dict[str, Any]], density: float) -> List[Dict[str, Any]]:
    placed = []
    base_positions = [
        {"x": 0, "y": 0, "z": 2.5},
        {"x": -2.0, "y": 0, "z": 1.5},
        {"x": 2.0, "y": 0, "z": 1.5},
        {"x": 0.5, "y": 0, "z": -1.5},
        {"x": -1.2, "y": 0, "z": -1.0},
    ]
    for i, asset in enumerate(assets):
        pos = base_positions[i % len(base_positions)]
        placed.append({
            "source_id": asset["asset_id"],
            "category": asset.get("category", "ambient"),
            "asset_ref": asset.get("mock_file_path", f"mock://{asset['asset_id']}.wav"),
            "start_sec": 0,
            "end_sec": 60,
            "volume": round(asset.get("default_volume", 0.6) * (0.8 + 0.4 * density), 2),
            "loop": asset.get("category") == "ambient",
            "position": pos,
            "motion": {"type": "none" if asset.get("category") != "ambient" else "slow_orbit"},
            "fade_in_sec": 2,
            "fade_out_sec": 3,
            "role": asset.get("description", ""),
        })
    return placed


# ---------------------------------------------------------------------------
# Scene bootstrap
# ---------------------------------------------------------------------------

def bootstrap_scene(user_prompt: str) -> Dict[str, Any]:
    library = load_audio_library()
    scene_family = select_scene_family(user_prompt)

    if client:
        prompt = read_prompt("scene_bootstrap_prompt.md")
        messages = [
            {"role": "system", "content": prompt or "You draft calm spatial meditation scenes."},
            {"role": "user", "content": json.dumps({"user_prompt": user_prompt, "library": library})},
        ]
        try:
            res = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            return json.loads(res.choices[0].message.content)
        except Exception:
            pass  # fall back to deterministic

    # Fallback deterministic bootstrap
    assets = choose_sources(library, scene_family, density=0.4)
    placed = place_sources(assets, density=0.4)
    scene_id = new_scene_id(scene_family)
    world_state = base_world_state(scene_family, [a["asset_id"] for a in assets])
    narration = "Notice your breath while soft forest air surrounds you."
    return build_unity_scene(
        scene_id=scene_id,
        segment_id="segment_000",
        scene_type=scene_family,
        atmosphere="quiet, enclosed, calm",
        narration_script=narration,
        sources=placed,
        duration_sec=60,
        world_state=world_state,
        mental_state={"state_label": "settling", "source": "rule"},
    )


# ---------------------------------------------------------------------------
# EEG interpretation
# ---------------------------------------------------------------------------

def interpret_window(payload: dict) -> Dict[str, Any]:
    rule_state = payload.get("current_rule_state")
    features = payload.get("current_features", {})

    if client:
        prompt = read_prompt("eeg_interpreter_prompt.md")
        messages = [
            {"role": "system", "content": prompt or "You interpret EEG feature summaries for meditation stability."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            res = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            return json.loads(res.choices[0].message.content)
        except Exception:
            pass

    # deterministic fallback
    return {
        "state_label": rule_state,
        "confidence": 0.42,
        "trend": "stable",
        "interpretation": f"Fallback: continuing {rule_state} based on ratios",
        "attention": features.get("attention_score", 0.5),
        "relaxation": features.get("relaxation_score", 0.5),
        "stability": features.get("stability_score", 0.5),
        "mind_wandering_risk": 1 - features.get("attention_score", 0.5),
        "scene_implication": {
            "density": 0.35 if rule_state == "stable_relaxation" else 0.5,
            "motion_intensity": 0.2,
            "eventfulness": 0.2,
            "guidance_intensity": 0.4,
            "proximity": 0.5,
        },
    }


# ---------------------------------------------------------------------------
# Scene adaptation
# ---------------------------------------------------------------------------

def adapt_scene(previous_scene: Dict[str, Any], mental_state: Dict[str, Any], library: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    library = library or load_audio_library()
    state_label = mental_state.get("state_label", "settling")
    implication = mental_state.get("scene_implication", {})
    density = implication.get("density", 0.4)

    assets = choose_sources(library, previous_scene.get("scene_type", "forest"), density)
    placed = place_sources(assets, density)

    atmosphere = previous_scene.get("atmosphere", "quiet forest")
    notes = previous_scene.get("world_state", {}).get("continuity_notes", "")
    narration = previous_scene.get("narration_script", "")

    world_state = previous_scene.get("world_state", {}).copy()
    world_state["active_sources"] = [a["asset_id"] for a in assets]
    world_state.setdefault("retired_sources", [])
    world_state.setdefault("continuity_notes", notes)

    segment_id = f"segment_{int(previous_scene.get('segment_id', 'segment_000').split('_')[-1]) + 1:03d}"

    return build_unity_scene(
        scene_id=previous_scene.get("scene_id"),
        segment_id=segment_id,
        scene_type=previous_scene.get("scene_type", "forest"),
        atmosphere=atmosphere,
        narration_script=narration,
        sources=placed,
        duration_sec=60,
        world_state=world_state,
        mental_state=mental_state,
    )
