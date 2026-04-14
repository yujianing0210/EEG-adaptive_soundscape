import json
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


FILE_PATH = "data\mindMonitor_2026-03-06--17-46-21.csv"
WINDOW_SEC = 120
STEP_SEC = 20


def parse_timestamp(ts: str) -> float:
    """
    Convert Mind Monitor timestamp like '20:27.5' to seconds.
    Example: '20:27.5' -> 1227.5
    """
    minute, second = str(ts).split(":")
    return int(minute) * 60 + float(second)


def load_data(file_path: str) -> pd.DataFrame:
    """
    Load Mind Monitor CSV and create elapsed time column.
    """
    df = pd.read_csv(file_path, low_memory=False)

    if "TimeStamp" not in df.columns:
        raise ValueError("Missing 'TimeStamp' column in CSV.")

    df["time_sec"] = df["TimeStamp"].astype(str).map(parse_timestamp)
    df["time_sec"] = df["time_sec"] - df["time_sec"].iloc[0]

    return df


def filter_good_signal(df: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    """
    Filter rows by headband and HSI quality.

    strict=True: require HSI == 1 for all channels
    strict=False: allow HSI <= 2
    """
    df = df.copy()

    hsi_cols = ["HSI_TP9", "HSI_AF7", "HSI_AF8", "HSI_TP10"]

    if "HeadBandOn" in df.columns:
        df = df[df["HeadBandOn"] == 1]

    for col in hsi_cols:
        if col not in df.columns:
            continue
        if strict:
            df = df[df[col] == 1]
        else:
            df = df[df[col] <= 2]

    return df


def create_band_averages(df: pd.DataFrame) -> pd.DataFrame:
    """
    Average the 4 electrodes for each band.
    Creates columns: Delta, Theta, Alpha, Beta, Gamma
    """
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
    """
    Add motion magnitude columns from accelerometer and gyroscope.
    """
    df = df.copy()

    acc_cols = ["Accelerometer_X", "Accelerometer_Y", "Accelerometer_Z"]
    gyro_cols = ["Gyro_X", "Gyro_Y", "Gyro_Z"]

    if set(acc_cols).issubset(df.columns):
        df["acc_mag"] = np.sqrt(
            df["Accelerometer_X"] ** 2 +
            df["Accelerometer_Y"] ** 2 +
            df["Accelerometer_Z"] ** 2
        )

    if set(gyro_cols).issubset(df.columns):
        df["gyro_mag"] = np.sqrt(
            df["Gyro_X"] ** 2 +
            df["Gyro_Y"] ** 2 +
            df["Gyro_Z"] ** 2
        )

    return df


def extract_window_features(window_df: pd.DataFrame) -> dict:
    """
    Extract summary EEG features for one window.
    """
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

    return feats


def classify_state(features: dict) -> str:
    """
    First-pass rule-based state classification.
    Tune thresholds later based on your own dataset.
    """
    alpha_beta = features["alpha_beta_ratio"]
    theta_beta = features["theta_beta_ratio"]
    stability = features["stability_score"]

    motion_penalty = False
    if "gyro_std" in features and features["gyro_std"] is not None:
        if features["gyro_std"] > 10:
            motion_penalty = True

    if alpha_beta > 1.4 and stability > 0.015 and not motion_penalty:
        return "stable_relaxation"
    elif alpha_beta > 1.15 and not motion_penalty:
        return "settling"
    elif theta_beta < 1.1 and not motion_penalty:
        return "effortful_focus"
    else:
        return "distracted_or_unstable"


def compute_feature_deltas(current_features: dict, previous_features: Optional[dict]) -> Optional[dict]:
    """
    Compute change from previous window.
    """
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
    """
    Compress recent history into a short summary for LLM input.
    """
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
) -> dict:
    """
    Build structured JSON payload for LLM.
    """
    payload = {
        "window_id": window_id,
        "time_range_sec": [round(window_start, 2), round(window_end, 2)],
        "window_length_sec": WINDOW_SEC,
        "step_sec": STEP_SEC,
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


def run_sliding_window_pipeline(
    file_path: str,
    window_sec: int = WINDOW_SEC,
    step_sec: int = STEP_SEC,
    strict_hsi: bool = True,
) -> tuple[pd.DataFrame, list]:
    """
    Main pipeline:
    - load CSV
    - preprocess
    - run 60-second sliding windows
    - update every 10 seconds
    - compare with previous state
    - build LLM payload for each step
    """
    df = load_data(file_path)
    print("Original rows:", len(df))

    df = filter_good_signal(df, strict=strict_hsi)
    print("Rows after signal filter:", len(df))

    if len(df) == 0:
        raise ValueError("No data left after filtering. Try strict_hsi=False.")

    df = create_band_averages(df)
    df = add_motion_features(df)

    max_time = float(df["time_sec"].max())

    state_memory = []
    records = []
    payloads = []

    window_id = 0
    end_time = window_sec

    while end_time <= max_time + 1e-9:
        start_time = end_time - window_sec

        window_df = df[(df["time_sec"] >= start_time) & (df["time_sec"] < end_time)].copy()

        if len(window_df) == 0:
            end_time += step_sec
            continue

        current_features = extract_window_features(window_df)
        current_rule_state = classify_state(current_features)

        previous_record = state_memory[-1] if state_memory else None
        history_summary = build_history_summary(state_memory, n=3)

        payload = build_llm_payload(
            window_id=window_id,
            window_start=start_time,
            window_end=end_time,
            current_features=current_features,
            current_rule_state=current_rule_state,
            previous_record=previous_record,
            history_summary=history_summary,
        )

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
            "start_sec": round(start_time, 2),
            "end_sec": round(end_time, 2),
            "window_center_sec": round((start_time + end_time) / 2, 2),
            "num_samples": int(len(window_df)),
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


def save_payloads_to_json(payloads: list, output_file: str = "llm_payloads.json"):
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payloads, f, indent=2, ensure_ascii=False)


def save_payloads_jsonl(payloads: list, output_file: str = "llm_payloads.jsonl"):
    with open(output_file, "w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


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



################################################################################
### LLM - OpenAI API
################################################################################
import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

LLM_MODEL = "gpt-4o-mini"  # use an affordable and stable model for prototyping first


def call_llm(payload: dict) -> dict:
    """
    Send one EEG payload to the model and get structured JSON back.
    """
    developer_prompt = """
You are an interpretation agent for meditation-related EEG summaries.

You receive structured EEG-derived features from a 60-second sliding window.
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
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False)
            },
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
                        "confidence": {
                            "type": "number"
                        },
                        "trend": {
                            "type": "string",
                            "enum": [
                                "improving",
                                "stable",
                                "declining",
                                "uncertain"
                            ]
                        },
                        "interpretation": {
                            "type": "string"
                        },
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

    # Perform a final local validation to
    # prevent anomalous results from directly corrupting subsequent logic.
    required_keys = [
        "state_label", "confidence", "trend", "interpretation", "audio_action"
    ]
    for key in required_keys:
        if key not in result:
            raise ValueError(f"Missing key in LLM result: {key}")

    return result


def enrich_with_llm(result_df: pd.DataFrame, payloads: list) -> pd.DataFrame:
    """
    Call the LLM for each payload and append results to the dataframe.
    """
    result_df = result_df.copy()

    llm_states = []
    llm_confidences = []
    llm_trends = []
    llm_interpretations = []

    sound_density_list = []
    spatial_motion_list = []
    guidance_intensity_list = []

    for i, payload in enumerate(payloads[:3]):
        print(f"Calling LLM for window {i}...")
        llm_result = call_llm(payload)

        llm_states.append(llm_result["state_label"])
        llm_confidences.append(llm_result["confidence"])
        llm_trends.append(llm_result["trend"])
        llm_interpretations.append(llm_result["interpretation"])

        sound_density_list.append(llm_result["audio_action"]["sound_density"])
        spatial_motion_list.append(llm_result["audio_action"]["spatial_motion"])
        guidance_intensity_list.append(llm_result["audio_action"]["guidance_intensity"])

    result_df["llm_state"] = llm_states
    result_df["llm_confidence"] = llm_confidences
    result_df["llm_trend"] = llm_trends
    result_df["llm_interpretation"] = llm_interpretations
    result_df["audio_sound_density"] = sound_density_list
    result_df["audio_spatial_motion"] = spatial_motion_list
    result_df["audio_guidance_intensity"] = guidance_intensity_list

    return result_df


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




if __name__ == "__main__":
    result_df, payloads = run_sliding_window_pipeline(
        FILE_PATH,
        window_sec=120,
        step_sec=20,
        strict_hsi=True,   # if too few rows remain, change to False
    )

    # First, save the results from the rules layer.
    result_df.to_csv("sliding_window_features.csv", index=False)
    save_payloads_to_json(payloads, "llm_payloads.json")
    save_payloads_jsonl(payloads, "llm_payloads.jsonl")

    # Original Image
    make_all_plots(result_df)

    # Call the LLM and write back the result.
    result_df = enrich_with_llm(result_df, payloads)
    result_df.to_csv("sliding_window_features_with_llm.csv", index=False)

    # New Image
    plot_llm_state_timeline(result_df)
    plot_llm_confidence(result_df)

    print("\nSaved files:")
    print("- sliding_window_features.csv")
    print("- sliding_window_features_with_llm.csv")
    print("- llm_payloads.json")
    print("- llm_payloads.jsonl")
    print("- plot_llm_state_timeline.png")
    print("- plot_llm_confidence.png")

    print("\nPreview:")
    print(result_df[[
        "window_id",
        "window_center_sec",
        "rule_state",
        "llm_state",
        "llm_confidence",
        "llm_trend"
    ]])
