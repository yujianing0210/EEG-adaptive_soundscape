import os

UNITY_VOLUME_BOOST = float(os.getenv("UNITY_VOLUME_BOOST", 1.0))
UNITY_AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif")

# =========================
# 🎯 主函数
# =========================
def scene_to_commands(scene_json, prev_ids=None):
    if prev_ids is None:
        prev_ids = set()

    commands = []
    current_ids = set()

    sources = scene_json.get("sources", [])

    for s in sources:
        sid = s.get("source_id")
        if sid is None:
            continue

        current_ids.add(sid)

        # =========================
        # 📍 基本参数
        # =========================
        position = s.get("position", {"x": 0, "y": 0, "z": 2})
        volume = min(0.85, s.get("volume", 0.5) * UNITY_VOLUME_BOOST)

        # =========================
        # 🔊 clip（从 asset_ref 提取）
        # =========================
        clip = extract_clip(s)

        if clip is None:
            print(f"⚠️ Missing clip for {sid}, skipping")
            continue

        cmd = {
            "action": "create" if sid not in prev_ids else "update",
            "id": sid,
            "clip": clip,
            "position": [position["x"], position["y"], position["z"]],
            "volume": volume,
            "loop": bool(s.get("loop", s.get("category") == "ambient")),
            "repeat_count": int(s.get("repeat_count", 1)),
            "repeat_interval_sec": float(s.get("repeat_interval_sec", 0)),
        }

        # =========================
        # 🌀 motion（核心🔥）
        # =========================
        motion = s.get("motion")
        motion = normalize_motion(motion)

        if motion is None:
            motion = infer_motion(s)

        if motion:
            cmd["motion"] = motion

        commands.append(cmd)

    # =========================
    # 🔴 删除消失的对象
    # =========================
    for old_id in prev_ids:
        if old_id not in current_ids:
            commands.append({
                "action": "delete",
                "id": old_id
            })

    return {"commands": commands}, current_ids


# =========================
# 🎧 提取音源（关键🔥）
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
# 🧠 motion 标准化（防 LLM 乱写🔥）
# =========================
def normalize_motion(motion):
    if motion is None:
        return None
    if not isinstance(motion, dict):
        return None

    mtype = motion.get("type")

    # 🔁 LLM → Unity mapping

    if mtype == "slow_orbit":
        return {
            "type": "circle",
            "speed": 0.22,
            "radius": 1.2
        }

    elif mtype == "orbit":
        return {
            "type": "circle",
            "speed": motion.get("speed", 0.5),
            "radius": motion.get("radius", 2.0)
        }

    elif mtype == "breathing":
        return {
            "type": "breathing",
            "speed": motion.get("speed", 0.2),
            "minRadius": motion.get("minRadius", 1.5),
            "maxRadius": motion.get("maxRadius", 3.0)
        }

    elif mtype == "random":
        return {
            "type": "random"
        }

    elif mtype == "none":
        return {
            "type": "none"
        }

    # ❗未知 motion → 丢弃（防炸）
    print(f"⚠️ Unknown motion type: {mtype}")
    return None


# =========================
# 🔁 fallback motion（保证不会不动🔥）
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
