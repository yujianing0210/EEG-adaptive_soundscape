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


def _canonical_scene_family(scene_family: Any) -> str:
    sf = str(scene_family or "").strip().lower()
    if sf in {"ocean", "ocean_beach", "beach", "sea", "coast", "seaside", "shore"}:
        return "ocean"
    if sf in {"night_forest", "nightforest", "forest_night"}:
        return "night_forest"
    if sf in {"forest", "woods", "woodland"}:
        return "forest"
    if "ocean" in sf or "beach" in sf or "sea" in sf:
        return "ocean"
    if "night" in sf and "forest" in sf:
        return "night_forest"
    if "forest" in sf or "woods" in sf:
        return "forest"
    return "forest"


def _as_lower_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip().lower() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text.lower()] if text else []


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp01(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def _score_unit(value: Any, default: float = 0.5) -> float:
    """Normalize scores that may arrive as 0-1 or 0-10 into 0-1."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v <= 1.0:
        return max(0.0, min(1.0, v))
    return max(0.0, min(1.0, v / 10.0))


def _asset_layer(asset: Dict[str, Any]) -> str:
    layer = str(
        asset.get("layer")
        or asset.get("category")
        or asset.get("role")
        or "event"
    ).lower()
    if layer not in {"ambient", "event", "action"}:
        return "event"
    return layer


def _asset_category(asset: Dict[str, Any]) -> str:
    layer = _asset_layer(asset)
    if layer in {"ambient", "event", "action"}:
        return layer
    return "event"


def _matches_scene(asset: Dict[str, Any], scene_family: str) -> bool:
    scene_family = _canonical_scene_family(scene_family)
    scene_values = set(_as_lower_list(asset.get("scene")))
    tags = set(_as_lower_list(asset.get("tags")))

    if scene_family in {"forest", "night_forest"}:
        return ("forest" in scene_values) or ("forest" in tags)
    if scene_family == "ocean":
        return ("ocean_beach" in scene_values) or ("ocean" in tags) or ("beach" in tags)

    aliases = SCENE_TAG_ALIASES.get(scene_family, {scene_family})
    searchable = " ".join([
        str(asset.get("asset_id", "")),
        str(asset.get("label", "")),
        str(asset.get("description", "")),
        str(asset.get("asset_ref", "")),
        " ".join(_as_lower_list(asset.get("tags"))),
        " ".join(_as_lower_list(asset.get("scene"))),
    ]).lower()
    return any(alias in searchable for alias in aliases)


def _segment_index(scene: Optional[Dict[str, Any]]) -> int:
    if not scene:
        return 0
    sid = str(scene.get("segment_id", "segment_000"))
    try:
        return int(sid.split("_")[-1])
    except (TypeError, ValueError):
        return 0


def _scene_ambient_priority(scene_family: str) -> List[str]:
    scene_family = _canonical_scene_family(scene_family)
    if scene_family in {"forest", "night_forest"}:
        return ["forest_ambient_bed_01", "forest_wind_leaves_01", "forest_ambient_bed_02"]
    if scene_family == "ocean":
        return ["ocean_waves_soft_01", "ocean_shoreline_wash_01", "ocean_sea_breeze_01"]
    return []


def _state_flags(
    state_label: str,
    attention: Optional[float],
    relaxation: Optional[float],
    anxiety: Optional[float],
    mind_wandering_risk: Optional[float],
    stability: Optional[float],
) -> Dict[str, bool]:
    anxiety_high = (anxiety is not None and anxiety >= 0.65) or (relaxation is not None and relaxation < 0.45)
    attention_low = (attention is not None and attention < 0.45) or (mind_wandering_risk is not None and mind_wandering_risk >= 0.6)
    settling = state_label == "settling"
    stability_high = stability is not None and stability >= 0.65
    return {
        "anxiety_high": anxiety_high,
        "attention_low": attention_low,
        "settling": settling,
        "stability_high": stability_high,
    }


def _asset_allowed_under_state(asset: Dict[str, Any], anxiety_high: bool) -> bool:
    avoid_when = set(_as_lower_list(asset.get("avoid_when")))
    suddenness = _safe_float(asset.get("suddenness"), 0.0)
    if anxiety_high and "anxiety_high" in avoid_when:
        return False
    if anxiety_high and suddenness > 0.4:
        return False
    return True


def _is_bird_like_event(asset: Dict[str, Any]) -> bool:
    aid = str(asset.get("asset_id", "")).lower()
    label = str(asset.get("label", "")).lower()
    tags = set(_as_lower_list(asset.get("tags")))
    text = " ".join([aid, label, " ".join(tags)])
    return ("bird" in text) or ("seagull" in text)


def choose_sources(
    library: List[Dict[str, Any]],
    scene_family: str,
    density: float,
    eventfulness: float = 0.3,
    attention: Optional[float] = None,
    relaxation: Optional[float] = None,
    anxiety: Optional[float] = None,
    state_label: str = "settling",
    mind_wandering_risk: Optional[float] = None,
    stability: Optional[float] = None,
    attention_delta: Optional[float] = None,
    previous_scene: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    scene_family = _canonical_scene_family(scene_family)
    candidates = [asset for asset in library if _matches_scene(asset, scene_family)]
    if not candidates:
        candidates = list(library)

    grouped: Dict[str, List[Dict[str, Any]]] = {"ambient": [], "event": [], "action": []}
    for asset in candidates:
        grouped[_asset_layer(asset)].append(asset)

    flags = _state_flags(state_label, attention, relaxation, anxiety, mind_wandering_risk, stability)
    seg_idx = _segment_index(previous_scene)
    ambient_priority = _scene_ambient_priority(scene_family)
    ambient_rank = {aid: idx for idx, aid in enumerate(ambient_priority)}

    prev_ambient_id = None
    prev_event_id = None
    played_event_counts: Dict[str, int] = {}
    recent_event_ids: List[str] = []
    last_event_segment = -999
    last_event_segment_by_id: Dict[str, int] = {}
    if previous_scene:
        ws = previous_scene.get("world_state", {}) if isinstance(previous_scene.get("world_state", {}), dict) else {}
        raw_counts = ws.get("played_event_counts", {})
        if isinstance(raw_counts, dict):
            for k, v in raw_counts.items():
                try:
                    played_event_counts[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
        raw_recent = ws.get("recent_event_ids", [])
        if isinstance(raw_recent, list):
            recent_event_ids = [str(v) for v in raw_recent if str(v)]
        try:
            last_event_segment = int(ws.get("last_event_segment", -999))
        except (TypeError, ValueError):
            last_event_segment = -999
        raw_last_by_id = ws.get("last_event_segment_by_id", {})
        if isinstance(raw_last_by_id, dict):
            for k, v in raw_last_by_id.items():
                try:
                    last_event_segment_by_id[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
        for src in previous_scene.get("sources", []):
            src_layer = str(src.get("layer", src.get("category", ""))).lower()
            if src_layer == "ambient":
                prev_ambient_id = src.get("asset_id") or src.get("source_id")
            elif src_layer == "event":
                prev_event_id = src.get("asset_id") or src.get("source_id")

    # 1) Exactly one ambient.
    ambient_candidates = [
        a for a in grouped["ambient"]
        if _asset_allowed_under_state(a, flags["anxiety_high"])
    ]
    ambient_selected = None
    allow_ambient_switch = seg_idx > 0 and (seg_idx % 6 == 0)
    if prev_ambient_id and not allow_ambient_switch:
        for a in ambient_candidates:
            if a.get("asset_id") == prev_ambient_id:
                ambient_selected = a
                break
    if ambient_selected is None and ambient_candidates:
        random.shuffle(ambient_candidates)
        if allow_ambient_switch and prev_ambient_id:
            alternatives = [a for a in ambient_candidates if a.get("asset_id") != prev_ambient_id]
            if alternatives:
                ambient_candidates = alternatives
        ambient_candidates.sort(
            key=lambda a: (
                -int(bool(a.get("is_primary_ambient"))),
                ambient_rank.get(str(a.get("asset_id")), 99),
                -_safe_float(a.get("priority"), 0.5),
            )
        )
        ambient_selected = ambient_candidates[0]
    if ambient_selected is None and candidates:
        ambient_selected = candidates[0]

    selected: List[Dict[str, Any]] = []
    if ambient_selected is not None:
        selected.append(ambient_selected)

    secondary_ambient = None
    if ambient_selected is not None and len(ambient_candidates) > 1:
        ambient_texture_pool = [
            a for a in ambient_candidates
            if a.get("asset_id") != ambient_selected.get("asset_id")
            and (
                "slow_movement" in set(_as_lower_list(a.get("spatial_behavior")))
                or "texture" in set(_as_lower_list(a.get("tags")))
                or density >= 0.55
            )
        ]
        allow_secondary_ambient = (
            density >= 0.55
            or flags["attention_low"]
            or scene_family in {"forest", "night_forest"}
            or (seg_idx > 0 and seg_idx % 4 == 0)
        )
        if allow_secondary_ambient and ambient_texture_pool:
            ambient_texture_pool.sort(
                key=lambda a: (
                    int(a.get("asset_id") == prev_ambient_id),
                    -_safe_float(a.get("priority"), 0.5),
                    random.random(),
                )
            )
            secondary_ambient = ambient_texture_pool[0]
            selected.append(secondary_ambient)

    # 2) Event slot (at most one). Keep cues gentle, but frequent enough to
    # make the soundscape respond audibly to each EEG segment.
    event_selected = None
    event_candidates = [
        a for a in grouped["event"]
        if _asset_allowed_under_state(a, flags["anxiety_high"])
    ]
    if flags["anxiety_high"]:
        event_candidates = [
            a for a in event_candidates
            if _safe_float(a.get("suddenness"), 0.0) <= 0.25
            and str(a.get("recommended_distance", "")).lower() in {"far", "middle", "wide"}
            and not bool(a.get("is_rare_event"))
        ]

    allow_event = False
    attention_declining = attention_delta is not None and attention_delta < -0.04
    attention_improving = attention_delta is not None and attention_delta > 0.04
    strong_attention_recovery = (
        (attention is not None and attention < 0.32)
        or (mind_wandering_risk is not None and mind_wandering_risk >= 0.85)
        or (attention_declining and attention is not None and attention < 0.55)
    )
    if flags["attention_low"]:
        allow_event = True
    if attention_declining and not flags["anxiety_high"]:
        allow_event = True
    if mind_wandering_risk is not None and mind_wandering_risk >= 0.72 and not flags["anxiety_high"]:
        allow_event = True
    if not flags["anxiety_high"] and not flags["settling"] and eventfulness >= 0.12:
        allow_event = True
    if attention_improving and not flags["attention_low"] and eventfulness < 0.4:
        allow_event = False
    min_event_gap = 2 if flags["anxiety_high"] else 0
    if allow_event and (seg_idx - last_event_segment) < min_event_gap and not strong_attention_recovery:
        allow_event = False

    if allow_event:
        trigger_prob = 0.65 + 0.25 * _clamp01(eventfulness, 0.3)
        if eventfulness >= 0.4 and not flags["anxiety_high"]:
            trigger_prob = 1.0
        if flags["attention_low"]:
            trigger_prob += 0.10
        if attention_declining:
            trigger_prob += 0.18
        if attention_improving and not flags["attention_low"]:
            trigger_prob -= 0.22
        if flags["anxiety_high"]:
            trigger_prob -= 0.25
        if strong_attention_recovery:
            trigger_prob += 0.15
        trigger_prob = max(0.25, min(0.95, trigger_prob))
        if random.random() > trigger_prob:
            allow_event = False

    if allow_event and event_candidates:
        # Prevent immediate reuse of exactly the same event ID when alternatives exist.
        staged = []
        for a in event_candidates:
            aid = str(a.get("asset_id", ""))
            last_seg_for_id = last_event_segment_by_id.get(aid, -999)
            if (seg_idx - last_seg_for_id) >= 3:
                staged.append(a)
        if staged:
            event_candidates = staged

        unplayed = [a for a in event_candidates if played_event_counts.get(str(a.get("asset_id")), 0) == 0]
        if unplayed:
            event_candidates = unplayed
        unplayed_exists = len(unplayed) > 0
        if event_candidates:
            min_play_count = min(played_event_counts.get(str(a.get("asset_id")), 0) for a in event_candidates)
        else:
            min_play_count = 0
        scored = []
        for a in event_candidates:
            aid = str(a.get("asset_id", ""))
            use_when = set(_as_lower_list(a.get("use_when")))
            distance = str(a.get("recommended_distance", "")).lower()
            suddenness = _safe_float(a.get("suddenness"), 0.0)
            score = 0.0
            if "attention_low" in use_when:
                score += 3.5
            if attention_declining and "attention_low" in use_when:
                score += 1.2
            if attention_improving and not flags["attention_low"] and "attention_low" in use_when:
                score -= 1.0
            if distance in {"far", "middle", "wide"}:
                score += 1.5
            score += _safe_float(a.get("priority"), 0.5)
            score -= suddenness * 2.0
            if bool(a.get("is_rare_event")):
                if flags["stability_high"] and not flags["settling"] and not flags["anxiety_high"]:
                    score += 0.2
                else:
                    score -= 3.0
            times_played = played_event_counts.get(aid, 0)
            score -= min(3.0, times_played * 0.9)
            # Strongly discourage replaying the same event every window.
            if times_played >= 1:
                score -= 0.8
            if times_played >= 2:
                score -= 1.4
            if unplayed_exists and times_played > 0:
                score -= 1.2
            score -= max(0, times_played - min_play_count) * 1.5
            if prev_event_id and (a.get("asset_id") == prev_event_id):
                # Avoid selecting the exact same event every update when alternatives exist.
                score -= 2.8
            if aid in recent_event_ids:
                score -= 1.8
            scored.append((score, random.random(), a))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        score_threshold = -999.0 if flags["attention_low"] else -2.0
        if scored and scored[0][0] > score_threshold:
            best_score = scored[0][0]
            # Randomize among near-top candidates to avoid repetitive single-event selection.
            top_pool = [row[2] for row in scored if row[0] >= best_score - 0.9]
            if prev_event_id:
                non_repeat_pool = [a for a in top_pool if a.get("asset_id") != prev_event_id]
                if non_repeat_pool:
                    top_pool = non_repeat_pool
            event_selected = random.choice(top_pool) if top_pool else scored[0][2]
            # If only a previously played single candidate remains, prefer silence over repetition.
            if not strong_attention_recovery and event_selected is not None:
                eid = str(event_selected.get("asset_id", ""))
                if played_event_counts.get(eid, 0) >= 2 and len(event_candidates) == 1:
                    event_selected = None

    # 3) Action slot (at most one). Action can coexist with event.
    action_selected = None
    action_candidates = [
        a for a in grouped["action"]
        if _asset_allowed_under_state(a, flags["anxiety_high"])
    ]
    if action_candidates:
        previous_action_ids = []
        if previous_scene:
            previous_action_ids = [
                str(src.get("asset_id") or src.get("source_id") or "")
                for src in previous_scene.get("sources", [])
                if str(src.get("layer", src.get("category", ""))).lower() == "action"
            ]
        if flags["anxiety_high"] or flags["settling"]:
            for a in action_candidates:
                if str(a.get("asset_id", "")).lower() == "body_slow_breath_01":
                    action_selected = a
                    break
        if action_selected is None:
            scene_action_ids = {
                "forest": "forest_grass_footstep_01",
                "night_forest": "forest_grass_footstep_01",
                "ocean": "ocean_wet_sand_footstep_01",
            }
            preferred_action_id = scene_action_ids.get(scene_family, "body_slow_breath_01")
            if (flags["attention_low"] or attention_declining) and seg_idx % 2 == 0:
                for a in action_candidates:
                    if str(a.get("asset_id", "")).lower() == preferred_action_id:
                        action_selected = a
                        break
            if action_selected is None and seg_idx % 3 == 0:
                for a in action_candidates:
                    if str(a.get("asset_id", "")).lower() == preferred_action_id:
                        action_selected = a
                        break
            if action_selected is not None and str(action_selected.get("asset_id", "")) in previous_action_ids:
                alternatives = [
                    a for a in action_candidates
                    if str(a.get("asset_id", "")) not in previous_action_ids
                    and str(a.get("asset_id", "")).lower() != "body_slow_breath_01"
                ]
                if alternatives and (flags["attention_low"] or attention_declining or seg_idx % 4 == 0):
                    action_selected = random.choice(alternatives)
        if action_selected is None and event_selected is not None:
            # If event is present, still allow a gentle grounding layer sometimes.
            if seg_idx % 2 == 0:
                for a in action_candidates:
                    if str(a.get("asset_id", "")).lower() == "body_slow_breath_01":
                        action_selected = a
                        break
        if action_selected is None and action_candidates:
            # Fallback so action does not disappear for long stretches.
            action_selected = action_candidates[0]

    if event_selected is not None:
        selected.append(event_selected)
    if action_selected is not None:
        selected.append(action_selected)

    return selected


def scene_uses_family_assets(scene: Dict[str, Any], scene_family: str) -> bool:
    scene_family = _canonical_scene_family(scene_family)
    aliases = SCENE_TAG_ALIASES.get(scene_family, {scene_family})
    sources = scene.get("sources", [])
    if not sources:
        return False
    source_text = " ".join(
        " ".join(str(source.get(key, "")) for key in ["source_id", "asset_ref", "role", "category"])
        for source in sources
    ).lower()
    return any(alias in source_text for alias in aliases)


def _source_position(value: Any, fallback: Dict[str, float]) -> Dict[str, float]:
    if isinstance(value, list) and len(value) >= 3:
        return {"x": _safe_float(value[0], fallback["x"]), "y": _safe_float(value[1], fallback["y"]), "z": _safe_float(value[2], fallback["z"])}
    if isinstance(value, dict):
        return {
            "x": _safe_float(value.get("x"), fallback["x"]),
            "y": _safe_float(value.get("y"), fallback["y"]),
            "z": _safe_float(value.get("z"), fallback["z"]),
        }
    return fallback


def _normalize_llm_source(source: Dict[str, Any], asset: Dict[str, Any]) -> Dict[str, Any]:
    layer = _asset_layer(asset)
    category = _asset_category(asset)
    scheduled = place_sources([asset], density=0.4)[0]
    merged = dict(scheduled)

    merged["source_id"] = asset["asset_id"]
    merged["id"] = asset["asset_id"]
    merged["asset_id"] = asset["asset_id"]
    merged["label"] = asset.get("label", merged.get("label", asset["asset_id"]))
    merged["layer"] = layer
    merged["category"] = category
    merged["asset_ref"] = asset.get("asset_ref") or asset.get("mock_file_path") or merged.get("asset_ref")
    merged["role"] = asset.get("role", merged.get("role", layer))

    # LLM is allowed to design Unity placement and behavior, while metadata
    # remains the fallback and safety boundary.
    if "position" in source:
        merged["position"] = _source_position(source.get("position"), merged["position"])
    if "volume" in source:
        merged["volume"] = round(max(0.0, min(0.85, _safe_float(source.get("volume"), merged["volume"]))), 2)
    if "loop" in source:
        merged["loop"] = bool(source.get("loop"))
    if layer == "ambient":
        merged["loop"] = True
    if layer == "event":
        merged["loop"] = False
    if "motion" in source:
        motion = _normalize_motion_for_unity(source.get("motion"), layer, _as_lower_list(asset.get("spatial_behavior")))
        if layer == "event" and _is_bird_like_event(asset):
            motion = {
                "type": "orbit",
                "speed": float(motion.get("speed", 0.08)) if isinstance(motion, dict) else 0.08,
                "radius": float(motion.get("radius", 1.6)) if isinstance(motion, dict) else 1.6,
            }
        merged["motion"] = motion
    if "repeat_count" in source:
        repeat_count = int(_safe_float(source.get("repeat_count"), merged["repeat_count"]))
        merged["repeat_count"] = max(1, min(8, repeat_count))
        if layer == "event":
            merged["repeat_count"] = max(2, min(4, merged["repeat_count"]))
    if "repeat_interval_sec" in source:
        merged["repeat_interval_sec"] = max(0.0, min(20.0, _safe_float(source.get("repeat_interval_sec"), merged["repeat_interval_sec"])))
    if "fade_in_sec" in source:
        merged["fade_in_sec"] = max(0.0, min(12.0, _safe_float(source.get("fade_in_sec"), merged["fade_in_sec"])))
    if "fade_out_sec" in source:
        merged["fade_out_sec"] = max(0.0, min(12.0, _safe_float(source.get("fade_out_sec"), merged["fade_out_sec"])))
    if "auto_delete_after_sec" in source:
        value = source.get("auto_delete_after_sec")
        merged["auto_delete_after_sec"] = None if value is None else max(0.0, min(120.0, _safe_float(value, 0.0)))

    merged["position"] = _spatialized_position(asset, layer, str(merged.get("recommended_distance", "middle")), merged["position"])
    merged["motion"] = _spatialized_motion(asset, layer, merged["position"], merged.get("motion", {"type": "none"}))

    return merged


def normalize_scene_assets(scene: Dict[str, Any], library: List[Dict[str, Any]], scene_family: str) -> Optional[Dict[str, Any]]:
    scene_family = _canonical_scene_family(scene_family)
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

        normalized_sources.append(_normalize_llm_source(source, asset))

    ambient_sources = [s for s in normalized_sources if str(s.get("layer", "")).lower() == "ambient"]
    non_ambient_sources = [s for s in normalized_sources if str(s.get("layer", "")).lower() != "ambient"]
    if ambient_sources:
        normalized_sources = ambient_sources[:2] + non_ambient_sources
    else:
        ambient_candidates = [
            asset for asset in library
            if _asset_layer(asset) == "ambient" and _matches_scene(asset, scene_family)
        ]
        ambient_candidates.sort(
            key=lambda a: (
                -int(bool(a.get("is_primary_ambient"))),
                -_safe_float(a.get("priority"), 0.5),
            )
        )
        if ambient_candidates:
            normalized_sources = [_normalize_llm_source({}, ambient_candidates[0])] + non_ambient_sources

    scene["sources"] = normalized_sources[:5]
    scene["scene_type"] = scene_family
    scene.setdefault("world_state", {})
    scene["world_state"]["active_sources"] = [source["source_id"] for source in normalized_sources]
    scene["world_state"]["scene_family"] = scene_family

    if not normalized_sources or not scene_uses_family_assets(scene, scene_family):
        return None
    return scene


def _boost_event_repeats(scene: Dict[str, Any]) -> Dict[str, Any]:
    for source in scene.get("sources", []) or []:
        if str(source.get("layer", source.get("category", ""))).lower() != "event":
            continue
        source["loop"] = False
        try:
            repeat_count = int(source.get("repeat_count", 1))
        except (TypeError, ValueError):
            repeat_count = 1
        source["repeat_count"] = max(2, min(4, repeat_count if repeat_count > 1 else random.randint(2, 4)))
        try:
            interval = float(source.get("repeat_interval_sec", 0))
        except (TypeError, ValueError):
            interval = 0.0
        if interval <= 0:
            source["repeat_interval_sec"] = random.choice([8.0, 10.0, 12.0, 14.0])
    return scene


def _add_gentle_event_if_missing(
    scene: Dict[str, Any],
    library: List[Dict[str, Any]],
    scene_family: str,
    mental_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sources = scene.get("sources", []) or []
    if any(str(s.get("layer", s.get("category", ""))).lower() == "event" for s in sources):
        return _boost_event_repeats(scene)
    if len(sources) >= 5:
        return scene

    mental_state = mental_state or {}
    state_label = str(mental_state.get("state_label", "stable_relaxation"))
    relaxation = _clamp01(mental_state.get("relaxation", 0.7), 0.7)
    anxiety = mental_state.get("anxiety")
    anxiety_high = False
    if anxiety is not None:
        anxiety_high = _clamp01(anxiety, 0.0) >= 0.65
    if state_label == "settling" and relaxation < 0.45:
        anxiety_high = True
    if anxiety_high:
        return scene

    world_state = scene.get("world_state", {}) if isinstance(scene.get("world_state", {}), dict) else {}
    recent_ids = set(str(v) for v in world_state.get("recent_event_ids", []) if str(v))
    candidates = [
        a for a in library
        if _asset_layer(a) == "event"
        and _matches_scene(a, scene_family)
        and _asset_allowed_under_state(a, anxiety_high=False)
    ]
    if not candidates:
        return scene
    fresh = [a for a in candidates if str(a.get("asset_id", "")) not in recent_ids]
    if fresh:
        candidates = fresh

    def event_score(asset: Dict[str, Any]) -> tuple[float, float]:
        tags = set(_as_lower_list(asset.get("tags")))
        use_when = set(_as_lower_list(asset.get("use_when")))
        score = _safe_float(asset.get("priority"), 0.5)
        score += 1.2 if str(asset.get("recommended_distance", "")).lower() in {"far", "middle", "wide"} else 0.0
        score += 0.8 if {"attention_low", "adaptive_shift", "immersion"} & use_when else 0.0
        score += 0.4 if {"bird", "seagull", "water", "wave", "leaf"} & tags else 0.0
        score -= _safe_float(asset.get("suddenness"), 0.0) * 1.5
        if bool(asset.get("is_rare_event")) and state_label != "stable_relaxation":
            score -= 1.5
        return score, random.random()

    candidates.sort(key=event_score, reverse=True)
    event_asset = candidates[0]
    event_source = _normalize_llm_source(
        {
            "repeat_count": random.randint(2, 4),
            "repeat_interval_sec": random.choice([8.0, 10.0, 12.0, 14.0]),
        },
        event_asset,
    )
    scene["sources"] = sources + [event_source]
    scene.setdefault("world_state", {})
    scene["world_state"]["active_sources"] = [s["source_id"] for s in scene["sources"]]
    return _boost_event_repeats(scene)


def fallback_bootstrap_scene(user_prompt: str, library: List[Dict[str, Any]], scene_family: str) -> Dict[str, Any]:
    scene_family = _canonical_scene_family(scene_family)
    assets = choose_sources(
        library,
        scene_family,
        density=0.4,
        eventfulness=0.45,
        attention=0.6,
        relaxation=0.6,
        state_label="stable_relaxation",
        mind_wandering_risk=0.3,
        stability=0.55,
        previous_scene=None,
    )
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


def _default_position_for_distance(recommended_distance: str) -> Dict[str, float]:
    d = str(recommended_distance or "").lower()
    if d == "near":
        return {"x": 0.0, "y": 0.0, "z": 1.2}
    if d == "middle":
        return {"x": 2.8, "y": 0.0, "z": 2.7}
    if d == "far":
        return {"x": 3.8, "y": 1.0, "z": 4.0}
    if d == "wide":
        return {"x": -2.4, "y": 0.4, "z": 3.4}
    return {"x": 0.0, "y": 0.0, "z": 2.5}


def _normalize_motion_for_unity(motion: Any, layer: str, spatial_behavior: List[str]) -> Dict[str, Any]:
    # Keep metadata motion as-is whenever it uses known vocabulary.
    if not isinstance(motion, dict):
        motion = {}
    mtype = str(motion.get("type", "")).lower()
    if mtype == "static":
        return {"type": "none"}
    if mtype in {
        "none",
        "drift",
        "overhead_pass",
        "approach_recede",
        "local_random",
        "orbit",
        "circle",
        "breathing",
        "random",
        "slow_orbit",
    }:
        return dict(motion)

    if layer == "ambient":
        if "slow_movement" in spatial_behavior:
            return {"type": "drift", "duration": 16.0, "repeat": True}
        return {"type": "none"}
    if layer == "action":
        return {"type": "none"}
    return {"type": "none"}


def _safe_layer_volume(asset: Dict[str, Any], layer: str) -> float:
    rv = asset.get("recommended_volume")
    if rv is not None:
        volume = _safe_float(rv, 0.45 if layer == "ambient" else 0.22)
        aid = str(asset.get("asset_id", "")).lower()
        tags = set(_as_lower_list(asset.get("tags")))
        if layer == "ambient" and ("wave" in aid or "waves" in tags or "shoreline" in aid):
            return min(volume, 0.28)
        if layer == "ambient" and ("forest" in aid or "forest" in tags):
            return max(volume, 0.72)
        if layer in {"event", "action"} and ("forest" in aid or "forest" in tags):
            return min(volume, 0.24)
        return volume
    if layer == "ambient":
        return 0.45
    return 0.22


def _vec3_list(pos: Dict[str, float]) -> List[float]:
    return [float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), float(pos.get("z", 0.0))]


def _lateral_sign(asset_id: str) -> float:
    return -1.0 if sum(ord(ch) for ch in asset_id) % 2 == 0 else 1.0


def _spatialized_position(asset: Dict[str, Any], layer: str, distance: str, pos: Dict[str, float]) -> Dict[str, float]:
    pos = dict(pos)
    aid = str(asset.get("asset_id", ""))
    sign = _lateral_sign(aid)
    distance = str(distance or "").lower()

    if layer == "action":
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    if layer == "ambient":
        if abs(_safe_float(pos.get("x"), 0.0)) < 0.4:
            pos["x"] = sign * random.uniform(0.45, 1.05)
        else:
            pos["x"] = max(-1.2, min(1.2, _safe_float(pos.get("x"), 0.0)))
        pos["z"] = max(1.2, min(2.2, _safe_float(pos.get("z"), 1.8)))
        pos["y"] = max(-0.2, min(0.7, _safe_float(pos.get("y"), 0.0)))
        return pos

    if distance == "near":
        pos["x"] = sign * random.uniform(1.0, 1.8)
        pos["z"] = random.uniform(1.4, 2.1)
    elif distance == "middle":
        pos["x"] = sign * random.uniform(2.0, 3.3)
        pos["z"] = random.uniform(2.4, 3.4)
    elif distance in {"far", "wide"}:
        pos["x"] = sign * random.uniform(2.8, 4.4)
        pos["z"] = random.uniform(3.2, 4.8)
        pos["y"] = max(0.4, min(2.2, _safe_float(pos.get("y"), 1.0)))
    else:
        pos["x"] = sign * random.uniform(1.8, 3.4)
        pos["z"] = random.uniform(2.2, 3.8)
    return pos


def _spatialized_motion(asset: Dict[str, Any], layer: str, pos: Dict[str, float], motion: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(motion, dict):
        motion = {"type": "none"}
    motion = dict(motion)
    mtype = str(motion.get("type", "none")).lower()
    aid = str(asset.get("asset_id", ""))
    center = _vec3_list(pos)

    if layer == "action":
        return {"type": "none", "relative_to_listener": True}

    if layer == "ambient":
        if mtype in {"none", "static", ""}:
            return {"type": "none"}
        if mtype == "drift":
            motion["duration"] = max(28.0, _safe_float(motion.get("duration"), 28.0))
            motion["repeat"] = True
            motion["start"] = [center[0] - 0.4, center[1], center[2] - 0.1]
            motion["end"] = [center[0] + 0.4, center[1], center[2] + 0.1]
        return motion

    if mtype in {"none", "static", ""}:
        sign = _lateral_sign(aid)
        return {
            "type": "approach_recede",
            "start": [sign * 4.6, center[1], 3.4],
            "mid": [sign * 0.8, max(0.2, center[1]), 1.2],
            "end": [-sign * 4.6, center[1], 3.0],
            "duration": 7.0,
            "repeat": False,
            "pass_count": 2,
            "volume_curve": "fade_in_then_out",
            "relative_to_listener": True,
        }
    if mtype in {"orbit", "circle"}:
        motion["type"] = "orbit"
        motion["center"] = [0.0, max(0.2, min(1.2, center[1])), 0.6]
        motion["radius"] = max(3.0, _safe_float(motion.get("radius"), 1.6))
        motion["speed"] = max(0.28, _safe_float(motion.get("speed"), 0.08))
        motion["around_listener"] = True
        motion["relative_to_listener"] = True
        return motion
    if mtype == "local_random":
        motion["center"] = [0.0, center[1], 1.2]
        motion["radius"] = max(2.0, _safe_float(motion.get("radius"), 0.4))
        motion["speed"] = max(0.16, _safe_float(motion.get("speed"), 0.04))
        motion["relative_to_listener"] = True
        return motion
    if mtype == "drift":
        sign = _lateral_sign(aid)
        motion["start"] = [sign * 4.6, center[1], 3.2]
        motion["end"] = [-sign * 4.6, center[1], 1.4]
        motion["duration"] = max(7.0, min(11.0, _safe_float(motion.get("duration"), 8.0)))
        motion["repeat"] = True
        motion["relative_to_listener"] = True
        return motion
    if mtype in {"overhead_pass", "approach_recede"}:
        sign = _lateral_sign(aid)
        motion["start"] = [sign * 4.8, max(center[1], 0.7), 3.6]
        motion["end"] = [-sign * 4.8, max(center[1], 0.7), 2.0]
        if mtype == "approach_recede":
            motion["mid"] = [sign * 0.6, max(center[1], 0.4), 0.9]
            motion["volume_curve"] = "fade_in_then_out"
        motion["duration"] = max(5.0, min(9.0, _safe_float(motion.get("duration"), 7.0)))
        motion["pass_count"] = max(2, int(_safe_float(motion.get("pass_count"), 2)))
        motion["relative_to_listener"] = True
        return motion
    return motion


def place_sources(assets: List[Dict[str, Any]], density: float) -> List[Dict[str, Any]]:
    placed = []
    for asset in assets:
        layer = _asset_layer(asset)
        category = _asset_category(asset)
        spatial_behavior = set(_as_lower_list(asset.get("spatial_behavior")))
        distance = str(asset.get("recommended_distance", "middle")).lower()

        default_pos = asset.get("default_position")
        if isinstance(default_pos, list) and len(default_pos) >= 3:
            pos = {"x": float(default_pos[0]), "y": float(default_pos[1]), "z": float(default_pos[2])}
        elif isinstance(default_pos, dict):
            pos = {
                "x": _safe_float(default_pos.get("x"), 0.0),
                "y": _safe_float(default_pos.get("y"), 0.0),
                "z": _safe_float(default_pos.get("z"), 2.5),
            }
        else:
            pos = _default_position_for_distance(distance)

        if layer == "action":
            # Action sounds are body/user anchored and should follow the listener/camera.
            pos = {"x": 0.0, "y": 0.0, "z": 0.0}
        else:
            pos = _spatialized_position(asset, layer, distance, pos)

        base_volume = _safe_layer_volume(asset, layer)
        volume = min(0.85, base_volume * AUDIO_VOLUME_BOOST)
        loop = bool(asset.get("loop", category == "ambient"))
        if layer == "event":
            loop = False
        motion = _normalize_motion_for_unity(asset.get("default_motion"), layer, sorted(spatial_behavior))
        if layer == "action":
            motion = {"type": "none", "relative_to_listener": True}
        if layer == "event" and isinstance(motion, dict):
            mtype = str(motion.get("type", "")).lower()
            if _is_bird_like_event(asset):
                # User preference: all bird/seagull events orbit/circle.
                motion = {
                    "type": "orbit",
                    "speed": float(motion.get("speed", 0.08)),
                    "radius": float(motion.get("radius", 1.6)),
                }
                mtype = "orbit"
            if mtype in {"overhead_pass", "approach_recede"}:
                motion = dict(motion)
                motion.setdefault("repeat", False)
                # Keep event movement finite per EEG segment: 1-2 passes.
                motion["pass_count"] = int(motion.get("pass_count", random.choice([1, 2])))
        motion = _spatialized_motion(asset, layer, pos, motion)

        repeat_count = int(asset.get("repeat_count", 1 if loop else 1))
        if layer == "event":
            # User preference: event playback should typically repeat 2-4 times.
            configured = int(asset.get("repeat_count", 1))
            if configured <= 1:
                repeat_count = random.randint(2, 4)
            else:
                repeat_count = max(2, min(4, configured))
        repeat_interval_sec = float(asset.get("repeat_interval_sec", 0))
        if layer == "event" and repeat_count > 1 and repeat_interval_sec <= 0:
            repeat_interval_sec = random.choice([8.0, 10.0, 12.0, 14.0])

        placed.append({
            "id": asset["asset_id"],
            "asset_id": asset["asset_id"],
            "source_id": asset["asset_id"],
            "label": asset.get("label", asset["asset_id"]),
            "layer": layer,
            "role": asset.get("role", layer),
            "category": category,
            "asset_ref": asset.get("asset_ref") or asset.get("mock_file_path") or f"mock://{asset['asset_id']}.wav",
            "start_sec": 0,
            "end_sec": 60,
            "volume": round(volume, 2),
            "loop": loop,
            "repeat_count": repeat_count,
            "repeat_interval_sec": repeat_interval_sec,
            "position": pos,
            "relative_to_listener": layer == "action",
            "motion": motion,
            "spatial_behavior": sorted(spatial_behavior),
            "recommended_distance": distance,
            "fade_in_sec": float(asset.get("fade_in_sec", 2.0)),
            "fade_out_sec": float(asset.get("fade_out_sec", 2.0)),
            "auto_delete_after_sec": asset.get("auto_delete_after_sec"),
            "description": asset.get("description", ""),
        })
    return placed


# ---------------------------------------------------------------------------
# Scene bootstrap
# ---------------------------------------------------------------------------

def bootstrap_scene(user_prompt: str) -> Dict[str, Any]:
    library = load_audio_library()
    scene_family = _canonical_scene_family(select_scene_family(user_prompt))

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
                scene = _add_gentle_event_if_missing(scene, library, scene_family, scene["mental_state"])
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
            "eventfulness": 0.45,
            "guidance_intensity": 0.25,
            "proximity": 0.7,
        },
        "settling": {
            "density": 0.48,
            "motion_intensity": 0.28,
            "eventfulness": 0.32,
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
            "eventfulness": 0.35,
            "guidance_intensity": 0.65,
            "proximity": 0.85,
        },
    }

    # deterministic fallback
    raw_attention = _safe_float(features.get("attention_score"), 0.5)
    raw_relaxation = _safe_float(features.get("relaxation_score"), 0.5)
    raw_stability = _safe_float(features.get("stability_score"), 0.5)
    attention = _score_unit(raw_attention, 0.5)
    relaxation = _score_unit(raw_relaxation, 0.5)
    stability = _score_unit(raw_stability, 0.5)
    mind_wandering_risk = _clamp01(1 - attention, 0.5)
    return {
        "state_label": rule_state,
        "confidence": 0.42,
        "trend": "stable",
        "interpretation": f"Fallback: continuing {rule_state} based on ratios",
        "attention": attention,
        "relaxation": relaxation,
        "stability": stability,
        "mind_wandering_risk": mind_wandering_risk,
        "scene_implication": implication_by_state.get(rule_state, implication_by_state["settling"]),
    }


def _next_segment_index(previous_scene: Dict[str, Any]) -> int:
    try:
        return int(str(previous_scene.get("segment_id", "segment_000")).split("_")[-1]) + 1
    except (TypeError, ValueError):
        return 1


def _update_scene_runtime_state(
    scene: Dict[str, Any],
    previous_scene: Dict[str, Any],
    mental_state: Dict[str, Any],
    scene_family: str,
) -> Dict[str, Any]:
    new_segment_index = _next_segment_index(previous_scene)
    segment_id = f"segment_{new_segment_index:03d}"
    scene["scene_id"] = previous_scene.get("scene_id", scene.get("scene_id") or new_scene_id(scene_family))
    scene["segment_id"] = segment_id
    scene["scene_type"] = scene_family
    scene["duration_sec"] = int(scene.get("duration_sec", 60) or 60)
    previous_atmosphere = previous_scene.get("atmosphere", "")
    scene["atmosphere"] = scene.get("atmosphere") or _adaptive_atmosphere(scene_family, mental_state, new_segment_index)
    if scene["atmosphere"] == previous_atmosphere:
        scene["atmosphere"] = _adaptive_atmosphere(scene_family, mental_state, new_segment_index)
    previous_narration = previous_scene.get("narration_script", "")
    scene["narration_script"] = scene.get("narration_script") or _adaptive_narration(scene_family, mental_state, new_segment_index)
    if scene["narration_script"] == previous_narration:
        scene["narration_script"] = _adaptive_narration(scene_family, mental_state, new_segment_index)

    world_state = previous_scene.get("world_state", {}).copy()
    incoming_world_state = scene.get("world_state", {})
    if isinstance(incoming_world_state, dict):
        world_state.update(incoming_world_state)
    world_state["scene_family"] = scene_family
    world_state["active_sources"] = [s["asset_id"] for s in scene.get("sources", [])]
    world_state.setdefault("retired_sources", [])
    world_state.setdefault("continuity_notes", "Keep identity stable; avoid sudden scene jumps.")

    played_event_counts = world_state.get("played_event_counts", {})
    if not isinstance(played_event_counts, dict):
        played_event_counts = {}
    recent_event_ids = world_state.get("recent_event_ids", [])
    if not isinstance(recent_event_ids, list):
        recent_event_ids = []
    last_event_segment_by_id = world_state.get("last_event_segment_by_id", {})
    if not isinstance(last_event_segment_by_id, dict):
        last_event_segment_by_id = {}

    any_event_selected = False
    for src in scene.get("sources", []):
        if str(src.get("layer", src.get("category", ""))).lower() == "event":
            eid = str(src.get("asset_id") or src.get("source_id") or "")
            if not eid:
                continue
            any_event_selected = True
            try:
                played_event_counts[eid] = int(played_event_counts.get(eid, 0)) + 1
            except (TypeError, ValueError):
                played_event_counts[eid] = 1
            recent_event_ids.append(eid)
            last_event_segment_by_id[eid] = new_segment_index

    world_state["played_event_counts"] = played_event_counts
    world_state["recent_event_ids"] = recent_event_ids[-3:]
    world_state["last_event_segment_by_id"] = last_event_segment_by_id
    if any_event_selected:
        world_state["last_event_segment"] = new_segment_index
    else:
        world_state.setdefault("last_event_segment", -999)
    scene["world_state"] = world_state

    merged_mental = dict(mental_state)
    merged_mental.setdefault("source", "llm" if client else "rule")
    scene["mental_state"] = merged_mental
    return scene


def _scene_active_asset_ids(scene: Dict[str, Any]) -> List[str]:
    active = (scene.get("world_state") or {}).get("active_sources")
    if isinstance(active, list) and active:
        return [str(v) for v in active if str(v)]
    return [
        str(src.get("asset_id") or src.get("source_id") or "")
        for src in scene.get("sources", [])
        if str(src.get("asset_id") or src.get("source_id") or "")
    ]


def _mental_score(mental_state: Dict[str, Any], key: str, default: float = 0.5) -> float:
    display = mental_state.get("display_scores")
    if isinstance(display, dict) and display.get(key) is not None:
        return _score_unit(display.get(key), default)
    return _score_unit(mental_state.get(key), default)


def _variant_index(mental_state: Dict[str, Any], fallback: int = 0) -> int:
    for key in ("window_id", "step", "segment_index", "session_elapsed_sec"):
        try:
            return int(float(mental_state.get(key)))
        except (TypeError, ValueError):
            continue
    return fallback


def _pick_variant(options: List[str], variant: int) -> str:
    if not options:
        return ""
    return options[variant % len(options)]


def _adaptive_atmosphere(scene_family: str, mental_state: Dict[str, Any], variant: int = 0) -> str:
    state = str(mental_state.get("state_label") or mental_state.get("llm_state") or "").lower()
    attention = _mental_score(mental_state, "attention")
    relaxation = _mental_score(mental_state, "relaxation")
    stability = _mental_score(mental_state, "stability")
    variant = _variant_index(mental_state, variant)
    scene_family = _canonical_scene_family(scene_family)
    if scene_family == "ocean":
        if relaxation < 0.45:
            return _pick_variant([
                "close shoreline air with softened waves and steady grounding texture",
                "low tide ambience with rounded surf and near-body calm",
                "muted coastal air with slow foam movement and gentle grounding",
            ], variant)
        if attention < 0.45 or "distract" in state:
            return _pick_variant([
                "wide coastal air with clear distant cues and gentle side movement",
                "open shoreline space with small directional calls over steady waves",
                "bright sea air with sparse cues crossing the listener's edge",
            ], variant)
        if stability < 0.65:
            return "balanced seaside air with slow wave rhythm and reduced motion"
        return "open seaside air with spacious waves and calm forward focus"
    if scene_family == "night_forest":
        if relaxation < 0.45:
            return _pick_variant([
                "sheltered night forest with dim textures and near-body calm",
                "dark forest air with softened leaves and low grounding movement",
                "quiet night canopy with close, slow textures around the listener",
            ], variant)
        if attention < 0.45 or "distract" in state:
            return "quiet night forest with subtle directional cues through the dark"
        if stability < 0.65:
            return "slow night forest with steady low ambience and softened movement"
        return "deep night forest with stable air and lightly focused stillness"
    if relaxation < 0.45:
        return _pick_variant([
            "soft enclosed forest air with gentle grounding movement",
            "warm forest hush with low rustling textures close to the body",
            "quiet green air with softened leaf motion and slower breath-like pacing",
            "sheltered woodland space with gentle near-field movement",
        ], variant)
    if attention < 0.45 or "distract" in state:
        return _pick_variant([
            "clear forest space with small directional cues and light motion",
            "open woodland air with tiny far cues drawing attention outward",
            "leaf-filtered space with subtle side movement and crisp distant detail",
        ], variant)
    if stability < 0.65:
        return _pick_variant([
            "steady forest air with slower texture and balanced movement",
            "grounded forest ambience with reduced motion and even spacing",
            "calm woodland texture with stable layers and softened transitions",
        ], variant)
    return "open forest calm with spacious attention and stable organic motion"


def _adaptive_narration(scene_family: str, mental_state: Dict[str, Any], variant: int = 0) -> str:
    state = str(mental_state.get("state_label") or mental_state.get("llm_state") or "").lower()
    attention = _mental_score(mental_state, "attention")
    relaxation = _mental_score(mental_state, "relaxation")
    stability = _mental_score(mental_state, "stability")
    variant = _variant_index(mental_state, variant)
    scene_family = _canonical_scene_family(scene_family)
    place = "forest" if scene_family in {"forest", "night_forest"} else "shoreline"
    if relaxation < 0.45:
        return _pick_variant([
            f"Let the {place} soften around you; follow the gentlest layer back toward ease.",
            "Let the closest sound become your anchor, then loosen your shoulders with the next breath.",
            "Stay with the softest texture in the scene and let the rest of the space slow down.",
            "Allow the soundscape to hold the edges of your attention while your body settles.",
        ], variant)
    if attention < 0.45 or "distract" in state:
        return _pick_variant([
            "Notice the small directional cues, then return your attention to the space around you.",
            "Follow one moving cue across the scene, then come back to the center of your breath.",
            "Let the next distant sound gently point your attention outward and back again.",
        ], variant)
    if stability < 0.65:
        return _pick_variant([
            "Stay with the steady background sound as the scene settles into a more balanced rhythm.",
            "Let the stable layer underneath the scene set the pace for the next few breaths.",
            "Keep your attention on the slow bed of sound while the moving details become quieter.",
        ], variant)
    if "focus" in state:
        return f"Keep your focus lightly open while the soundscape stays spacious and steady."
    return f"Let this segment continue gently, with your breath and the {place} moving together."


def _compact_asset_for_llm(asset: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        "asset_id": asset.get("asset_id"),
        "asset_ref": asset.get("asset_ref"),
        "label": asset.get("label"),
        "scene": asset.get("scene"),
        "layer": _asset_layer(asset),
        "tags": asset.get("tags", [])[:8] if isinstance(asset.get("tags"), list) else asset.get("tags"),
        "description": asset.get("description"),
        "intensity": asset.get("intensity"),
        "suddenness": asset.get("suddenness"),
        "recommended_volume": asset.get("recommended_volume"),
        "recommended_distance": asset.get("recommended_distance"),
        "spatial_behavior": asset.get("spatial_behavior"),
        "default_position": asset.get("default_position"),
        "default_motion": asset.get("default_motion"),
        "use_when": asset.get("use_when"),
        "avoid_when": asset.get("avoid_when"),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [])}


def _scene_llm_library(
    library: List[Dict[str, Any]],
    scene_family: str,
    previous_scene: Dict[str, Any],
) -> List[Dict[str, Any]]:
    previous_ids = set(_scene_active_asset_ids(previous_scene))
    relevant = [
        asset for asset in library
        if _matches_scene(asset, scene_family) or str(asset.get("asset_id")) in previous_ids
    ]

    def rank(asset: Dict[str, Any]) -> tuple:
        layer = _asset_layer(asset)
        layer_rank = {"ambient": 0, "action": 1, "event": 2}.get(layer, 3)
        return (
            -int(str(asset.get("asset_id")) in previous_ids),
            layer_rank,
            -_safe_float(asset.get("priority"), 0.5),
            _safe_float(asset.get("suddenness"), 0.2),
            str(asset.get("asset_id", "")),
        )

    selected = sorted(relevant, key=rank)
    return [_compact_asset_for_llm(asset) for asset in selected]


def _compact_previous_scene_for_llm(scene: Dict[str, Any]) -> Dict[str, Any]:
    world_state = scene.get("world_state") if isinstance(scene.get("world_state"), dict) else {}
    compact_sources = []
    for source in scene.get("sources", []):
        compact_sources.append({
            "asset_id": source.get("asset_id") or source.get("source_id"),
            "layer": source.get("layer") or source.get("category"),
            "volume": source.get("volume"),
            "position": source.get("position"),
            "motion": source.get("motion"),
            "loop": source.get("loop"),
            "repeat_count": source.get("repeat_count"),
            "repeat_interval_sec": source.get("repeat_interval_sec"),
        })
    return {
        "scene_id": scene.get("scene_id"),
        "segment_id": scene.get("segment_id"),
        "scene_type": scene.get("scene_type"),
        "duration_sec": scene.get("duration_sec"),
        "atmosphere": scene.get("atmosphere"),
        "narration_script": scene.get("narration_script"),
        "sources": compact_sources,
        "mental_state": scene.get("mental_state", {}),
        "world_state": {
            "active_sources": world_state.get("active_sources"),
            "recent_event_ids": world_state.get("recent_event_ids"),
            "played_event_counts": world_state.get("played_event_counts"),
            "last_event_segment": world_state.get("last_event_segment"),
            "scene_family": world_state.get("scene_family"),
        },
    }


def llm_adapt_scene(
    previous_scene: Dict[str, Any],
    mental_state: Dict[str, Any],
    library: List[Dict[str, Any]],
    scene_family: str,
) -> Optional[Dict[str, Any]]:
    if not client:
        return None
    prompt = read_prompt("scene_adaptation_prompt.md")
    llm_library = _scene_llm_library(library, scene_family, previous_scene)
    messages = [
        {"role": "system", "content": prompt or "You update a spatial meditation scene."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "previous_scene": _compact_previous_scene_for_llm(previous_scene),
                    "mental_state": mental_state,
                    "scene_family": scene_family,
                    "audio_library": llm_library,
                    "constraints": {
                        "use_only_asset_ids_from_audio_library": True,
                        "must_change_each_window": "Change at least one event/action source from previous_scene when alternatives exist; if preserving the same source, change motion, repeat, or volume.",
                        "prefer_not_recent": "Prefer event/action asset_ids not listed in previous_scene.world_state.recent_event_ids. Avoid repeating the exact same event/action asset set in consecutive windows.",
                        "attention_event_logic": "If mental_state.attention_trend_direction is down, rotate in a gentle far/middle event or subtle action cue. If it is up and attention is not low, reduce novelty and avoid adding a new attention cue.",
                        "must_update_copy": "Return a new atmosphere and narration_script for this EEG window. Keep the scene identity, but do not copy previous_scene.atmosphere or previous_scene.narration_script exactly.",
                        "sources_per_segment": "2-5",
                        "ambient_layers": "1-2",
                        "event_and_action_may_coexist": True,
                        "unity_listener_origin": {"x": 0, "y": 0, "z": 0},
                        "supported_motion_types": [
                            "none",
                            "orbit",
                            "drift",
                            "overhead_pass",
                            "approach_recede",
                            "local_random",
                            "breathing",
                        ],
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]
    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.55,
            max_tokens=1400,
        )
        scene = json.loads(res.choices[0].message.content)
        scene = normalize_scene_assets(scene, library, scene_family)
        if scene is None:
            return None
        scene.setdefault("mental_state", {})
        scene["mental_state"].update(mental_state)
        scene["mental_state"]["source"] = "llm"
        scene = _add_gentle_event_if_missing(scene, library, scene_family, scene["mental_state"])
        scene = _update_scene_runtime_state(scene, previous_scene, scene["mental_state"], scene_family)
        prev_ids = _scene_active_asset_ids(previous_scene)
        next_ids = _scene_active_asset_ids(scene)
        if prev_ids and next_ids and set(prev_ids) == set(next_ids):
            return None
        return scene
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scene adaptation
# ---------------------------------------------------------------------------

def adapt_scene(previous_scene: Dict[str, Any], mental_state: Dict[str, Any], library: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    library = library or load_audio_library()
    current_scene_family = _canonical_scene_family(previous_scene.get("scene_type", "forest"))
    llm_scene = llm_adapt_scene(previous_scene, mental_state, library, current_scene_family)
    if llm_scene is not None:
        return llm_scene

    state_label = str(mental_state.get("state_label", "settling"))
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

    density = _clamp01(implication.get("density", 0.4), 0.4)
    eventfulness = _clamp01(implication.get("eventfulness", 0.3), 0.3)
    attention = _score_unit(mental_state.get("attention", 0.5), 0.5)
    relaxation = _score_unit(mental_state.get("relaxation", 0.5), 0.5)
    stability = _score_unit(mental_state.get("stability", 0.5), 0.5)
    mind_wandering_risk = _clamp01(mental_state.get("mind_wandering_risk", 0.5), 0.5)
    attention_delta = mental_state.get("attention_delta")
    if attention_delta is not None:
        try:
            attention_delta = max(-1.0, min(1.0, float(attention_delta)))
        except (TypeError, ValueError):
            attention_delta = None
    anxiety = mental_state.get("anxiety")
    if anxiety is not None:
        anxiety = _clamp01(anxiety, 0.5)

    assets = choose_sources(
        library,
        current_scene_family,
        density,
        eventfulness=eventfulness,
        attention=attention,
        relaxation=relaxation,
        anxiety=anxiety,
        state_label=state_label,
        mind_wandering_risk=mind_wandering_risk,
        stability=stability,
        attention_delta=attention_delta,
        previous_scene=previous_scene,
    )
    placed = place_sources(assets, density)

    new_segment_index = _next_segment_index(previous_scene)
    atmosphere = _adaptive_atmosphere(current_scene_family, mental_state, new_segment_index)
    notes = previous_scene.get("world_state", {}).get("continuity_notes", "")
    narration = _adaptive_narration(current_scene_family, mental_state, new_segment_index)

    world_state = previous_scene.get("world_state", {}).copy()
    world_state["active_sources"] = [a["asset_id"] for a in assets]
    world_state.setdefault("retired_sources", [])
    world_state.setdefault("continuity_notes", notes)
    new_segment_index = int(previous_scene.get("segment_id", "segment_000").split("_")[-1]) + 1
    played_event_counts = world_state.get("played_event_counts", {})
    if not isinstance(played_event_counts, dict):
        played_event_counts = {}
    recent_event_ids = world_state.get("recent_event_ids", [])
    if not isinstance(recent_event_ids, list):
        recent_event_ids = []
    last_event_segment_by_id = world_state.get("last_event_segment_by_id", {})
    if not isinstance(last_event_segment_by_id, dict):
        last_event_segment_by_id = {}
    any_event_selected = False
    for src in placed:
        if str(src.get("layer", src.get("category", ""))).lower() == "event":
            eid = str(src.get("asset_id") or src.get("source_id") or "")
            if eid:
                any_event_selected = True
                try:
                    played_event_counts[eid] = int(played_event_counts.get(eid, 0)) + 1
                except (TypeError, ValueError):
                    played_event_counts[eid] = 1
                recent_event_ids.append(eid)
                last_event_segment_by_id[eid] = new_segment_index
    if len(recent_event_ids) > 3:
        recent_event_ids = recent_event_ids[-3:]
    world_state["played_event_counts"] = played_event_counts
    world_state["recent_event_ids"] = recent_event_ids
    world_state["last_event_segment_by_id"] = last_event_segment_by_id
    if any_event_selected:
        world_state["last_event_segment"] = new_segment_index
    else:
        world_state.setdefault("last_event_segment", -999)

    segment_id = f"segment_{new_segment_index:03d}"

    return build_unity_scene(
        scene_id=previous_scene.get("scene_id"),
        segment_id=segment_id,
        scene_type=current_scene_family,
        atmosphere=atmosphere,
        narration_script=narration,
        sources=placed,
        duration_sec=60,
        world_state=world_state,
        mental_state=mental_state,
    )
