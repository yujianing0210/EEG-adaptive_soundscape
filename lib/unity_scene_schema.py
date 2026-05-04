from __future__ import annotations
from typing import Dict, List, Any
import uuid


def new_scene_id(scene_type: str) -> str:
    return f"{scene_type}_session_{uuid.uuid4().hex[:8]}"


def base_world_state(scene_family: str, active_sources: List[str]) -> Dict[str, Any]:
    return {
        "scene_family": scene_family,
        "current_phase": "settling_in",
        "atmosphere": "quiet, enclosed, soft morning air",
        "dominant_elements": active_sources[:2],
        "active_sources": active_sources,
        "retired_sources": [],
        "continuity_notes": "Keep identity stable; avoid sudden scene jumps.",
    }


def build_unity_scene(scene_id: str, segment_id: str, scene_type: str, atmosphere: str,
                     narration_script: str, sources: List[Dict[str, Any]], duration_sec: int,
                     world_state: Dict[str, Any], mental_state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scene_id": scene_id,
        "segment_id": segment_id,
        "duration_sec": duration_sec,
        "scene_type": scene_type,
        "atmosphere": atmosphere,
        "narration_script": narration_script,
        "sources": sources,
        "world_state": world_state,
        "mental_state": mental_state,
    }
