import asyncio
import websockets
import json
import os
import time

from translator import scene_to_commands

# 📂 她的输出目录（改成你实际路径）
SCENE_FILE = "D:\\Users\\Teres\\OneDrive\\OneDrive - Harvard University\\embodied_arch\\json_to_unity\\outputs\\current_unity_scene.json"

prev_ids = set()


def load_scene():
    if not os.path.exists(SCENE_FILE):
        print("❌ Scene file not found")
        return None

    with open(SCENE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def handler(websocket):
    global prev_ids

    print("✅ Unity connected")

    while True:
        try:
            scene = load_scene()

            if scene is None:
                await asyncio.sleep(1)
                continue

            command_json, prev_ids = scene_to_commands(scene, prev_ids)

            await websocket.send(json.dumps(command_json))

            print("📤 Sent:", command_json)

            await asyncio.sleep(1.0)  # 👈 控制更新频率

        except Exception as e:
            print("❌ Error:", e)
            break


async def main():
    async with websockets.serve(handler, "localhost", 8765):
        print("🚀 Server running on ws://localhost:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())