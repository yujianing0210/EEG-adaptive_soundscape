import json
import os
from pathlib import Path
from typing import List, Dict, Optional

AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac"}
DEFAULT_LIBRARY = [
    {
        "asset_id": "forest_ambient_bed",
        "label": "Forest ambient bed",
        "category": "ambient",
        "description": "Soft continuous forest bed with light leaves",
        "asset_ref": "mock://forest_ambient_bed.wav",
        "default_duration_sec": 60,
        "default_volume": 0.72,
        "spatial_profile": "broad_front",
        "tags": ["forest", "calm", "continuous"],
    },
    {
        "asset_id": "light_wind_through_leaves",
        "label": "Light wind through leaves",
        "category": "ambient",
        "description": "Gentle wind moving branches",
        "asset_ref": "mock://light_wind.wav",
        "default_duration_sec": 45,
        "default_volume": 0.55,
        "spatial_profile": "slow_pan",
        "tags": ["forest", "wind", "motion"],
    },
]


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS


def build_asset_entry(path: Path) -> Dict[str, object]:
    asset_id = path.stem
    label = asset_id.replace("_", " ").title()
    category = "ambient"
    if any(token in asset_id for token in ["horn", "run", "walking", "hailang"]):
        category = "event"
    if any(token in asset_id for token in ["narration", "voice"]):
        category = "narration"

    return {
        "asset_id": asset_id,
        "label": label,
        "category": category,
        "description": label,
        "asset_ref": str(Path("audio_lib") / path.name).replace("\\", "/"),
        "default_duration_sec": 60,
        "default_volume": 0.7,
        "spatial_profile": "broad_front",
        "tags": [asset_id],
    }


def build_unity_resource_entry(path: Path, resources_dir: Path) -> Dict[str, object]:
    relative = path.relative_to(resources_dir).with_suffix("")
    asset_ref = str(relative).replace("\\", "/")
    asset_id = path.stem
    searchable = f"{asset_id} {asset_ref}".lower()

    category = "ambient"
    if any(token in searchable for token in ["step", "walk", "walking", "run", "breath", "body", "action"]):
        category = "action"
    elif any(token in searchable for token in ["bird", "leaf", "horn", "plane", "creak", "event", "cue"]):
        category = "event"
    if any(token in searchable for token in ["narration", "voice", "guide"]):
        category = "narration"

    tags = set(asset_id.replace("-", "_").split("_"))
    tags.update(part.lower() for part in relative.parts)
    if any(token in searchable for token in ["ocean", "sea", "beach", "wave", "hailang", "water"]):
        tags.update(["ocean", "beach", "water", "wave"])
    if any(token in searchable for token in ["horn", "boat", "ship", "plane"]):
        tags.update(["ocean", "beach", "far"])
    if any(token in searchable for token in ["forest", "bird", "leaf", "wood", "tree"]):
        tags.update(["forest", "natural"])
    if category == "action":
        tags.update(["common", "action", "body", "grounding", "near", "forest", "ocean", "beach"])

    default_motion = {"type": "none"}
    if category == "ambient" and any(token in searchable for token in ["wind", "breeze"]):
        default_motion = {"type": "drift", "duration": 16.0, "repeat": True}
    elif category == "event" and any(token in searchable for token in ["bird", "seagull"]):
        default_motion = {"type": "orbit", "speed": 0.12, "radius": 1.6}
    elif category == "event" and any(token in searchable for token in ["horn", "boat", "ship", "plane"]):
        default_motion = {"type": "approach_recede", "duration": 9.0, "repeat": False, "pass_count": 1}
    elif category == "event" and any(token in searchable for token in ["leaf", "creak"]):
        default_motion = {"type": "local_random", "radius": 0.4, "speed": 0.04}

    return {
        "asset_id": asset_id,
        "label": asset_id.replace("_", " ").replace("-", " ").title(),
        "layer": category,
        "role": category,
        "category": category,
        "description": f"Unity Resources audio clip: {asset_ref}",
        "asset_ref": asset_ref,
        "default_duration_sec": 60,
        "default_volume": 0.7,
        "recommended_volume": 0.42 if category == "ambient" else 0.24,
        "recommended_distance": "wide" if category == "ambient" else ("near" if category == "action" else "far"),
        "spatial_profile": "broad_front" if category == "ambient" else "point",
        "spatial_behavior": ["wide"] if category == "ambient" else (["body_anchored"] if category == "action" else ["point"]),
        "default_motion": default_motion,
        "repeat_count": 1,
        "repeat_interval_sec": 2.5 if category == "event" else 0,
        "tags": sorted(tag for tag in tags if tag),
    }


def load_audio_library(path: str | Path = "data/audio_library.json") -> List[Dict]:
    path = Path(path)
    if path.exists() and path.is_file():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass

    # Optional fallback for quick prototypes where no curated metadata exists.
    # The curated JSON should normally be the source of truth because it explains
    # scene, layer, intended use, spatial behavior, and Unity defaults.
    unity_resources = os.getenv("UNITY_RESOURCES_DIR")
    if unity_resources and os.getenv("USE_UNITY_RESOURCES_SCAN") == "1":
        resources_dir = Path(unity_resources).expanduser()
        if resources_dir.exists() and resources_dir.is_dir():
            assets = [
                build_unity_resource_entry(file_path, resources_dir)
                for file_path in sorted(resources_dir.rglob("*"))
                if is_audio_file(file_path)
            ]
            if assets:
                return assets

    directory = Path("audio_lib")
    if directory.exists() and directory.is_dir():
        assets: List[Dict] = []
        for file_path in sorted(directory.rglob("*")):
            if not is_audio_file(file_path):
                continue
            if "_hrtf" in file_path.stem or "_mono" in file_path.stem:
                continue
            if any(parent.name == "narration_script" for parent in file_path.parents):
                continue
            assets.append(build_asset_entry(file_path))
        if assets:
            return assets

    return load_mock_library()


def load_mock_library(path: str | Path = "data/mock_sound_library.json") -> List[Dict]:
    """Load mock sound assets; fall back to inlined defaults if missing or invalid."""
    path = Path(path)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return DEFAULT_LIBRARY
