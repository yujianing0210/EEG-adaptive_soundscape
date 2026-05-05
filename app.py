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
    "session_ended": False,
    "dashboard_summary": None,
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
    "session_dashboard_summary.json",
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


def _read_runtime_state() -> Optional[dict]:
    runtime_file = OUTPUTS / "unity_runtime_state.json"
    if not runtime_file.exists():
        return None
    try:
        with open(runtime_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _source_position(source: dict) -> dict:
    position = source.get("position") or {}
    if isinstance(position, list):
        return {
            "x": float(position[0]) if len(position) > 0 else 0.0,
            "y": float(position[1]) if len(position) > 1 else 0.0,
            "z": float(position[2]) if len(position) > 2 else 0.0,
        }
    if isinstance(position, dict):
        return {
            "x": float(position.get("x", 0.0) or 0.0),
            "y": float(position.get("y", 0.0) or 0.0),
            "z": float(position.get("z", 0.0) or 0.0),
        }
    return {"x": 0.0, "y": 0.0, "z": 0.0}


def _audio_snapshot(scene: Optional[dict], idx: int) -> dict:
    if not scene:
        return {"step": idx, "active_sources": [], "sources": []}
    active = set((scene.get("world_state") or {}).get("active_sources") or [])
    sources = []
    for source in scene.get("sources", []) or []:
        sid = source.get("source_id") or source.get("asset_id")
        if not sid:
            continue
        sources.append({
            "id": sid,
            "asset_id": source.get("asset_id"),
            "layer": source.get("layer") or source.get("category"),
            "category": source.get("category") or source.get("layer"),
            "volume": source.get("volume", 0.0),
            "loop": bool(source.get("loop", False)),
            "active": sid in active,
            "position": _source_position(source),
            "motion": source.get("motion"),
        })
    return {
        "step": idx,
        "active_sources": sorted(active),
        "sources": sources,
    }


def _build_dashboard_summary() -> dict:
    windows = STATE.get("windows") or []
    current_idx = STATE.get("current_idx", -1)
    processed_windows = windows[: current_idx + 1] if current_idx >= 0 else []
    mental_history = STATE.get("mental_history") or []
    scene_history = STATE.get("scene_history") or []

    timeline = []
    for idx, payload in enumerate(processed_windows):
        features = payload.get("current_features", {}) or {}
        mental = mental_history[idx] if idx < len(mental_history) else {}
        scene = scene_history[idx + 1] if idx + 1 < len(scene_history) else STATE.get("scene")
        timeline.append({
            "step": idx,
            "time_sec": idx * 30,
            "window_id": payload.get("window_id", idx),
            "time_range_sec": payload.get("time_range_sec"),
            "rule_state": payload.get("current_rule_state"),
            "llm_state": mental.get("llm_state"),
            "trend": mental.get("trend"),
            "confidence": mental.get("confidence"),
            "bands": {
                "delta": features.get("delta_mean"),
                "theta": features.get("theta_mean"),
                "alpha": features.get("alpha_mean"),
                "beta": features.get("beta_mean"),
                "gamma": features.get("gamma_mean"),
            },
            "scores": {
                "alpha_beta_ratio": features.get("alpha_beta_ratio"),
                "theta_beta_ratio": features.get("theta_beta_ratio"),
                "stability_score": features.get("stability_score"),
                "attention_score": features.get("attention_score"),
                "relaxation_score": features.get("relaxation_score"),
            },
            "audio": _audio_snapshot(scene, idx),
        })

    if not timeline and STATE.get("scene"):
        timeline.append({
            "step": 0,
            "time_sec": 0,
            "window_id": None,
            "rule_state": None,
            "llm_state": None,
            "trend": None,
            "confidence": None,
            "bands": {},
            "scores": {},
            "audio": _audio_snapshot(STATE.get("scene"), 0),
        })

    state_counts: Dict[str, int] = {}
    for item in timeline:
        state = item.get("llm_state") or item.get("rule_state") or "unknown"
        state_counts[state] = state_counts.get(state, 0) + 1

    audio_tracks: Dict[str, dict] = {}
    for item in timeline:
        for source in item["audio"].get("sources", []):
            track = audio_tracks.setdefault(source["id"], {
                "id": source["id"],
                "layer": source.get("layer"),
                "category": source.get("category"),
                "points": [],
            })
            track["points"].append({
                "time_sec": item["time_sec"],
                "position": source.get("position"),
                "volume": source.get("volume"),
                "active": source.get("active"),
            })

    return {
        "prompt": STATE.get("prompt"),
        "scene_type": (STATE.get("scene") or {}).get("scene_type"),
        "ended_at": __import__("time").time(),
        "duration_sec": timeline[-1]["time_sec"] if timeline else 0,
        "sample_interval_sec": 30,
        "window_count": len(timeline),
        "state_counts": state_counts,
        "timeline": timeline,
        "audio_tracks": list(audio_tracks.values()),
        "runtime": _read_runtime_state(),
    }


def _score_to_100(value: Any) -> Optional[int]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return 0
    if n <= 1:
        return int(round(n * 100))
    return int(round((n / (n + 1)) * 100))


def _mean_int(values: list) -> int:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return 0
    return int(round(sum(nums) / len(nums)))


def _pretty_source_label(source_id: Any) -> str:
    text = str(source_id or "Unknown Sound")
    for prefix in ("forest_", "ocean_", "beach_", "common_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    for suffix in ("_01", "_02", "_03"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return " ".join(part.capitalize() for part in text.replace("-", "_").split("_") if part)


def _summary_state_label(item: dict) -> str:
    state = str(item.get("llm_state") or item.get("rule_state") or "").lower()
    if "relax" in state or "focus" in state:
        return "focused"
    if "sett" in state or "calm" in state:
        return "calm"
    return "distracted"


def _load_dashboard_summary() -> dict:
    if STATE.get("dashboard_summary"):
        return STATE["dashboard_summary"]
    if STATE.get("prompt") and not STATE.get("session_ended"):
        return _build_dashboard_summary()
    summary_file = OUTPUTS / "session_dashboard_summary.json"
    if summary_file.exists():
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return _build_dashboard_summary()
    return _build_dashboard_summary()


def _dashboard_to_session_summary(summary: dict) -> dict:
    timeline = summary.get("timeline") or []
    sample_interval = int(summary.get("sample_interval_sec") or 30)
    duration = int(summary.get("duration_sec") or 0)
    if timeline:
        last = timeline[-1]
        time_range = last.get("time_range_sec") or []
        if len(time_range) >= 2:
            duration = max(duration, int(float(time_range[1])))
        duration = max(duration, int(last.get("time_sec") or 0) + sample_interval)
    duration = max(duration, sample_interval if timeline else 0)

    mental_timeline = []
    attention_values = []
    relaxation_values = []
    stability_values = []
    for item in timeline:
        scores = item.get("scores") or {}
        attention = _score_to_100(scores.get("attention_score"))
        relaxation = _score_to_100(scores.get("relaxation_score") or scores.get("alpha_beta_ratio"))
        stability = _score_to_100(scores.get("stability_score"))
        if attention is not None:
            attention_values.append(attention)
        if relaxation is not None:
            relaxation_values.append(relaxation)
        if stability is not None:
            stability_values.append(stability)
        mental_timeline.append({
            "time_sec": int(item.get("time_sec") or 0),
            "attention": attention if attention is not None else 0,
            "relaxation": relaxation if relaxation is not None else 0,
            "stability": stability if stability is not None else 0,
            "status": item.get("llm_state") or item.get("rule_state") or "unknown",
            "mental_state": _summary_state_label(item),
        })

    audio_timeline = []
    previous_active = set()
    audio_events = []
    for idx, item in enumerate(timeline):
        start = int(item.get("time_sec") or idx * sample_interval)
        if idx + 1 < len(timeline):
            end = int(timeline[idx + 1].get("time_sec") or (start + sample_interval))
        else:
            end = max(duration, start + sample_interval)
        sources = (item.get("audio") or {}).get("sources") or []
        current_active = set()
        for source in sources:
            if not source.get("active", True):
                continue
            source_id = source.get("asset_id") or source.get("id")
            if not source_id:
                continue
            layer = str(source.get("layer") or source.get("category") or "ambient").lower()
            if layer not in {"ambient", "event", "action"}:
                layer = "ambient"
            current_active.add(str(source_id))
            audio_timeline.append({
                "layer": layer,
                "resource": source_id,
                "label": _pretty_source_label(source_id),
                "start_sec": start,
                "end_sec": end,
            })
            if source_id not in previous_active:
                verb = "triggered" if layer == "action" else ("introduced" if layer == "event" else "started")
                audio_events.append({
                    "time_sec": start,
                    "label": f"{_pretty_source_label(source_id)} {verb}",
                    "type": layer,
                    "resource": source_id,
                })
        previous_active = current_active

    merged_audio = []
    for item in audio_timeline:
        if (
            merged_audio
            and merged_audio[-1]["resource"] == item["resource"]
            and merged_audio[-1]["layer"] == item["layer"]
            and merged_audio[-1]["end_sec"] == item["start_sec"]
        ):
            merged_audio[-1]["end_sec"] = item["end_sec"]
        else:
            merged_audio.append(item)

    layer_totals = {"ambient": 0, "event": 0, "action": 0}
    resource_totals: Dict[str, dict] = {}
    for item in merged_audio:
        layer = item["layer"]
        dur = max(0, int(item["end_sec"]) - int(item["start_sec"]))
        layer_totals[layer] = layer_totals.get(layer, 0) + dur
        bucket = resource_totals.setdefault(str(item["resource"]), {
            "label": item["label"],
            "type": layer,
            "duration": 0,
        })
        bucket["duration"] += dur

    layer_total = sum(layer_totals.values()) or 1
    ambient_pct = int(round(layer_totals.get("ambient", 0) / layer_total * 100))
    event_pct = int(round(layer_totals.get("event", 0) / layer_total * 100))
    action_pct = max(0, 100 - ambient_pct - event_pct)

    top_items = sorted(resource_totals.values(), key=lambda x: x["duration"], reverse=True)[:5]
    top_total = sum(item["duration"] for item in top_items) or 1
    top_audio = [
        {
            "label": item["label"],
            "percent": int(round(item["duration"] / top_total * 100)),
            "type": item["type"],
        }
        for item in top_items
    ]

    first_state = timeline[0].get("llm_state") or timeline[0].get("rule_state") if timeline else "the opening state"
    last_state = timeline[-1].get("llm_state") or timeline[-1].get("rule_state") if timeline else "the closing state"
    top_names = ", ".join(item["label"].lower() for item in top_audio[:2]) or "the active soundscape"

    return {
        "session": {
            "duration_sec": duration,
            "prompt": summary.get("prompt"),
            "scene_type": summary.get("scene_type"),
        },
        "metrics": {
            "average_attention": _mean_int(attention_values),
            "average_relaxation": _mean_int(relaxation_values),
            "average_stability": _mean_int(stability_values),
        },
        "ai_summary": (
            f"Across {len(timeline)} EEG window(s), your interpreted state moved from "
            f"{first_state} toward {last_state}, while the system adapted the soundscape in response."
        ),
        "mental_timeline": mental_timeline,
        "audio_events": audio_events[:6],
        "audio_timeline": merged_audio,
        "audio_composition": {
            "ambient": ambient_pct,
            "event": event_pct,
            "action": action_pct,
        },
        "top_audio_elements": top_audio,
        "insight": (
            f"The strongest audio presence came from {top_names}. These active layers coincided with "
            "the measured attention, relaxation, and stability trajectory shown above."
        ),
    }


def _make_stopped_scene(scene: Optional[dict]) -> dict:
    stopped = dict(scene or {})
    world_state = dict(stopped.get("world_state") or {})
    world_state["active_sources"] = []
    world_state["session_status"] = "ended"
    stopped["world_state"] = world_state
    stopped["sources"] = []
    stopped["session_status"] = "ended"
    return stopped


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
    STATE["session_ended"] = False
    STATE["dashboard_summary"] = None

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


@app.get("/summary")
def summary_page():
    return render_template("summary.html")


@app.get("/api/session_summary")
def api_session_summary():
    return jsonify(_dashboard_to_session_summary(_load_dashboard_summary()))


@app.post("/api/end_session")
def api_end_session():
    summary = _build_dashboard_summary()
    stop_realtime_session()

    stopped_scene = _make_stopped_scene(STATE.get("scene"))
    STATE["scene"] = stopped_scene
    STATE["realtime_active"] = False
    STATE["session_ended"] = True
    STATE["dashboard_summary"] = summary

    write_json(summary, "session_dashboard_summary.json")
    write_json(stopped_scene, "current_unity_scene.json")

    return jsonify({
        **_state_snapshot(),
        "active": False,
        "ended": True,
        "dashboard": summary,
    })


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

    runtime = _read_runtime_state()

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
