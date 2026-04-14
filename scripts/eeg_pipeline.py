from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Default config via env
load_dotenv()
DEFAULT_EEG_FILE = os.getenv("EEG_FILE", "data/mindMonitor_2026-03-06--17-46-21.csv")
WINDOW_SEC = int(os.getenv("WINDOW_SEC", 60))
STEP_SEC = int(os.getenv("STEP_SEC", 20))


@dataclass
class EEGWindow:
    window_id: int
    start_sec: float
    end_sec: float
    rule_state: str
    features: dict
    payload: dict


def parse_timestamp(ts: str) -> float:
    minute, second = str(ts).split(":")
    return int(minute) * 60 + float(second)


def load_data(file_path: str) -> pd.DataFrame:
    df = pd.read_csv(file_path, low_memory=False)
    if "TimeStamp" not in df.columns:
        raise ValueError("Missing 'TimeStamp' column in CSV.")
    df["time_sec"] = df["TimeStamp"].astype(str).map(parse_timestamp)
    df["time_sec"] = df["time_sec"] - df["time_sec"].iloc[0]
    return df


def filter_good_signal(df: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    df = df.copy()
    hsi_cols = ["HSI_TP9", "HSI_AF7", "HSI_AF8", "HSI_TP10"]
    if "HeadBandOn" in df.columns:
        df = df[df["HeadBandOn"] == 1]
    for col in hsi_cols:
        if col not in df.columns:
            continue
        df = df[df[col] <= (1 if strict else 2)]
    return df


def create_band_averages(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    bands = ["Delta", "Theta", "Alpha", "Beta", "Gamma"]
    channels = ["TP9", "AF7", "AF8", "TP10"]
    for band in bands:
        cols = [f"{band}_{ch}" for ch in channels if f"{band}_{ch}" in df.columns]
        if not cols:
            raise ValueError(f"No columns found for band {band}")
        df[band] = df[cols].mean(axis=1)
    return df


def add_motion_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    acc_cols = ["Accelerometer_X", "Accelerometer_Y", "Accelerometer_Z"]
    gyro_cols = ["Gyro_X", "Gyro_Y", "Gyro_Z"]
    if set(acc_cols).issubset(df.columns):
        df["acc_mag"] = np.sqrt(df[acc_cols[0]] ** 2 + df[acc_cols[1]] ** 2 + df[acc_cols[2]] ** 2)
    if set(gyro_cols).issubset(df.columns):
        df["gyro_mag"] = np.sqrt(df[gyro_cols[0]] ** 2 + df[gyro_cols[1]] ** 2 + df[gyro_cols[2]] ** 2)
    return df


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
    band_stds = [feats["delta_std"], feats["theta_std"], feats["alpha_std"], feats["beta_std"], feats["gamma_std"]]
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
    return feats


def classify_state(features: dict) -> str:
    alpha_beta = features["alpha_beta_ratio"]
    theta_beta = features["theta_beta_ratio"]
    stability = features["stability_score"]
    motion_penalty = False
    if "gyro_std" in features and features.get("gyro_std") is not None:
        motion_penalty = features["gyro_std"] > 10
    if alpha_beta > 1.4 and stability > 0.015 and not motion_penalty:
        return "stable_relaxation"
    if alpha_beta > 1.15 and not motion_penalty:
        return "settling"
    if theta_beta < 1.1 and not motion_penalty:
        return "effortful_focus"
    return "distracted_or_unstable"


def compute_feature_deltas(current: dict, previous: Optional[dict]) -> Optional[dict]:
    if previous is None:
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
    return {f"{k}_change": current[k] - previous[k] for k in delta_keys if k in current and k in previous}


def build_history(state_memory: List[dict], n: int = 3) -> List[dict]:
    recent = state_memory[-n:]
    return [
        {
            "window_id": item["window_id"],
            "time_range_sec": [item["start_sec"], item["end_sec"]],
            "rule_state": item["rule_state"],
            "llm_state": item.get("llm_state"),
            "alpha_beta_ratio": item["features"]["alpha_beta_ratio"],
            "stability_score": item["features"]["stability_score"],
        }
        for item in recent
    ]


def build_payload(window_id: int, start_time: float, end_time: float, current_features: dict,
                  current_rule_state: str, previous_record: Optional[dict], history_summary: List[dict]) -> dict:
    payload = {
        "window_id": window_id,
        "time_range_sec": [round(start_time, 2), round(end_time, 2)],
        "window_length_sec": WINDOW_SEC,
        "step_sec": STEP_SEC,
        "current_features": current_features,
        "current_rule_state": current_rule_state,
        "history_summary": history_summary,
    }
    if previous_record:
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


def run_pipeline(file_path: str = DEFAULT_EEG_FILE, window_sec: int = WINDOW_SEC, step_sec: int = STEP_SEC,
                 strict_hsi: bool = True) -> Tuple[pd.DataFrame, List[dict]]:
    df = load_data(file_path)
    df = filter_good_signal(df, strict=strict_hsi)
    if len(df) == 0:
        raise ValueError("No data left after filtering; try strict_hsi=False")
    df = create_band_averages(df)
    df = add_motion_features(df)
    max_time = float(df["time_sec"].max())

    state_memory: List[dict] = []
    records = []
    payloads: List[dict] = []

    window_id = 0
    end_time = window_sec
    while end_time <= max_time + 1e-9:
        start_time = end_time - window_sec
        window_df = df[(df["time_sec"] >= start_time) & (df["time_sec"] < end_time)]
        if len(window_df) == 0:
            end_time += step_sec
            continue
        current_features = extract_window_features(window_df)
        current_rule_state = classify_state(current_features)
        previous_record = state_memory[-1] if state_memory else None
        history = build_history(state_memory, n=3)
        payload = build_payload(window_id, start_time, end_time, current_features, current_rule_state, previous_record, history)
        record = {
            "window_id": window_id,
            "start_sec": round(start_time, 2),
            "end_sec": round(end_time, 2),
            "window_center_sec": round((start_time + end_time) / 2, 2),
            "num_samples": int(len(window_df)),
            "rule_state": current_rule_state,
            "features": current_features,
            "llm_state": None,
            "payload": payload,
        }
        state_memory.append(record)
        payloads.append(payload)
        flat_row = {
            "window_id": window_id,
            "start_sec": record["start_sec"],
            "end_sec": record["end_sec"],
            "window_center_sec": record["window_center_sec"],
            "num_samples": record["num_samples"],
            "rule_state": current_rule_state,
        }
        flat_row.update(current_features)
        deltas = payload.get("feature_deltas")
        if deltas:
            flat_row.update(deltas)
        records.append(flat_row)
        window_id += 1
        end_time += step_sec

    result_df = pd.DataFrame(records)
    return result_df, payloads


def save_windows(result_df: pd.DataFrame, payloads: List[dict], outputs_dir: str = "outputs"):
    Path(outputs_dir).mkdir(parents=True, exist_ok=True)
    result_df.to_csv(Path(outputs_dir) / "eeg_windows.csv", index=False)
    with open(Path(outputs_dir) / "eeg_payloads.json", "w", encoding="utf-8") as f:
        json.dump(payloads, f, indent=2)
    with open(Path(outputs_dir) / "eeg_payloads.jsonl", "w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps(payload) + "\n")


def run_and_save(file_path: str = DEFAULT_EEG_FILE, outputs_dir: str = "outputs", strict_hsi: bool = True):
    df, payloads = run_pipeline(file_path=file_path, window_sec=WINDOW_SEC, step_sec=STEP_SEC, strict_hsi=strict_hsi)
    save_windows(df, payloads, outputs_dir=outputs_dir)
    return df, payloads


if __name__ == "__main__":
    df, payloads = run_and_save()
    print(df.head())
    print(f"Saved {len(payloads)} payloads to outputs/")
