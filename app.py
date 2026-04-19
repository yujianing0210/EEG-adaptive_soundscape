from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any

from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv

from scripts.eeg_pipeline import run_pipeline, save_windows, DEFAULT_EEG_FILE, WINDOW_SEC, STEP_SEC
from scripts.scene_logic import bootstrap_scene, interpret_window, adapt_scene
from lib.mock_sound_library import load_audio_library

load_dotenv()

app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")
app.secret_key = "dev-key"

STATE: Dict[str, Any] = {
    "prompt": None,
    "scene": None,
    "windows": [],
    "current_idx": -1,
    "mental_history": [],
}

OUTPUTS = Path("outputs")
OUTPUTS.mkdir(exist_ok=True)


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
    )


@app.post("/bootstrap")
def do_bootstrap():
    user_prompt = request.form.get("prompt", "").strip()
    if not user_prompt:
        flash("Please enter a prompt.")
        return redirect(url_for("index"))

    # refresh EEG windows
    df, payloads = run_pipeline(file_path=DEFAULT_EEG_FILE, window_sec=WINDOW_SEC, step_sec=STEP_SEC, strict_hsi=True)
    save_windows(df, payloads, outputs_dir=str(OUTPUTS))

    scene = bootstrap_scene(user_prompt)
    write_json(scene, "initial_scene.json")

    STATE.update({
        "prompt": user_prompt,
        "scene": scene,
        "windows": payloads,
        "current_idx": -1,
        "mental_history": [],
    })

    flash("Initial scene generated and EEG windows prepared.")
    return redirect(url_for("index"))


@app.post("/step")
def step_scene():
    if not STATE["scene"]:
        flash("Run bootstrap first.")
        return redirect(url_for("index"))

    ensure_windows()
    next_idx = STATE["current_idx"] + 1
    if next_idx >= len(STATE["windows"]):
        flash("No more EEG windows.")
        return redirect(url_for("index"))

    payload = STATE["windows"][next_idx]
    mental = interpret_window(payload)
    write_json(mental, f"eeg_window_{next_idx:02d}_interpretation.json")

    updated_scene = adapt_scene(STATE["scene"], mental)
    write_json(updated_scene, f"eeg_window_{next_idx:02d}_scene_update.json")
    write_json(updated_scene, "current_unity_scene.json")

    STATE["scene"] = updated_scene
    STATE["current_idx"] = next_idx
    STATE["mental_history"].append({
        "window_id": payload.get("window_id"),
        "rule_state": payload.get("current_rule_state"),
        "llm_state": mental.get("state_label"),
        "trend": mental.get("trend"),
        "confidence": mental.get("confidence"),
    })

    flash(f"Processed window {next_idx}.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
