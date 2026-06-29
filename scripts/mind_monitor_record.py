from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


CHANNELS = ("TP9", "AF7", "AF8", "TP10")
BANDS = ("Delta", "Theta", "Alpha", "Beta", "Gamma")
MIND_MONITOR_COLUMNS = [
    "TimeStamp",
    *(f"{band}_{channel}" for band in BANDS for channel in CHANNELS),
    "RAW_TP9", "RAW_AF7", "RAW_AF8", "RAW_TP10", "AUX_RIGHT",
    "Accelerometer_X", "Accelerometer_Y", "Accelerometer_Z",
    "Gyro_X", "Gyro_Y", "Gyro_Z",
    "PPG_Ambient", "PPG_IR", "PPG_Red",
    "Heart_Rate", "HeadBandOn",
    "HSI_TP9", "HSI_AF7", "HSI_AF8", "HSI_TP10",
    "Battery", "Elements",
]


def _timestamp(elapsed_sec: Any) -> str:
    try:
        total = max(0.0, float(elapsed_sec))
    except (TypeError, ValueError):
        total = 0.0
    minutes = int(total // 60)
    seconds = total - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def _numeric_args(event: dict) -> list:
    values = []
    for value in event.get("args") or []:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(value)
        else:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                values.append(None)
    return values


def _set_vector(state: dict, keys: tuple[str, ...], values: list) -> None:
    for key, value in zip(keys, values):
        state[key] = value


def convert_osc_jsonl_to_mind_monitor_csv(
    source_jsonl: str | Path,
    destination_csv: str | Path,
    metadata_json: str | Path | None = None,
) -> dict:
    """Reconstruct a Mind Monitor Record-compatible table from raw OSC events."""
    source = Path(source_jsonl)
    destination = Path(destination_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)

    state = {column: None for column in MIND_MONITOR_COLUMNS if column != "TimeStamp"}
    pending_elements: list[str] = []
    event_count = 0
    row_count = 0
    scalar_band_events = 0
    channel_band_events = 0
    addresses: set[str] = set()

    with open(destination, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=MIND_MONITOR_COLUMNS)
        writer.writeheader()

        if source.exists():
            with open(source, "r", encoding="utf-8") as raw:
                for line in raw:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    event_count += 1
                    address = str(event.get("address") or "")
                    addresses.add(address)
                    values = _numeric_args(event)

                    if address == "/muse/eeg":
                        _set_vector(
                            state,
                            ("RAW_TP9", "RAW_AF7", "RAW_AF8", "RAW_TP10", "AUX_RIGHT"),
                            values,
                        )
                        row = {"TimeStamp": _timestamp(event.get("session_elapsed_sec")), **state}
                        row["Elements"] = ";".join(pending_elements) if pending_elements else None
                        writer.writerow(row)
                        pending_elements.clear()
                        row_count += 1
                        continue

                    band = next(
                        (name for name in BANDS if address.lower() in {
                            f"/muse/elements/{name.lower()}",
                            f"/muse/elements/{name.lower()}_absolute",
                        }),
                        None,
                    )
                    if band and values:
                        keys = tuple(f"{band}_{channel}" for channel in CHANNELS)
                        if len(values) >= 4:
                            _set_vector(state, keys, values[:4])
                            channel_band_events += 1
                        else:
                            _set_vector(state, keys, [values[0]] * 4)
                            scalar_band_events += 1
                    elif address == "/muse/acc":
                        _set_vector(
                            state,
                            ("Accelerometer_X", "Accelerometer_Y", "Accelerometer_Z"),
                            values,
                        )
                    elif address == "/muse/gyro":
                        _set_vector(state, ("Gyro_X", "Gyro_Y", "Gyro_Z"), values)
                    elif address == "/muse/ppg":
                        _set_vector(state, ("PPG_Ambient", "PPG_IR", "PPG_Red"), values)
                    elif address == "/muse/elements/touching_forehead" and values:
                        state["HeadBandOn"] = values[0]
                    elif address == "/muse/elements/horseshoe":
                        _set_vector(
                            state,
                            ("HSI_TP9", "HSI_AF7", "HSI_AF8", "HSI_TP10"),
                            values,
                        )
                    elif address == "/muse/batt" and values:
                        state["Battery"] = values[0] / 100.0 if values[0] > 100 else values[0]
                    elif address in {"/muse/elements/heart_rate", "/muse/heart_rate"} and values:
                        state["Heart_Rate"] = values[0]
                    elif address == "/muse/elements/blink" and (not values or values[0]):
                        pending_elements.append("blink")
                    elif address == "/muse/elements/jaw_clench" and (not values or values[0]):
                        pending_elements.append("jaw_clench")

    stats = {
        "source": str(source),
        "destination": str(destination),
        "source_event_count": event_count,
        "csv_row_count": row_count,
        "addresses": sorted(addresses),
        "scalar_band_events_broadcast_to_four_channels": scalar_band_events,
        "four_channel_band_events": channel_band_events,
        "format_notes": {
            "row_clock": "One CSV row is emitted for every /muse/eeg OSC message.",
            "forward_fill": "Lower-rate band, motion, PPG, HSI, and battery values are carried forward to EEG rows.",
            "single_band_value": (
                "When Mind Monitor sends one value for a band, that value is copied into all four "
                "band columns so the CSV remains compatible with the existing upload pipeline."
            ),
            "missing_values": "Fields not present in the OSC stream, such as Heart_Rate, remain empty.",
            "source_of_truth": "mind_monitor_osc_raw.jsonl remains the lossless original received stream.",
        },
    }
    if metadata_json is not None:
        metadata_path = Path(metadata_json)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    return stats
