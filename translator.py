import os

UNITY_VOLUME_BOOST = float(os.getenv("UNITY_VOLUME_BOOST", 1.0))
UNITY_AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif")

# =========================
# 主函数
# =========================
def scene_to_commands(scene_json, prev_ids=None):
    if prev_ids is None:
        prev_ids = set()

    commands = []
    current_ids = set()
    segment_id = str(scene_json.get("segment_id", ""))
    explicit_stop_ids = {
        str(source_id)
        for source_id in (
            scene_json.get("stop_source_ids")
            or (scene_json.get("world_state") or {}).get("stop_source_ids")
            or []
        )
        if source_id
    }

    sources = scene_json.get("sources", [])

    for s in sources:
        sid = s.get("source_id")
        if sid is None:
            continue

        current_ids.add(sid)

        # =========================
        # 基本参数
        # =========================
        layer = s.get("layer", s.get("category", ""))
        category = s.get("category", s.get("layer", ""))
        is_action = str(layer or category).lower() == "action"
        position = {"x": 0, "y": 0, "z": 0} if is_action else s.get("position", {"x": 0, "y": 0, "z": 2})
        volume = min(0.85, s.get("volume", 0.5) * UNITY_VOLUME_BOOST)

        # =========================
        # clip（从 asset_ref 提取）
        # =========================
        clip = extract_clip(s)

        if clip is None:
            print(f"⚠️ Missing clip for {sid}, skipping")
            continue

        cmd = {
            "action": "create" if sid not in prev_ids else "update",
            "id": sid,
            "clip": clip,
            "layer": layer,
            "category": category,
            "segment_id": segment_id,
            "position": [position["x"], position["y"], position["z"]],
            "relative_to_listener": is_action or bool(s.get("relative_to_listener", False)),
            "volume": volume,
            "loop": bool(s.get("loop", s.get("category") == "ambient")),
            "repeat_count": int(s.get("repeat_count", 1)),
            "repeat_interval_sec": float(s.get("repeat_interval_sec", 0)),
        }

        # =========================
        # motion（核心）
        # =========================
        motion = s.get("motion")
        motion = normalize_motion(motion)

        if motion is None:
            motion = infer_motion(s)

        if motion:
            cmd["motion"] = motion

        commands.append(cmd)

    # =========================
    # 删除消失的对象
    # =========================
    deleted_ids = set()
    for old_id in sorted(explicit_stop_ids):
        if old_id not in current_ids:
            commands.append({
                "action": "delete",
                "id": old_id
            })
            deleted_ids.add(old_id)

    for old_id in prev_ids:
        if old_id not in current_ids and old_id not in deleted_ids:
            commands.append({
                "action": "delete",
                "id": old_id
            })

    return {"commands": commands}, current_ids


# =========================
# 提取音源（关键）
# =========================
def extract_clip(source):
    asset = source.get("asset_ref", "")

    if not asset:
        return None

    if "://" in asset:
        asset = asset.split("://", 1)[1]

    normalized = asset.replace("\\", "/")
    lower = normalized.lower()
    for ext in UNITY_AUDIO_EXTENSIONS:
        if lower.endswith(ext):
            return normalized[: -len(ext)]

    return normalized


# =========================
# motion 标准化（防 LLM 乱写）
# =========================
def normalize_motion(motion):
    if motion is None:
        return None
    if not isinstance(motion, dict):
        return None

    mtype = str(motion.get("type", "")).lower()

    def _as_vec3(value):
        if isinstance(value, list) and len(value) >= 3:
            return [float(value[0]), float(value[1]), float(value[2])]
        if isinstance(value, dict):
            return [
                float(value.get("x", 0.0)),
                float(value.get("y", 0.0)),
                float(value.get("z", 0.0)),
            ]
        return None

    def _copy_listener_flags(out):
        if "around_listener" in motion:
            out["around_listener"] = bool(motion.get("around_listener"))
        if "relative_to_listener" in motion:
            out["relative_to_listener"] = bool(motion.get("relative_to_listener"))
        return out

    if mtype == "slow_orbit":
        return _copy_listener_flags({
            "type": "orbit",
            "speed": 0.22,
            "radius": 1.2
        })

    elif mtype == "orbit" or mtype == "circle":
        out = {
            "type": "orbit",
            "speed": float(motion.get("speed", 0.5)),
            "radius": float(motion.get("radius", 2.0))
        }
        center = _as_vec3(motion.get("center"))
        if center is not None:
            out["center"] = center
        return _copy_listener_flags(out)

    elif mtype == "breathing":
        return _copy_listener_flags({
            "type": "breathing",
            "speed": float(motion.get("speed", 0.2)),
            "minRadius": float(motion.get("minRadius", 1.5)),
            "maxRadius": float(motion.get("maxRadius", 3.0))
        })

    elif mtype == "random":
        return _copy_listener_flags({
            "type": "random"
        })

    elif mtype == "none":
        return _copy_listener_flags({
            "type": "none"
        })

    elif mtype == "drift":
        out = {
            "type": "drift",
            "duration": float(motion.get("duration", 12.0)),
            "repeat": bool(motion.get("repeat", True)),
        }
        start = _as_vec3(motion.get("start"))
        end = _as_vec3(motion.get("end"))
        if start is not None:
            out["start"] = start
        if end is not None:
            out["end"] = end
        return _copy_listener_flags(out)

    elif mtype == "overhead_pass":
        out = {
            "type": "overhead_pass",
            "duration": float(motion.get("duration", 6.0)),
            "repeat": bool(motion.get("repeat", False)),
            "pass_count": int(motion.get("pass_count", 1)),
        }
        start = _as_vec3(motion.get("start"))
        end = _as_vec3(motion.get("end"))
        if start is not None:
            out["start"] = start
        if end is not None:
            out["end"] = end
        return _copy_listener_flags(out)

    elif mtype == "approach_recede":
        out = {
            "type": "approach_recede",
            "duration": float(motion.get("duration", 9.0)),
            "repeat": bool(motion.get("repeat", False)),
            "pass_count": int(motion.get("pass_count", 1)),
            "volume_curve": str(motion.get("volume_curve", "")),
        }
        start = _as_vec3(motion.get("start"))
        mid = _as_vec3(motion.get("mid"))
        end = _as_vec3(motion.get("end"))
        if start is not None:
            out["start"] = start
        if mid is not None:
            out["mid"] = mid
        if end is not None:
            out["end"] = end
        return _copy_listener_flags(out)

    elif mtype == "local_random":
        out = {
            "type": "local_random",
            "radius": float(motion.get("radius", 0.35)),
            "speed": float(motion.get("speed", 0.04)),
        }
        center = _as_vec3(motion.get("center"))
        if center is not None:
            out["center"] = center
        return _copy_listener_flags(out)

    print(f"Unknown motion type: {mtype}")
    return _copy_listener_flags({"type": "none"})


# =========================
# fallback motion（保证不会不动）
# =========================
def infer_motion(source):
    category = source.get("category", "")

    if category == "ambient":
        return {
            "type": "none"
        }

    elif category == "event":
        return {
            "type": "circle",
            "speed": 0.28,
            "radius": 1.4
        }

    elif category == "narration":
        return {
            "type": "none"
        }

    return None
