def scene_to_commands(scene_json, prev_ids=set()):
    commands = []
    current_ids = set()

    sources = scene_json.get("sources", [])

    for s in sources:
        sid = s.get("source_id")
        current_ids.add(sid)

        position = s.get("position", {"x": 0, "y": 0, "z": 2})
        volume = s.get("volume", 0.5)

        cmd = {
            "action": "create" if sid not in prev_ids else "update",
            "id": sid,
            "clip": "wind",  # 👈 随便写一个先保证 Unity 不报错
            "position": [position["x"], position["y"], position["z"]],
            "volume": volume
        }

        # =========================
        # 🌀 关键：直接用 LLM motion
        # =========================
        motion = s.get("motion")

        # 👉 标准化（关键！）
        motion = normalize_motion(motion)

        if motion:
            cmd["motion"] = motion

        commands.append(cmd)

    # delete
    for old_id in prev_ids:
        if old_id not in current_ids:
            commands.append({
                "action": "delete",
                "id": old_id
            })

    return {"commands": commands}, current_ids


# =========================
# 🧠 motion 统一翻译
# =========================
def normalize_motion(motion):
    if motion is None:
        return None

    mtype = motion.get("type")

    # 🔥 LLM → Unity mapping
    if mtype == "slow_orbit":
        return {
            "type": "circle",
            "speed": 0.2,
            "radius": 2.5
        }

    if mtype == "orbit":
        return {
            "type": "circle",
            "speed": motion.get("speed", 0.5),
            "radius": motion.get("radius", 2.0)
        }

    if mtype == "breathing":
        return {
            "type": "breathing",
            "speed": motion.get("speed", 0.2),
            "minRadius": motion.get("minRadius", 1.5),
            "maxRadius": motion.get("maxRadius", 3.0)
        }

    if mtype == "random":
        return {
            "type": "random"
        }

    if mtype == "none":
        return {
            "type": "none"
        }

    # ❗未知 motion → 不传
    return None