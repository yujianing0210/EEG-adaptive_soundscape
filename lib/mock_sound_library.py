import json
from pathlib import Path
from typing import List, Dict

DEFAULT_LIBRARY = [
    {
        "asset_id": "forest_ambient_bed",
        "label": "Forest ambient bed",
        "category": "ambient",
        "description": "Soft continuous forest bed with light leaves",
        "mock_file_path": "mock://forest_ambient_bed.wav",
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
        "mock_file_path": "mock://light_wind.wav",
        "default_duration_sec": 45,
        "default_volume": 0.55,
        "spatial_profile": "slow_pan",
        "tags": ["forest", "wind", "motion"],
    },
]


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
