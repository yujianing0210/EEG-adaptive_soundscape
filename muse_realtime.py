import json
import os
import time
import threading
from collections import deque
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from openai import OpenAI

load_dotenv()

###############################################################################
# CONFIG
###############################################################################


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return int(default)
    return int(value)


OSC_IP = os.getenv("OSC_IP", "0.0.0.0")
OSC_PORT = env_int("OSC_PORT", 5000)

WINDOW_SEC = env_int("REALTIME_WINDOW_SEC", env_int("WINDOW_SEC", 60))
STEP_SEC = env_int("REALTIME_STEP_SEC", env_int("STEP_SEC", 20))
REALTIME_WARMUP_SEC = env_int("REALTIME_WARMUP_SEC", 10)
BUFFER_SEC = env_int("REALTIME_BUFFER_SEC", 180)

STRICT_SIGNAL_CHECK = False
USE_LLM = True
ENABLE_PLOT = False

DEBUG = False
PRINT_TABLE_EVERY = 5
TABLE_TAIL_N = 5

RAW_OUTPUT_CSV = os.path.join("outputs", "sliding_window_features.csv")
RAW_PAYLOAD_JSON = os.path.join("outputs", "llm_payloads.json")
RAW_PAYLOAD_JSONL = os.path.join("outputs", "llm_payloads.jsonl")
LLM_OUTPUT_CSV = os.path.join("outputs", "sliding_window_features_with_llm.csv")
OFFLINE_OUTPUT_CSV = os.path.join("outputs", "eeg_windows.csv")
OFFLINE_PAYLOAD_JSON = os.path.join("outputs", "eeg_payloads.json")
OFFLINE_PAYLOAD_JSONL = os.path.join("outputs", "eeg_payloads.jsonl")
RAW_OSC_JSONL = os.path.join("outputs", "mind_monitor_osc_raw.jsonl")

LLM_MODEL = "gpt-4o-mini"

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_colwidth", 80)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


###############################################################################
# DEBUG PRINT
###############################################################################

def dprint(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


###############################################################################
# GLOBAL LOCK
###############################################################################

buffer_lock = threading.RLock()


###############################################################################
# REALTIME BUFFER
###############################################################################

class RealtimeEEGBuffer:
    def __init__(self, max_seconds: int = BUFFER_SEC):
        self.max_seconds = max_seconds
        self.start_wall_time = time.time()
        self.rows = deque()

    def add_row(self, row: dict):
        with buffer_lock:
            self.rows.append(row)
            self._trim_locked()

    def _trim_locked(self):
        now_sec = time.time() - self.start_wall_time
        while self.rows and now_sec - self.rows[0]["time_sec"] > self.max_seconds:
            self.rows.popleft()

    def get_recent_df(self, window_sec: float) -> pd.DataFrame:
        with buffer_lock:
            now_sec = time.time() - self.start_wall_time
            data = [r.copy() for r in self.rows if now_sec - r["time_sec"] <= window_sec]

        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)

    def total_rows(self) -> int:
        with buffer_lock:
            return len(self.rows)


stream_buffer = RealtimeEEGBuffer()
realtime_window_queue = deque()
realtime_payload_history = deque(maxlen=50)
realtime_raw_rows = []
raw_osc_write_queue = deque()
realtime_thread: Optional[threading.Thread] = None
realtime_server = None
realtime_stop_event = threading.Event()
osc_message_count = 0
committed_rows_count = 0
raw_osc_recorded_count = 0
last_osc_address = None
last_osc_at = None
active_window_sec = WINDOW_SEC
active_step_sec = STEP_SEC


###############################################################################
# FRAME CACHE
###############################################################################

def fresh_frame_template():
    return {
        "Delta": None,
        "Theta": None,
        "Alpha": None,
        "Beta": None,
        "Gamma": None,

        "Accelerometer_X": None,
        "Accelerometer_Y": None,
        "Accelerometer_Z": None,

        "Gyro_X": None,
        "Gyro_Y": None,
        "Gyro_Z": None,

        # Placeholder signal quality values
        "HeadBandOn": 1,
        "HSI_TP9": 1,
        "HSI_AF7": 1,
        "HSI_AF8": 1,
        "HSI_TP10": 1,
    }


latest_frame = fresh_frame_template()


###############################################################################
# RESET / CLEAR
###############################################################################

def clear_output_files():
    for path in [
        RAW_OUTPUT_CSV,
        RAW_PAYLOAD_JSON,
        RAW_PAYLOAD_JSONL,
        LLM_OUTPUT_CSV,
        OFFLINE_OUTPUT_CSV,
        OFFLINE_PAYLOAD_JSON,
        OFFLINE_PAYLOAD_JSONL,
        RAW_OSC_JSONL,
    ]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                dprint(f"Could not remove {path}: {e}")


def reset_realtime_state():
    global stream_buffer, latest_frame, osc_message_count, committed_rows_count, raw_osc_recorded_count, last_osc_address, last_osc_at

    with buffer_lock:
        stream_buffer = RealtimeEEGBuffer(max_seconds=BUFFER_SEC)
        latest_frame = fresh_frame_template()
        realtime_payload_history.clear()
        realtime_raw_rows.clear()
        raw_osc_write_queue.clear()
        osc_message_count = 0
        committed_rows_count = 0
        raw_osc_recorded_count = 0
        last_osc_address = None
        last_osc_at = None

    if ENABLE_PLOT:
        try:
            plt.close("all")
        except Exception:
            pass


###############################################################################
# HELPERS
###############################################################################

def save_payloads_to_json(payloads: list, output_file: str = RAW_PAYLOAD_JSON):
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payloads, f, indent=2, ensure_ascii=False)


def save_payloads_jsonl(payloads: list, output_file: str = RAW_PAYLOAD_JSONL):
    with open(output_file, "w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def save_offline_compatible_outputs(result_df: pd.DataFrame, payloads: list) -> None:
    os.makedirs("outputs", exist_ok=True)
    result_df.to_csv(OFFLINE_OUTPUT_CSV, index=False)
    save_payloads_to_json(payloads, OFFLINE_PAYLOAD_JSON)
    save_payloads_jsonl(payloads, OFFLINE_PAYLOAD_JSONL)


def _safe_float_list(args):
    vals = []
    for x in args:
        try:
            vals.append(float(x))
        except Exception:
            pass
    return vals


def parse_band_args(args):
    """
    Parse Mind Monitor OSC band message.
    Prefer averaging first 4 values if 4 channels exist.
    Fall back to a single scalar if only 1 value is present.
    """
    vals = _safe_float_list(args)

    if len(vals) >= 4:
        return float(np.mean(vals[:4]))
    if len(vals) == 1:
        return float(vals[0])
    return None


###############################################################################
# DEBUG HANDLER
###############################################################################

def debug_handler(address, *args):
    note_osc_message(address, *args)
    dprint(f"[DEBUG OSC] address={address} args_len={len(args)} args={args[:6]}")


def _json_safe_osc_arg(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    return str(value)


def note_osc_message(address, *args):
    global osc_message_count, raw_osc_recorded_count, last_osc_address, last_osc_at
    received_at = time.time()
    with buffer_lock:
        osc_message_count += 1
        raw_osc_recorded_count += 1
        last_osc_address = address
        last_osc_at = received_at
        raw_osc_write_queue.append({
            "received_at_unix": received_at,
            "session_elapsed_sec": received_at - stream_buffer.start_wall_time,
            "address": address,
            "args": [_json_safe_osc_arg(value) for value in args],
        })


###############################################################################
# OSC HANDLERS
###############################################################################

def delta_handler(address, *args):
    note_osc_message(address, *args)
    val = parse_band_args(args)
    dprint("[HANDLER] delta", args[:4])
    if val is not None:
        with buffer_lock:
            latest_frame["Delta"] = val


def theta_handler(address, *args):
    note_osc_message(address, *args)
    val = parse_band_args(args)
    dprint("[HANDLER] theta", args[:4])
    if val is not None:
        with buffer_lock:
            latest_frame["Theta"] = val


def alpha_handler(address, *args):
    note_osc_message(address, *args)
    val = parse_band_args(args)
    dprint("[HANDLER] alpha", args[:4])
    if val is not None:
        with buffer_lock:
            latest_frame["Alpha"] = val


def beta_handler(address, *args):
    note_osc_message(address, *args)
    val = parse_band_args(args)
    dprint("[HANDLER] beta", args[:4])
    if val is not None:
        with buffer_lock:
            latest_frame["Beta"] = val


def gamma_handler(address, *args):
    note_osc_message(address, *args)
    val = parse_band_args(args)
    dprint("[HANDLER] gamma", args[:4])
    if val is not None:
        with buffer_lock:
            latest_frame["Gamma"] = val
        maybe_commit_row()


def acc_handler(address, *args):
    note_osc_message(address, *args)
    vals = _safe_float_list(args)
    dprint("[HANDLER] acc", args[:3])
    if len(vals) >= 3:
        with buffer_lock:
            latest_frame["Accelerometer_X"] = vals[0]
            latest_frame["Accelerometer_Y"] = vals[1]
            latest_frame["Accelerometer_Z"] = vals[2]


def gyro_handler(address, *args):
    note_osc_message(address, *args)
    vals = _safe_float_list(args)
    dprint("[HANDLER] gyro", args[:3])
    if len(vals) >= 3:
        with buffer_lock:
            latest_frame["Gyro_X"] = vals[0]
            latest_frame["Gyro_Y"] = vals[1]
            latest_frame["Gyro_Z"] = vals[2]


###############################################################################
# COMMIT
###############################################################################

def maybe_commit_row():
    global latest_frame, committed_rows_count

    needed = ["Delta", "Theta", "Alpha", "Beta", "Gamma"]

    with buffer_lock:
        missing = [k for k in needed if latest_frame[k] is None]
        if missing:
            dprint("[COMMIT] skipped, missing:", missing)
            return

        row = dict(latest_frame)
        row["time_sec"] = time.time() - stream_buffer.start_wall_time

        if all(row.get(k) is not None for k in ["Accelerometer_X", "Accelerometer_Y", "Accelerometer_Z"]):
            row["acc_mag"] = float(np.sqrt(
                row["Accelerometer_X"] ** 2 +
                row["Accelerometer_Y"] ** 2 +
                row["Accelerometer_Z"] ** 2
            ))

        if all(row.get(k) is not None for k in ["Gyro_X", "Gyro_Y", "Gyro_Z"]):
            row["gyro_mag"] = float(np.sqrt(
                row["Gyro_X"] ** 2 +
                row["Gyro_Y"] ** 2 +
                row["Gyro_Z"] ** 2
            ))

        stream_buffer.rows.append(row)
        realtime_raw_rows.append(row.copy())
        stream_buffer._trim_locked()
        committed_rows_count += 1

        dprint(f"[COMMIT] OK time_sec={row['time_sec']:.2f} buffer_size={len(stream_buffer.rows)}")

        for k in needed:
            latest_frame[k] = None


###############################################################################
# QUALITY CHECK
###############################################################################

def recent_signal_ok(window_df: pd.DataFrame) -> bool:
    if len(window_df) == 0:
        return False

    required_cols = ["Delta", "Theta", "Alpha", "Beta", "Gamma"]
    for col in required_cols:
        if col not in window_df.columns:
            return False
        if window_df[col].isna().mean() > 0.2:
            return False

    band_values = window_df[required_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if float(band_values.abs().to_numpy().max()) <= 1e-9:
        return False

    if not STRICT_SIGNAL_CHECK:
        return True

    if "HeadBandOn" in window_df.columns:
        if (window_df["HeadBandOn"] == 1).mean() < 0.8:
            return False

    hsi_cols = ["HSI_TP9", "HSI_AF7", "HSI_AF8", "HSI_TP10"]
    existing = [c for c in hsi_cols if c in window_df.columns]
    if existing:
        for col in existing:
            if (window_df[col] == 1).mean() < 0.8:
                return False

    return True


def window_is_filled_enough(window_df: pd.DataFrame, expected_sec: float) -> bool:
    if len(window_df) < 5:
        return False
    if "time_sec" not in window_df.columns:
        return False

    span = float(window_df["time_sec"].max()) - float(window_df["time_sec"].min())
    return span >= expected_sec * 0.8


###############################################################################
# FEATURE EXTRACTION
###############################################################################

def extract_window_features(window_df: pd.DataFrame) -> dict:
    feats = {}
    eps = 1e-8

    for band in ["Delta", "Theta", "Alpha", "Beta", "Gamma"]:
        feats[f"{band.lower()}_mean"] = float(window_df[band].mean())
        feats[f"{band.lower()}_std"] = float(window_df[band].std())

    feats["alpha_beta_ratio"] = feats["alpha_mean"] / (feats["beta_mean"] + eps)
    feats["theta_beta_ratio"] = feats["theta_mean"] / (feats["beta_mean"] + eps)
    feats["alpha_theta_ratio"] = feats["alpha_mean"] / (feats["theta_mean"] + eps)

    feats["relaxation_score"] = feats["alpha_beta_ratio"]
    feats["attention_score"] = 1 / (feats["theta_beta_ratio"] + eps)

    band_stds = [
        feats["delta_std"],
        feats["theta_std"],
        feats["alpha_std"],
        feats["beta_std"],
        feats["gamma_std"],
    ]
    feats["variance_score"] = float(np.nanmean(band_stds))
    feats["stability_score"] = 1 / (feats["variance_score"] + eps)

    if "acc_mag" in window_df.columns:
        feats["acc_mean"] = float(window_df["acc_mag"].mean())
        feats["acc_std"] = float(window_df["acc_mag"].std())

    if "gyro_mag" in window_df.columns:
        feats["gyro_mean"] = float(window_df["gyro_mag"].mean())
        feats["gyro_std"] = float(window_df["gyro_mag"].std())

    if "Heart_Rate" in window_df.columns:
        hr = pd.to_numeric(window_df["Heart_Rate"], errors="coerce")
        feats["heart_rate_mean"] = float(hr.mean()) if not hr.isna().all() else None

    band_means = [abs(feats.get(f"{band.lower()}_mean", 0.0)) for band in ["Delta", "Theta", "Alpha", "Beta", "Gamma"]]
    feats["signal_quality"] = "ok" if max(band_means or [0.0]) > 1e-9 else "insufficient_eeg_signal"

    return feats


###############################################################################
# RULE-BASED CLASSIFICATION
###############################################################################

def classify_state(features: dict) -> str:
    alpha_beta = features["alpha_beta_ratio"]
    theta_beta = features["theta_beta_ratio"]
    stability = features["stability_score"]

    motion_penalty = False
    if "gyro_std" in features and features["gyro_std"] is not None:
        if features["gyro_std"] > 1.5:
            motion_penalty = True

    if (
        alpha_beta > 1.8
        and 0 < theta_beta < 0.75
        and stability > 6.0
        and not motion_penalty
    ):
        return "stable_relaxation"
    elif alpha_beta > 1.25 and stability > 3.0 and not motion_penalty:
        return "settling"
    elif 0 < theta_beta < 1.1 and stability > 2.0 and not motion_penalty:
        return "effortful_focus"
    else:
        return "distracted_or_unstable"


###############################################################################
# DELTAS / HISTORY / PAYLOAD
###############################################################################

def compute_feature_deltas(current_features: dict, previous_features: Optional[dict]) -> Optional[dict]:
    if previous_features is None:
        return None

    delta_keys = [
        "alpha_mean",
        "beta_mean",
        "theta_mean",
        "delta_mean",
        "gamma_mean",
        "alpha_beta_ratio",
        "theta_beta_ratio",
        "relaxation_score",
        "attention_score",
        "stability_score",
    ]

    deltas = {}
    for key in delta_keys:
        if key in current_features and key in previous_features:
            deltas[f"{key}_change"] = current_features[key] - previous_features[key]

    return deltas


def build_history_summary(state_memory: list, n: int = 3) -> list:
    recent = state_memory[-n:]
    summary = []

    for item in recent:
        summary.append({
            "window_id": item["window_id"],
            "time_range_sec": [item["start_sec"], item["end_sec"]],
            "rule_state": item["rule_state"],
            "llm_state": item.get("llm_state"),
            "alpha_beta_ratio": item["features"]["alpha_beta_ratio"],
            "stability_score": item["features"]["stability_score"],
        })

    return summary


def build_llm_payload(
    window_id: int,
    window_start: float,
    window_end: float,
    current_features: dict,
    current_rule_state: str,
    previous_record: Optional[dict],
    history_summary: list,
    window_sec: int = WINDOW_SEC,
    step_sec: int = STEP_SEC,
) -> dict:
    payload = {
        "source": "realtime_muse",
        "window_id": window_id,
        "time_range_sec": [round(window_start, 2), round(window_end, 2)],
        "window_length_sec": window_sec,
        "step_sec": step_sec,
        "current_features": current_features,
        "current_rule_state": current_rule_state,
        "history_summary": history_summary,
    }

    if previous_record is not None:
        prev_features = previous_record["features"]
        payload["previous_features"] = prev_features
        payload["previous_state"] = {
            "rule_state": previous_record["rule_state"],
            "llm_state": previous_record.get("llm_state"),
        }
        payload["feature_deltas"] = compute_feature_deltas(current_features, prev_features)
    else:
        payload["previous_features"] = None
        payload["previous_state"] = None
        payload["feature_deltas"] = None

    return payload


###############################################################################
# PLOTTING
###############################################################################

def plot_ratio_over_time(result_df: pd.DataFrame, output_file: str = "plot_ratio_over_time.png"):
    plt.figure(figsize=(10, 4))
    plt.plot(result_df["window_center_sec"], result_df["alpha_beta_ratio"], marker="o")
    plt.xlabel("Time (sec)")
    plt.ylabel("Alpha / Beta Ratio")
    plt.title("Alpha/Beta Ratio Over Time")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


def plot_stability_over_time(result_df: pd.DataFrame, output_file: str = "plot_stability_over_time.png"):
    plt.figure(figsize=(10, 4))
    plt.plot(result_df["window_center_sec"], result_df["stability_score"], marker="o")
    plt.xlabel("Time (sec)")
    plt.ylabel("Stability Score")
    plt.title("Stability Over Time")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


def plot_band_means_over_time(result_df: pd.DataFrame, output_file: str = "plot_band_means_over_time.png"):
    plt.figure(figsize=(10, 4))
    plt.plot(result_df["window_center_sec"], result_df["alpha_mean"], marker="o", label="Alpha")
    plt.plot(result_df["window_center_sec"], result_df["beta_mean"], marker="o", label="Beta")
    plt.plot(result_df["window_center_sec"], result_df["theta_mean"], marker="o", label="Theta")
    plt.xlabel("Time (sec)")
    plt.ylabel("Band Mean")
    plt.title("Band Means Over Time")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


def plot_state_timeline(result_df: pd.DataFrame, output_file: str = "plot_state_timeline.png"):
    state_to_num = {
        "distracted_or_unstable": 0,
        "effortful_focus": 1,
        "settling": 2,
        "stable_relaxation": 3,
    }

    y = result_df["rule_state"].map(state_to_num)

    plt.figure(figsize=(10, 4))
    plt.plot(result_df["window_center_sec"], y, marker="o")
    plt.xlabel("Time (sec)")
    plt.ylabel("Rule State")
    plt.title("Rule-Based State Timeline")
    plt.yticks(
        [0, 1, 2, 3],
        ["distracted_or_unstable", "effortful_focus", "settling", "stable_relaxation"]
    )
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


def plot_feature_deltas(result_df: pd.DataFrame, output_file: str = "plot_feature_deltas.png"):
    cols = [
        "alpha_mean_change",
        "beta_mean_change",
        "theta_mean_change",
        "stability_score_change",
    ]
    available_cols = [c for c in cols if c in result_df.columns]

    if not available_cols:
        return

    plt.figure(figsize=(10, 4))
    for col in available_cols:
        plt.plot(result_df["window_center_sec"], result_df[col], marker="o", label=col)

    plt.xlabel("Time (sec)")
    plt.ylabel("Delta vs Previous Window")
    plt.title("Feature Deltas Over Time")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


def make_all_plots(result_df: pd.DataFrame):
    plot_ratio_over_time(result_df)
    plot_stability_over_time(result_df)
    plot_band_means_over_time(result_df)
    plot_state_timeline(result_df)
    plot_feature_deltas(result_df)


###############################################################################
# REALTIME PLOTTER
###############################################################################

class RealtimePlotter:
    def __init__(self):
        plt.ion()
        self.fig, self.axes = plt.subplots(4, 1, figsize=(12, 14))
        self.fig.suptitle("Realtime EEG Monitoring", fontsize=14)

        self.state_to_num = {
            "distracted_or_unstable": 0,
            "effortful_focus": 1,
            "settling": 2,
            "stable_relaxation": 3,
        }

    def update(self, result_df: pd.DataFrame):
        if result_df.empty:
            return

        x = result_df["window_center_sec"]

        ax1, ax2, ax3, ax4 = self.axes
        for ax in self.axes:
            ax.clear()

        ax1.plot(x, result_df["alpha_beta_ratio"], marker="o")
        ax1.set_title("Alpha / Beta Ratio")
        ax1.set_xlabel("Time (sec)")
        ax1.set_ylabel("Ratio")
        ax1.grid(True)

        ax2.plot(x, result_df["stability_score"], marker="o")
        ax2.set_title("Stability Score")
        ax2.set_xlabel("Time (sec)")
        ax2.set_ylabel("Score")
        ax2.grid(True)

        if "alpha_mean" in result_df.columns:
            ax3.plot(x, result_df["alpha_mean"], marker="o", label="Alpha")
        if "beta_mean" in result_df.columns:
            ax3.plot(x, result_df["beta_mean"], marker="o", label="Beta")
        if "theta_mean" in result_df.columns:
            ax3.plot(x, result_df["theta_mean"], marker="o", label="Theta")

        ax3.set_title("Band Means")
        ax3.set_xlabel("Time (sec)")
        ax3.set_ylabel("Mean")
        ax3.grid(True)
        ax3.legend()

        y = result_df["rule_state"].map(self.state_to_num)
        ax4.plot(x, y, marker="o")
        ax4.set_title("Rule-Based State Timeline")
        ax4.set_xlabel("Time (sec)")
        ax4.set_ylabel("State")
        ax4.set_yticks([0, 1, 2, 3])
        ax4.set_yticklabels([
            "distracted_or_unstable",
            "effortful_focus",
            "settling",
            "stable_relaxation",
        ])
        ax4.grid(True)

        self.fig.tight_layout()
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()
        plt.pause(0.01)


plotter = RealtimePlotter() if ENABLE_PLOT else None


###############################################################################
# LLM
###############################################################################

def call_llm(payload: dict) -> dict:
    developer_prompt = """
You are an interpretation agent for meditation-related EEG summaries.

You receive structured EEG-derived features from the current sliding window.
Compare the current window with the previous window and recent history.

Your job:
1. infer a conservative high-level state label,
2. describe the trend relative to the previous window,
3. recommend audio adaptation parameters.

Important rules:
- Do not diagnose medical or psychological conditions.
- Be conservative and only use the provided features.
- Return only valid JSON matching the schema.
"""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "developer", "content": developer_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "eeg_interpretation",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "state_label": {
                            "type": "string",
                            "enum": [
                                "distracted_or_unstable",
                                "effortful_focus",
                                "settling",
                                "stable_relaxation"
                            ]
                        },
                        "confidence": {"type": "number"},
                        "trend": {
                            "type": "string",
                            "enum": ["improving", "stable", "declining", "uncertain"]
                        },
                        "interpretation": {"type": "string"},
                        "audio_action": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "sound_density": {
                                    "type": "string",
                                    "enum": [
                                        "increase",
                                        "slightly_increase",
                                        "keep",
                                        "slightly_reduce",
                                        "reduce"
                                    ]
                                },
                                "spatial_motion": {
                                    "type": "string",
                                    "enum": [
                                        "speed_up",
                                        "slightly_speed_up",
                                        "keep",
                                        "slow_down",
                                        "strongly_slow_down"
                                    ]
                                },
                                "guidance_intensity": {
                                    "type": "string",
                                    "enum": [
                                        "increase",
                                        "slightly_increase",
                                        "keep",
                                        "decrease",
                                        "strongly_decrease"
                                    ]
                                }
                            },
                            "required": [
                                "sound_density",
                                "spatial_motion",
                                "guidance_intensity"
                            ]
                        }
                    },
                    "required": [
                        "state_label",
                        "confidence",
                        "trend",
                        "interpretation",
                        "audio_action"
                    ]
                }
            }
        },
        temperature=0.2,
    )

    content = response.choices[0].message.content
    result = json.loads(content)

    required_keys = [
        "state_label", "confidence", "trend", "interpretation", "audio_action"
    ]
    for key in required_keys:
        if key not in result:
            raise ValueError(f"Missing key in LLM result: {key}")

    return result


def plot_llm_state_timeline(result_df: pd.DataFrame, output_file: str = "plot_llm_state_timeline.png"):
    state_to_num = {
        "distracted_or_unstable": 0,
        "effortful_focus": 1,
        "settling": 2,
        "stable_relaxation": 3,
    }

    y = result_df["llm_state"].map(state_to_num)

    plt.figure(figsize=(10, 4))
    plt.plot(result_df["window_center_sec"], y, marker="o")
    plt.xlabel("Time (sec)")
    plt.ylabel("LLM State")
    plt.title("LLM State Timeline")
    plt.yticks(
        [0, 1, 2, 3],
        ["distracted_or_unstable", "effortful_focus", "settling", "stable_relaxation"]
    )
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


def plot_llm_confidence(result_df: pd.DataFrame, output_file: str = "plot_llm_confidence.png"):
    plt.figure(figsize=(10, 4))
    plt.plot(result_df["window_center_sec"], result_df["llm_confidence"], marker="o")
    plt.xlabel("Time (sec)")
    plt.ylabel("LLM Confidence")
    plt.title("LLM Confidence Over Time")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=200)
    plt.show()


###############################################################################
# REALTIME MAIN LOOP
###############################################################################

def run_realtime_pipeline(
    window_sec: int = WINDOW_SEC,
    step_sec: int = STEP_SEC,
    max_windows: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    osc_server=None,
    enable_plot: bool = ENABLE_PLOT,
    use_llm: bool = USE_LLM,
) -> tuple[pd.DataFrame, list]:
    """
    Realtime version:
    - resets from fresh start
    - collects windows from live OSC data
    - optionally returns after max_windows or when stop_event is set
    """
    global active_window_sec, active_step_sec

    active_window_sec = window_sec
    active_step_sec = step_sec

    state_memory = []
    records = []
    payloads = []
    window_id = 0
    last_processed_time_sec: Optional[float] = None
    own_server = False

    if osc_server is None:
        osc_server = start_osc_server(OSC_IP, OSC_PORT)
        own_server = True

    # 启动保存历史线程
    loop_stop_event = stop_event or threading.Event()
    save_thread = threading.Thread(target=save_history_loop, args=(loop_stop_event,), daemon=True)
    save_thread.start()

    try:
        while True:
            if loop_stop_event.is_set():
                dprint("[LOOP] stop event received")
                break

            sleep_sec = REALTIME_WARMUP_SEC if window_id == 0 else step_sec
            if loop_stop_event.wait(timeout=max(1, sleep_sec)):
                dprint("[LOOP] stop event received during sleep")
                break

            dprint(f"[LOOP] total rows in buffer = {stream_buffer.total_rows()}")

            window_df = stream_buffer.get_recent_df(window_sec)
            dprint(f"[LOOP] recent rows = {len(window_df)}")

            if len(window_df) == 0:
                dprint("No realtime data received yet.")
                continue

            expected_sec = min(window_sec, REALTIME_WARMUP_SEC if window_id == 0 else step_sec)
            if not window_is_filled_enough(window_df, expected_sec=expected_sec):
                dprint("Window not filled enough yet.")
                continue

            if not recent_signal_ok(window_df):
                dprint("Signal quality not good. Skip this step.")
                continue

            latest_sample_time = float(window_df["time_sec"].max())
            if (
                last_processed_time_sec is not None
                and latest_sample_time <= last_processed_time_sec + 1e-9
            ):
                dprint("[LOOP] no new EEG samples since last processed window.")
                continue

            current_features = extract_window_features(window_df)
            current_rule_state = classify_state(current_features)

            previous_record = state_memory[-1] if state_memory else None
            history_summary = build_history_summary(state_memory, n=3)

            window_end = latest_sample_time
            window_start = max(0.0, window_end - window_sec)

            payload = build_llm_payload(
                window_id=window_id,
                window_start=window_start,
                window_end=window_end,
                current_features=current_features,
                current_rule_state=current_rule_state,
                previous_record=previous_record,
                history_summary=history_summary,
                window_sec=window_sec,
                step_sec=step_sec,
            )

            llm_result = None
            if use_llm:
                try:
                    llm_result = call_llm(payload)
                except Exception as e:
                    print(f"LLM call failed on window {window_id}: {e}")
                    llm_result = None
            if llm_result is not None:
                payload["llm_result"] = llm_result
                payload["llm_state"] = llm_result.get("state_label")

            record = {
                "window_id": window_id,
                "start_sec": round(window_start, 2),
                "end_sec": round(window_end, 2),
                "window_center_sec": round((window_start + window_end) / 2, 2),
                "num_samples": int(len(window_df)),
                "rule_state": current_rule_state,
                "features": current_features,
                "llm_state": llm_result["state_label"] if llm_result else None,
                "payload": payload,
            }

            state_memory.append(record)
            payloads.append(payload)
            realtime_payload_history.append(payload)

            with buffer_lock:
                realtime_window_queue.append(payload)

            flat_row = {
                "window_id": window_id,
                "start_sec": round(window_start, 2),
                "end_sec": round(window_end, 2),
                "window_center_sec": round((window_start + window_end) / 2, 2),
                "num_samples": int(len(window_df)),
                "rule_state": current_rule_state,
            }
            flat_row.update(current_features)

            deltas = payload.get("feature_deltas")
            if deltas:
                flat_row.update(deltas)

            if llm_result is not None:
                flat_row["llm_state"] = llm_result["state_label"]
                flat_row["llm_confidence"] = llm_result["confidence"]
                flat_row["llm_trend"] = llm_result["trend"]
                flat_row["llm_interpretation"] = llm_result["interpretation"]
                flat_row["audio_sound_density"] = llm_result["audio_action"]["sound_density"]
                flat_row["audio_spatial_motion"] = llm_result["audio_action"]["spatial_motion"]
                flat_row["audio_guidance_intensity"] = llm_result["audio_action"]["guidance_intensity"]
            else:
                flat_row["llm_state"] = None
                flat_row["llm_confidence"] = None
                flat_row["llm_trend"] = None
                flat_row["llm_interpretation"] = None
                flat_row["audio_sound_density"] = None
                flat_row["audio_spatial_motion"] = None
                flat_row["audio_guidance_intensity"] = None

            records.append(flat_row)

            result_df = pd.DataFrame(records)

            result_df.to_csv(RAW_OUTPUT_CSV if not use_llm else LLM_OUTPUT_CSV, index=False)
            save_payloads_to_json(payloads, RAW_PAYLOAD_JSON)
            save_payloads_jsonl(payloads, RAW_PAYLOAD_JSONL)
            save_offline_compatible_outputs(result_df, payloads)

            if enable_plot and plotter is not None:
                plotter.update(result_df)

            if window_id % PRINT_TABLE_EVERY == 0 and len(records) > 0:
                preview_cols = [
                    "window_id",
                    "window_center_sec",
                    "num_samples",
                    "rule_state",
                    "alpha_beta_ratio",
                    "stability_score",
                ]
                if use_llm:
                    preview_cols += ["llm_state", "llm_confidence", "llm_trend"]

                available_cols = [c for c in preview_cols if c in result_df.columns]

                print("\nPreview:")
                print(result_df[available_cols].tail(TABLE_TAIL_N).to_string(index=False))
                print()

            if max_windows is not None and len(payloads) >= max_windows:
                dprint("[LOOP] reached max_windows")
                break

            last_processed_time_sec = latest_sample_time
            window_id += 1

    except KeyboardInterrupt:
        print("\nRealtime collection stopped by user.")

    loop_stop_event.set()
    save_thread.join(timeout=5.0)

    if osc_server is not None and own_server:
        try:
            osc_server.shutdown()
            osc_server.server_close()
        except Exception:
            pass

    result_df = pd.DataFrame(records)
    return result_df, payloads


###############################################################################
# OSC SERVER
###############################################################################

def start_osc_server(ip: str = OSC_IP, port: int = OSC_PORT):
    dispatcher = Dispatcher()

    dispatcher.map("/muse/elements/delta_absolute", delta_handler)
    dispatcher.map("/muse/elements/theta_absolute", theta_handler)
    dispatcher.map("/muse/elements/alpha_absolute", alpha_handler)
    dispatcher.map("/muse/elements/beta_absolute", beta_handler)
    dispatcher.map("/muse/elements/gamma_absolute", gamma_handler)

    dispatcher.map("/muse/elements/delta", delta_handler)
    dispatcher.map("/muse/elements/theta", theta_handler)
    dispatcher.map("/muse/elements/alpha", alpha_handler)
    dispatcher.map("/muse/elements/beta", beta_handler)
    dispatcher.map("/muse/elements/gamma", gamma_handler)

    dispatcher.map("/muse/acc", acc_handler)
    dispatcher.map("/muse/gyro", gyro_handler)

    dispatcher.set_default_handler(debug_handler)

    server = ThreadingOSCUDPServer((ip, port), dispatcher)
    print(f"Listening on {ip}:{port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def pop_realtime_payload():
    with buffer_lock:
        if realtime_window_queue:
            return realtime_window_queue.popleft()
    return None


def has_realtime_payloads() -> bool:
    with buffer_lock:
        return len(realtime_window_queue) > 0


def clear_realtime_queue():
    with buffer_lock:
        realtime_window_queue.clear()


def flush_raw_osc_events() -> int:
    with buffer_lock:
        events = list(raw_osc_write_queue)
        raw_osc_write_queue.clear()
    if not events:
        return 0
    try:
        os.makedirs("outputs", exist_ok=True)
        with open(RAW_OSC_JSONL, "a", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str))
                f.write("\n")
        return len(events)
    except Exception:
        with buffer_lock:
            raw_osc_write_queue.extendleft(reversed(events))
        raise


def _save_realtime_payload_history() -> None:
    with buffer_lock:
        history = list(realtime_payload_history)
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/realtime_payload_history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def save_history_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(timeout=1.0):
        try:
            _save_realtime_payload_history()
            flush_raw_osc_events()
        except Exception as e:
            print(f"Failed to save realtime history: {e}")
    try:
        _save_realtime_payload_history()
        flush_raw_osc_events()
    except Exception as e:
        print(f"Failed to save final realtime history: {e}")


def get_realtime_payload_history(max_items: int = 50) -> list:
    try:
        with open("outputs/realtime_payload_history.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return data[-max_items:]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_latest_realtime_sample() -> Optional[dict]:
    recent = stream_buffer.get_recent_df(window_sec=2.0)
    if recent.empty:
        return None
    if not recent_signal_ok(recent):
        return None
    try:
        features = extract_window_features(recent)
        state = classify_state(features)
    except Exception:
        return None
    latest_time = float(recent["time_sec"].max()) if "time_sec" in recent.columns else 0.0
    return {
        "time_sec": latest_time,
        "current_features": features,
        "current_rule_state": state,
        "source": "realtime_recent_sample",
    }


def get_realtime_diagnostics() -> dict:
    with buffer_lock:
        rows = len(stream_buffer.rows)
        queue_len = len(realtime_window_queue)
        history_len = len(realtime_payload_history)
        frame_ready = {k: latest_frame.get(k) is not None for k in ["Delta", "Theta", "Alpha", "Beta", "Gamma"]}
        last_age = time.time() - last_osc_at if last_osc_at else None
        return {
            "osc_ip": OSC_IP,
            "osc_port": OSC_PORT,
            "window_sec": active_window_sec,
            "step_sec": active_step_sec,
            "warmup_sec": REALTIME_WARMUP_SEC,
            "buffer_sec": BUFFER_SEC,
            "buffer_rows": rows,
            "pending_window_count": queue_len,
            "history_count": history_len,
            "osc_message_count": osc_message_count,
            "raw_osc_recorded_count": raw_osc_recorded_count,
            "raw_osc_pending_write_count": len(raw_osc_write_queue),
            "committed_rows_count": committed_rows_count,
            "last_osc_address": last_osc_address,
            "last_osc_age_sec": last_age,
            "frame_ready": frame_ready,
            "thread_alive": realtime_thread is not None and realtime_thread.is_alive(),
        }


def get_realtime_raw_rows() -> list[dict]:
    """Return every committed realtime EEG band row from the active session."""
    with buffer_lock:
        return [row.copy() for row in realtime_raw_rows]


def clear_realtime_history():
    with buffer_lock:
        realtime_payload_history.clear()


def start_realtime_session(
    ip: str = OSC_IP,
    port: int = OSC_PORT,
    window_sec: int = WINDOW_SEC,
    step_sec: int = STEP_SEC,
    warmup_sec: int = REALTIME_WARMUP_SEC,
    buffer_sec: int = BUFFER_SEC,
    max_windows: Optional[int] = None,
    enable_plot: bool = False,
    use_llm: bool = False,
):
    global realtime_thread, realtime_server, realtime_stop_event, active_window_sec, active_step_sec, REALTIME_WARMUP_SEC, BUFFER_SEC

    if realtime_thread is not None and realtime_thread.is_alive():
        return realtime_server, realtime_thread

    active_window_sec = window_sec
    active_step_sec = step_sec
    REALTIME_WARMUP_SEC = warmup_sec
    BUFFER_SEC = buffer_sec

    reset_realtime_state()
    clear_output_files()
    clear_realtime_queue()

    realtime_stop_event = threading.Event()
    realtime_server = start_osc_server(ip, port)

    realtime_thread = threading.Thread(
        target=run_realtime_pipeline,
        kwargs={
            "window_sec": window_sec,
            "step_sec": step_sec,
            "max_windows": max_windows,
            "stop_event": realtime_stop_event,
            "osc_server": realtime_server,
            "enable_plot": enable_plot,
            "use_llm": use_llm,
        },
        daemon=True,
    )
    realtime_thread.start()

    return realtime_server, realtime_thread


def stop_realtime_session():
    global realtime_thread, realtime_server, realtime_stop_event
    if realtime_stop_event is not None:
        realtime_stop_event.set()

    if realtime_server is not None:
        try:
            realtime_server.shutdown()
            realtime_server.server_close()
        except Exception:
            pass

    if realtime_thread is not None and realtime_thread.is_alive():
        realtime_thread.join(timeout=1.0)

    realtime_thread = None
    realtime_server = None
    realtime_stop_event = threading.Event()


###############################################################################
# MAIN
###############################################################################

if __name__ == "__main__":
    print("Starting realtime EEG pipeline...")
    print(f"OSC_IP={OSC_IP}, OSC_PORT={OSC_PORT}")
    print(f"WINDOW_SEC={WINDOW_SEC}, STEP_SEC={STEP_SEC}, BUFFER_SEC={BUFFER_SEC}")
    print("Open Mind Monitor OSC streaming now.")
    print("Press Ctrl+C to stop and save final outputs.")

    reset_realtime_state()
    clear_output_files()
    osc_server = start_osc_server(OSC_IP, OSC_PORT)

    result_df, payloads = run_realtime_pipeline(
        window_sec=WINDOW_SEC,
        step_sec=STEP_SEC,
        osc_server=osc_server,
    )

    # Final save with offline-compatible outputs
    if USE_LLM:
        result_df.to_csv(LLM_OUTPUT_CSV, index=False)
    else:
        result_df.to_csv(RAW_OUTPUT_CSV, index=False)

    save_payloads_to_json(payloads, RAW_PAYLOAD_JSON)
    save_payloads_jsonl(payloads, RAW_PAYLOAD_JSONL)
    save_offline_compatible_outputs(result_df, payloads)

    if len(result_df) > 0:
        make_all_plots(result_df)

        if USE_LLM:
            plot_llm_state_timeline(result_df)
            plot_llm_confidence(result_df)

    print("\nSaved files:")
    if USE_LLM:
        print(f"- {LLM_OUTPUT_CSV}")
    else:
        print(f"- {RAW_OUTPUT_CSV}")
    print(f"- {RAW_PAYLOAD_JSON}")
    print(f"- {RAW_PAYLOAD_JSONL}")
    if USE_LLM:
        print("- plot_llm_state_timeline.png")
        print("- plot_llm_confidence.png")

    print("\nPreview:")
    preview_cols = [
        "window_id",
        "window_center_sec",
        "rule_state",
    ]
    if "llm_state" in result_df.columns:
        preview_cols += ["llm_state", "llm_confidence", "llm_trend"]

    available_cols = [c for c in preview_cols if c in result_df.columns]
    if len(result_df) > 0 and available_cols:
        print(result_df[available_cols])
    else:
        print("No valid windows were collected.")
