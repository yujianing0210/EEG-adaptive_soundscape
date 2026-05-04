from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv

from scripts.eeg_pipeline import run_pipeline, save_windows, DEFAULT_EEG_FILE, WINDOW_SEC, STEP_SEC
from scripts.scene_logic import bootstrap_scene, interpret_window, adapt_scene
from lib.mock_sound_library import load_audio_library
from translator import scene_to_commands
from muse_realtime import (
    has_realtime_payloads,
    pop_realtime_payload,
    get_realtime_payload_history,
    get_realtime_diagnostics,
    start_realtime_session,
    stop_realtime_session,
)

load_dotenv()

app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")
app.secret_key = "dev-key"

STATE: Dict[str, Any] = {
    "prompt": None,
    "scene": None,
    "windows": [],
    "current_idx": -1,
    "mental_history": [],
    "eeg_mode": "recorded",
    "realtime_active": False,
    "realtime_summary": None,
    "last_summary_at": None,
}

OUTPUTS = Path("outputs")
OUTPUTS.mkdir(exist_ok=True)

SESSION_OUTPUT_PATTERNS = (
    "initial_scene.json",
    "current_unity_scene.json",
    "unity_runtime_state.json",
    "eeg_windows.csv",
    "eeg_payloads.json",
    "eeg_payloads.jsonl",
    "eeg_window_*_interpretation.json",
    "eeg_window_*_scene_update.json",
    "realtime_summary*.json",
    "realtime_summary_scene*.json",
    "realtime_payload_history.json",
)


def clear_session_outputs():
    """Remove generated session artifacts so a new bootstrap starts clean."""
    OUTPUTS.mkdir(exist_ok=True)
    for pattern in SESSION_OUTPUT_PATTERNS:
        for path in OUTPUTS.glob(pattern):
            if path.is_file():
                try:
                    path.unlink()
                except OSError as exc:
                    app.logger.warning("Could not remove stale output %s: %s", path, exc)


def ensure_windows():
    if STATE["windows"]:
        return
    df, payloads = run_pipeline(file_path=DEFAULT_EEG_FILE, window_sec=WINDOW_SEC, step_sec=STEP_SEC, strict_hsi=True)
    save_windows(df, payloads, outputs_dir=str(OUTPUTS))
    STATE["windows"] = payloads


def write_json(obj: Any, name: str):
    OUTPUTS.mkdir(exist_ok=True)
    with open(OUTPUTS / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def aggregate_recent_payloads(payloads: list) -> Optional[dict]:
    if not payloads:
        return None
    recent = payloads[-3:]
    feature_keys = set().union(*(p.get("current_features", {}).keys() for p in recent))
    aggregated = {
        "window_id": recent[-1].get("window_id"),
        "time_range_sec": [
            recent[0].get("time_range_sec", [0, 0])[0],
            recent[-1].get("time_range_sec", [0, 0])[1],
        ],
        "window_length_sec": int(sum(p.get("window_length_sec", WINDOW_SEC) for p in recent) / len(recent)),
        "step_sec": recent[-1].get("step_sec", STEP_SEC),
        "current_features": {},
        "current_rule_state": recent[-1].get("current_rule_state"),
        "history_summary": [
            {
                "window_id": p.get("window_id"),
                "rule_state": p.get("current_rule_state"),
                "alpha_beta_ratio": p.get("current_features", {}).get("alpha_beta_ratio"),
                "stability_score": p.get("current_features", {}).get("stability_score"),
            }
            for p in recent[:-1]
        ],
    }

    for key in feature_keys:
        values = [p["current_features"].get(key) for p in recent if p.get("current_features", {}).get(key) is not None]
        if values:
            aggregated["current_features"][key] = float(sum(values) / len(values))
        else:
            aggregated["current_features"][key] = None

    if len(recent) > 1:
        prev_features = recent[-2].get("current_features", {})
        aggregated["previous_features"] = prev_features
        aggregated["previous_state"] = {
            "rule_state": recent[-2].get("current_rule_state"),
            "llm_state": None,
        }
    else:
        aggregated["previous_features"] = None
        aggregated["previous_state"] = None
    aggregated["feature_deltas"] = {
        f"{k}_change": aggregated["current_features"].get(k) - aggregated["previous_features"].get(k)
        for k in aggregated["current_features"]
        if aggregated["previous_features"] and aggregated["current_features"].get(k) is not None and aggregated["previous_features"].get(k) is not None
    } if aggregated["previous_features"] else None

    return aggregated


def update_realtime_summary_if_due():
    from time import time

    if not STATE["realtime_active"] or not STATE["scene"]:
        return

    now = time()
    last = STATE.get("last_summary_at")
    if last is not None and now - last < 30:
        return

    payloads = get_realtime_payload_history(max_items=6)
    if len(payloads) < 2:
        return

    summary_payload = aggregate_recent_payloads(payloads)
    if summary_payload is None:
        return

    mental = interpret_window(summary_payload)
    updated_scene = adapt_scene(STATE["scene"], mental)
    write_json(updated_scene, f"realtime_summary_scene_{len(STATE['mental_history']) + 1:02d}.json")
    write_json(mental, f"realtime_summary_{len(STATE['mental_history']) + 1:02d}.json")

    STATE["scene"] = updated_scene
    STATE["realtime_summary"] = {
        "summary_time": int(now),
        "window_ids": [p.get("window_id") for p in payloads],
        "state_label": mental.get("state_label"),
        "confidence": mental.get("confidence"),
        "trend": mental.get("trend"),
        "interpretation": mental.get("interpretation"),
        "scene_implication": mental.get("scene_implication"),
    }
    STATE["last_summary_at"] = now
    STATE["mental_history"].append({
        "window_id": summary_payload.get("window_id"),
        "rule_state": summary_payload.get("current_rule_state"),
        "llm_state": mental.get("state_label"),
        "trend": mental.get("trend"),
        "confidence": mental.get("confidence"),
        "auto_summary": True,
    })


@app.route("/")
def index():
    library = load_audio_library()
    current_window = None
    current_payload = None
    if STATE["windows"] and STATE["current_idx"] >= 0:
        current_payload = STATE["windows"][STATE["current_idx"]]
        current_window = current_payload.get("window_id")
    return render_template(
        "index.html",
        prompt=STATE["prompt"],
        scene=STATE["scene"],
        library=library,
        current_idx=STATE["current_idx"],
        total_windows=len(STATE["windows"]),
        current_payload=current_payload,
        mental_history=STATE["mental_history"],
        eeg_path=DEFAULT_EEG_FILE,
        eeg_mode=STATE["eeg_mode"],
        realtime_active=STATE["realtime_active"],
    )


@app.post("/bootstrap")
def do_bootstrap():
    user_prompt = request.form.get("prompt", "").strip()
    eeg_mode = request.form.get("eeg_mode", "recorded")
    if not user_prompt:
        flash("Please enter a prompt.")
        return redirect(url_for("index"))

    bootstrap_session(user_prompt, eeg_mode)
    if eeg_mode == "realtime":
        flash("Realtime EEG session started. Wait for live windows to arrive.")
    else:
        flash("Initial scene generated and EEG windows prepared.")
    return redirect(url_for("index"))


def bootstrap_session(user_prompt: str, eeg_mode: str = "recorded") -> Dict[str, Any]:
    stop_realtime_session()
    clear_session_outputs()

    STATE["eeg_mode"] = eeg_mode
    STATE["realtime_active"] = False
    STATE["windows"] = []
    STATE["current_idx"] = -1
    STATE["mental_history"] = []
    STATE["realtime_summary"] = None
    STATE["last_summary_at"] = None

    if eeg_mode == "realtime":
        scene = bootstrap_scene(user_prompt)
        write_json(scene, "initial_scene.json")
        write_json(scene, "current_unity_scene.json")
        start_realtime_session()

        STATE.update({
            "prompt": user_prompt,
            "scene": scene,
            "scene_history": [scene],
            "realtime_active": True,
        })
        STATE["realtime_summary"] = None
        STATE["last_summary_at"] = None
        return scene

    # refresh EEG windows from pre-recorded CSV
    df, payloads = run_pipeline(file_path=DEFAULT_EEG_FILE, window_sec=WINDOW_SEC, step_sec=STEP_SEC, strict_hsi=True)
    save_windows(df, payloads, outputs_dir=str(OUTPUTS))

    scene = bootstrap_scene(user_prompt)
    write_json(scene, "initial_scene.json")
    write_json(scene, "current_unity_scene.json")

    STATE.update({
        "prompt": user_prompt,
        "scene": scene,
        "windows": payloads,
        "scene_history": [scene],
    })
    STATE["current_payload"] = None
    return scene


@app.post("/api/bootstrap")
def api_bootstrap():
    data = request.get_json(silent=True) or {}
    user_prompt = (data.get("prompt") or "").strip()
    eeg_mode = data.get("eeg_mode", "recorded")
    if not user_prompt:
        return jsonify({"error": "Please enter a prompt."}), 400

    scene = bootstrap_session(user_prompt, eeg_mode)
    return jsonify({
        "scene": scene,
        "prompt": STATE["prompt"],
        "eeg_mode": STATE["eeg_mode"],
        "total_windows": len(STATE["windows"]),
        "realtime_active": STATE["realtime_active"],
    })


@app.post("/step")
def step_scene():
    if not STATE["scene"]:
        flash("Run bootstrap first.")
        return redirect(url_for("index"))

    direction = request.form.get('direction', 'next')

    if direction == 'previous':
        if STATE["eeg_mode"] == "realtime":
            flash("Previous not supported in realtime mode.")
            return redirect(url_for("index"))
        prev_idx = STATE["current_idx"] - 1
        if prev_idx >= 0:
            STATE["current_idx"] = prev_idx
            STATE["scene"] = STATE["scene_history"][prev_idx]
            STATE["current_payload"] = STATE["windows"][prev_idx]
            write_json(STATE["scene"], "current_unity_scene.json")
            flash(f"Jumped to window {prev_idx}.")
        else:
            flash("Already at first window.")
        return redirect(url_for("index"))

    # direction == 'next'
    if STATE["eeg_mode"] == "realtime":
        if not has_realtime_payloads():
            flash("No live EEG window is ready yet. Please wait for the next window.")
            return redirect(url_for("index"))

        payload = pop_realtime_payload()
        STATE["windows"].append(payload)
    else:
        ensure_windows()
        next_idx = STATE["current_idx"] + 1
        if next_idx >= len(STATE["windows"]):
            flash("No more EEG windows.")
            return redirect(url_for("index"))
        payload = STATE["windows"][next_idx]

    next_idx = STATE["current_idx"] + 1
    mental = interpret_window(payload)
    write_json(mental, f"eeg_window_{next_idx:02d}_interpretation.json")

    updated_scene = adapt_scene(STATE["scene"], mental)
    write_json(updated_scene, f"eeg_window_{next_idx:02d}_scene_update.json")
    write_json(updated_scene, "current_unity_scene.json")

    STATE["scene"] = updated_scene
    STATE["scene_history"].append(updated_scene)
    STATE["current_idx"] = next_idx
    STATE["current_payload"] = payload
    STATE["mental_history"].append({
        "window_id": payload.get("window_id"),
        "rule_state": payload.get("current_rule_state"),
        "llm_state": mental.get("state_label"),
        "trend": mental.get("trend"),
        "confidence": mental.get("confidence"),
    })

    flash(f"Processed window {next_idx}.")
    return redirect(url_for("index"))


@app.get("/realtime_status")
def realtime_status():
    update_realtime_summary_if_due()
    history = get_realtime_payload_history(max_items=40)

    plot_points = [
        {
            "time": p.get("time_range_sec", [0, 0])[1],
            "alpha_beta_ratio": p.get("current_features", {}).get("alpha_beta_ratio"),
            "stability_score": p.get("current_features", {}).get("stability_score"),
            "rule_state": p.get("current_rule_state"),
        }
        for p in history
    ]

    latest_summary = STATE.get("realtime_summary")
    latest_payload = history[-1] if history else None
    diagnostics = get_realtime_diagnostics()
    return {
        "active": STATE["realtime_active"],
        "plot_points": plot_points,
        "summary": latest_summary,
        "scene": STATE["scene"],
        "current_payload": latest_payload,
        "pending_window_count": diagnostics.get("pending_window_count", 0),
        "diagnostics": diagnostics,
    }


@app.post("/stop_realtime")
def stop_realtime():
    if not STATE["realtime_active"]:
        flash("Realtime session is not active.")
        return redirect(url_for("index"))

    stop_realtime_session()  # 移除
    STATE["realtime_active"] = False
    flash("Realtime EEG session stopped.")
    return redirect(url_for("index"))


def _state_snapshot():
    idx = STATE["current_idx"]
    payload = STATE["windows"][idx] if idx >= 0 and STATE["windows"] else None
    return {
        "scene": STATE["scene"],
        "current_payload": payload,
        "current_idx": idx,
        "total_windows": len(STATE["windows"]),
        "mental_history": STATE["mental_history"][-10:],
        "done": False,
        "error": None,
    }


@app.route("/api/step", methods=["POST"])
def api_step():
    data = request.get_json(silent=True) or {}
    direction = data.get("direction", "next")

    if not STATE["scene"]:
        return jsonify({"error": "Run bootstrap first."}), 400

    if direction == "previous":
        if STATE["eeg_mode"] == "realtime":
            return jsonify({"error": "Previous not supported in realtime mode.", **_state_snapshot()}), 200
        prev_idx = STATE["current_idx"] - 1
        if prev_idx >= 0:
            STATE["current_idx"] = prev_idx
            history = STATE.get("scene_history", [])
            if prev_idx < len(history):
                STATE["scene"] = history[prev_idx]
            write_json(STATE["scene"], "current_unity_scene.json")
        return jsonify(_state_snapshot())

    # direction == "next"
    if STATE["eeg_mode"] == "realtime":
        if not has_realtime_payloads():
            return jsonify({"error": "No live EEG window ready yet.", **_state_snapshot()}), 200
        payload = pop_realtime_payload()
        STATE["windows"].append(payload)
    else:
        ensure_windows()
        next_idx = STATE["current_idx"] + 1
        if next_idx >= len(STATE["windows"]):
            snap = _state_snapshot()
            snap["done"] = True
            return jsonify(snap), 200
        payload = STATE["windows"][next_idx]

    next_idx = STATE["current_idx"] + 1
    mental = interpret_window(payload)
    write_json(mental, f"eeg_window_{next_idx:02d}_interpretation.json")
    updated_scene = adapt_scene(STATE["scene"], mental)
    write_json(updated_scene, f"eeg_window_{next_idx:02d}_scene_update.json")
    write_json(updated_scene, "current_unity_scene.json")

    STATE["scene"] = updated_scene
    STATE.setdefault("scene_history", []).append(updated_scene)
    STATE["current_idx"] = next_idx
    STATE["mental_history"].append({
        "window_id": payload.get("window_id"),
        "rule_state": payload.get("current_rule_state"),
        "llm_state": mental.get("state_label"),
        "trend": mental.get("trend"),
        "confidence": mental.get("confidence"),
    })

    return jsonify(_state_snapshot())


@app.get("/api/state")
def api_state():
    return jsonify(_state_snapshot())


@app.get("/api/unity_state")
def api_unity_state():
    scene = STATE.get("scene")
    if scene is None:
        current_scene = OUTPUTS / "current_unity_scene.json"
        if current_scene.exists():
            with open(current_scene, "r", encoding="utf-8") as f:
                scene = json.load(f)

    commands = []
    if scene is not None:
        command_json, _ = scene_to_commands(scene, set())
        commands = command_json.get("commands", [])

    runtime = None
    runtime_file = OUTPUTS / "unity_runtime_state.json"
    if runtime_file.exists():
        try:
            with open(runtime_file, "r", encoding="utf-8") as f:
                runtime = json.load(f)
        except Exception:
            runtime = None

    snap = _state_snapshot()
    return jsonify({
        **snap,
        "scene": scene,
        "unity_commands": commands,
        "unity_runtime": runtime,
        "unity_source": "translator.scene_to_commands",
    })


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5001)
