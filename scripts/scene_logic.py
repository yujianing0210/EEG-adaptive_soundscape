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
AUDIO_VOLUME_BOOST = float(os.getenv("AUDIO_VOLUME_BOOST", 1.0))

PROMPT_DIR = Path("prompts")

SCENE_TAG_ALIASES = {
    "forest": {"forest", "woods", "woodland", "leaf", "bird", "natural"},
    "night_forest": {"forest", "woods", "woodland", "night", "leaf", "bird", "natural"},
    "ocean": {"ocean", "beach", "sea", "seaside", "coast", "coastal", "water", "wave", "waves", "swell"},
}

SCENE_COPY = {
    "forest": {
        "atmosphere": "quiet forest air with soft organic movement",
        "narration": "Notice your breath while soft forest air surrounds you.",
    },
    "night_forest": {
        "atmosphere": "dim night forest with slow sheltered movement",
        "narration": "Let the darker forest settle around you as your breath finds an easy rhythm.",
    },
    "ocean": {
        "atmosphere": "open seaside air with steady waves and a wide horizon",
        "narration": "Let the rhythm of the shoreline meet your breath, arriving and receding slowly.",
    },
}


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
    if any(token in text for token in ["beach", "ocean", "sea", "seaside", "coast", "shore", "wave"]):
        return "ocean"
    if "night" in text:
        return "night_forest"
    if any(token in text for token in ["forest", "woods", "woodland", "tree", "leaf", "bird"]):
        return "forest"
    return "forest"


def choose_sources(library: List[Dict[str, Any]], scene_family: str, density: float) -> List[Dict[str, Any]]:
    aliases = SCENE_TAG_ALIASES.get(scene_family, {scene_family})

    def searchable_text(asset: Dict[str, Any]) -> str:
        values = [
            asset.get("asset_id", ""),
            asset.get("label", ""),
            asset.get("description", ""),
            asset.get("asset_ref", ""),
            " ".join(asset.get("tags", [])),
        ]
        return " ".join(values).lower()

    filtered = [asset for asset in library if any(alias in searchable_text(asset) for alias in aliases)]
    if not filtered:
        filtered = [asset for asset in library if asset.get("category") == "ambient"] or library

    # density 0-1 -> pick number of sources
    num = max(2, min(5, int(2 + density * 3)))
    ambient = [asset for asset in filtered if asset.get("category") == "ambient"]
    events = [asset for asset in filtered if asset.get("category") != "ambient"]
    random.shuffle(ambient)
    random.shuffle(events)
    selected = (ambient[:1] + events + ambient[1:])[:min(num, len(filtered))]
    return selected or filtered[:num]


def scene_uses_family_assets(scene: Dict[str, Any], scene_family: str) -> bool:
    aliases = SCENE_TAG_ALIASES.get(scene_family, {scene_family})
    sources = scene.get("sources", [])
    if not sources:
        return False
    source_text = " ".join(
        " ".join(str(source.get(key, "")) for key in ["source_id", "asset_ref", "role", "category"])
        for source in sources
    ).lower()
    return any(alias in source_text for alias in aliases)


def normalize_scene_assets(scene: Dict[str, Any], library: List[Dict[str, Any]], scene_family: str) -> Optional[Dict[str, Any]]:
    library_by_id = {asset.get("asset_id"): asset for asset in library}
    library_by_ref = {asset.get("asset_ref"): asset for asset in library if asset.get("asset_ref")}
    library_by_clip = {
        Path(str(asset.get("asset_ref", asset.get("asset_id", "")))).stem: asset
        for asset in library
    }

    normalized_sources = []
    for source in scene.get("sources", []):
        asset = (
            library_by_id.get(source.get("source_id"))
            or library_by_id.get(source.get("asset_id"))
            or library_by_ref.get(source.get("asset_ref"))
            or library_by_clip.get(Path(str(source.get("asset_ref", ""))).stem)
        )
        if asset is None:
            continue

        merged = dict(source)
        merged["source_id"] = asset["asset_id"]
        merged["category"] = asset.get("category", merged.get("category", "ambient"))
        merged["asset_ref"] = asset.get("asset_ref") or asset.get("mock_file_path") or merged.get("asset_ref")
        merged["volume"] = min(0.85, float(merged.get("volume", asset.get("default_volume", 0.6))) * AUDIO_VOLUME_BOOST)
        merged["loop"] = bool(merged.get("loop", asset.get("category") == "ambient"))
        if merged["category"] != "ambient":
            merged["repeat_count"] = int(merged.get("repeat_count", 2))
            merged["repeat_interval_sec"] = float(merged.get("repeat_interval_sec", 8.0))
        merged.setdefault("position", {"x": 0, "y": 0, "z": 2.5})
        merged.setdefault("motion", {"type": "slow_orbit"} if asset.get("category") != "ambient" else {"type": "none"})
        merged.setdefault("role", asset.get("description", ""))
        normalized_sources.append(merged)

    scene["sources"] = normalized_sources
    scene["scene_type"] = scene_family
    scene.setdefault("world_state", {})
    scene["world_state"]["active_sources"] = [source["source_id"] for source in normalized_sources]
    scene["world_state"]["scene_family"] = scene_family

    if not normalized_sources or not scene_uses_family_assets(scene, scene_family):
        return None
    return scene


def fallback_bootstrap_scene(user_prompt: str, library: List[Dict[str, Any]], scene_family: str) -> Dict[str, Any]:
    assets = choose_sources(library, scene_family, density=0.4)
    placed = place_sources(assets, density=0.4)
    scene_id = new_scene_id(scene_family)
    world_state = base_world_state(scene_family, [a["asset_id"] for a in assets])
    copy = SCENE_COPY.get(scene_family, SCENE_COPY["forest"])
    return build_unity_scene(
        scene_id=scene_id,
        segment_id="segment_000",
        scene_type=scene_family,
        atmosphere=copy["atmosphere"],
        narration_script=copy["narration"],
        sources=placed,
        duration_sec=60,
        world_state=world_state,
        mental_state={"state_label": "settling", "source": "rule", "user_prompt": user_prompt},
    )


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
        base_volume = asset.get("default_volume", 0.6)
        volume = min(0.85, base_volume * AUDIO_VOLUME_BOOST * (0.9 + 0.2 * density))
        placed.append({
            "source_id": asset["asset_id"],
            "category": asset.get("category", "ambient"),
            "asset_ref": asset.get("asset_ref") or asset.get("mock_file_path") or f"mock://{asset['asset_id']}.wav",
            "start_sec": 0,
            "end_sec": 60,
            "volume": round(volume, 2),
            "loop": asset.get("category") == "ambient",
            "repeat_count": 1 if asset.get("category") == "ambient" else max(2, min(6, int(2 + density * 5))),
            "repeat_interval_sec": 0 if asset.get("category") == "ambient" else round(5 + (1 - density) * 6 + i * 1.5, 1),
            "position": pos,
            "motion": {"type": "slow_orbit"} if asset.get("category") != "ambient" else {"type": "none"},
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
            scene = json.loads(res.choices[0].message.content)
            scene = normalize_scene_assets(scene, library, scene_family)
            if scene is not None:
                scene.setdefault("mental_state", {})
                scene["mental_state"]["source"] = "llm"
                return scene
        except Exception:
            pass  # fall back to deterministic

    return fallback_bootstrap_scene(user_prompt, library, scene_family)


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

    implication_by_state = {
        "stable_relaxation": {
            "density": 0.32,
            "motion_intensity": 0.18,
            "eventfulness": 0.15,
            "guidance_intensity": 0.25,
            "proximity": 0.7,
        },
        "settling": {
            "density": 0.48,
            "motion_intensity": 0.28,
            "eventfulness": 0.22,
            "guidance_intensity": 0.4,
            "proximity": 0.55,
        },
        "effortful_focus": {
            "density": 0.58,
            "motion_intensity": 0.38,
            "eventfulness": 0.28,
            "guidance_intensity": 0.35,
            "proximity": 0.5,
        },
        "distracted_or_unstable": {
            "density": 0.72,
            "motion_intensity": 0.12,
            "eventfulness": 0.08,
            "guidance_intensity": 0.65,
            "proximity": 0.85,
        },
    }

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
        "scene_implication": implication_by_state.get(rule_state, implication_by_state["settling"]),
    }


# ---------------------------------------------------------------------------
# Scene adaptation
# ---------------------------------------------------------------------------

def adapt_scene(previous_scene: Dict[str, Any], mental_state: Dict[str, Any], library: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    library = library or load_audio_library()
    state_label = mental_state.get("state_label", "settling")
    implication = mental_state.get("scene_implication", {})
    if not isinstance(implication, dict):
        implication = {}

    audio_action = mental_state.get("audio_action", {})
    if isinstance(audio_action, dict) and audio_action and not implication:
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
    motion_intensity = implication.get("motion_intensity", 0.25)
    spatial_spread = implication.get("spatial_spread", implication.get("proximity", 0.5))

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
    segment_num = int(segment_id.split("_")[-1])
    for i, source in enumerate(placed):
        if source.get("category") == "ambient":
            source["motion"] = {
                "type": "orbit",
                "speed": round(0.03 + motion_intensity * 0.08, 2),
                "radius": round(0.25 + spatial_spread * 0.35, 2),
            }
        elif source.get("category") == "event":
            source["motion"] = {
                "type": "orbit",
                "speed": round(0.18 + motion_intensity * 0.55 + (i * 0.04), 2),
                "radius": round(0.9 + spatial_spread * 1.1 + (segment_num % 2) * 0.2, 2),
            }
        source["volume"] = round(min(0.8, source.get("volume", 0.6) * (0.82 + density * 0.16)), 2)

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
