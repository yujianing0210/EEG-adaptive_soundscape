import asyncio
import websockets
import json

# =========================
# 🔥 模拟 LLM 输出（以后替换）
# =========================
def get_llm_output():
    return {
        "sounds": [
            {
                "id": "bird_1",
                "clip": "bird",
                "position": [2, 0, 0],
                "volume": 0.5,
                "motion": {
                    "type": "circle",
                    "speed": 0.5,
                    "radius": 2.0
                }
            },
            {
                "id": "wind_1",
                "clip": "wind",
                "position": [-2, 1, 0],
                "volume": 0.3
            }
        ]
    }

# =========================
# 🔥 WebSocket Server
# =========================
async def handler(websocket):
    print("✅ Unity connected!")

    created_ids = set()   # 🔥 记录哪些已经创建过

    while True:
        try:
            llm_data = get_llm_output()

            commands = []

            for sound in llm_data["sounds"]:
                sid = sound["id"]

                # 🟢 第一次 → create
                if sid not in created_ids:
                    commands.append({
                        "action": "create",
                        "id": sid,
                        "clip": sound["clip"],
                        "position": sound["position"],
                        "volume": sound["volume"],
                        "motion": sound.get("motion", {})
                    })
                    created_ids.add(sid)

                # 🔵 后续 → update
                else:
                    commands.append({
                        "action": "update",
                        "id": sid,
                        "position": sound["position"],
                        "volume": sound["volume"]
                    })

            # 🔴 删除逻辑（如果LLM不再返回某个sound）
            current_ids = set([s["id"] for s in llm_data["sounds"]])
            for sid in list(created_ids):
                if sid not in current_ids:
                    commands.append({
                        "action": "delete",
                        "id": sid
                    })
                    created_ids.remove(sid)

            # 📤 发给 Unity
            await websocket.send(json.dumps({"commands": commands}))

            print("📤 Sent:", commands)

            await asyncio.sleep(0.5)

        except Exception as e:
            print("❌ Error:", e)
            break

# =========================
# 🔥 启动服务器
# =========================
async def main():
    async with websockets.serve(handler, "localhost", 8765):
        print("🚀 Server running on ws://localhost:8765")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())