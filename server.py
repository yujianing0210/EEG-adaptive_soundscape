import asyncio
import json
import os
import time
from pathlib import Path

import websockets

from translator import scene_to_commands


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
SCENE_FILE = OUTPUTS / "current_unity_scene.json"
RUNTIME_FILE = OUTPUTS / "unity_runtime_state.json"
WS_HOST = os.getenv("UNITY_WS_HOST", "localhost")
WS_PORT = int(os.getenv("UNITY_WS_PORT", "8765"))

prev_ids = set()


def load_scene():
    if not SCENE_FILE.exists():
        print(f"Scene file not found: {SCENE_FILE}")
        return None

    with open(SCENE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def handler(websocket):
    global prev_ids
    prev_ids = set()

    print("Unity connected")
    receiver_task = asyncio.create_task(receive_unity_telemetry(websocket))

    try:
        while True:
            try:
                scene = load_scene()

                if scene is None:
                    await asyncio.sleep(1)
                    continue

                command_json, prev_ids = scene_to_commands(scene, prev_ids)
                await websocket.send(json.dumps(command_json))
                print("Sent:", command_json)

                await asyncio.sleep(1.0)

            except Exception as exc:
                print("Error:", exc)
                break
    finally:
        receiver_task.cancel()


async def receive_unity_telemetry(websocket):
    while True:
        try:
            message = await websocket.recv()
            data = json.loads(message)
            if data.get("type") != "unity_runtime_state":
                continue

            data["received_at"] = time.time()
            RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(RUNTIME_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print("Telemetry receive error:", exc)
            break


async def main():
    try:
        async with websockets.serve(handler, WS_HOST, WS_PORT):
            print(f"Server running on ws://{WS_HOST}:{WS_PORT}")
            await asyncio.Future()
    except OSError as exc:
        if getattr(exc, "errno", None) == 10048:
            print(f"Port {WS_PORT} is already in use.")
            print("Close the old server.py terminal, or find it with:")
            print(f"  Get-NetTCPConnection -LocalPort {WS_PORT} | Select-Object OwningProcess")
            print("Then stop that PID in Task Manager, or run:")
            print("  Stop-Process -Id <PID>")
            print("If you intentionally want another port, set UNITY_WS_PORT and update Unity's WebSocket URL too.")
            return
        raise


if __name__ == "__main__":
    asyncio.run(main())
