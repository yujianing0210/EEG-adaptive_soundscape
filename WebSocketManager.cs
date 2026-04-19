using UnityEngine;
using NativeWebSocket;
using System.Collections.Generic;
using System;

public class WebSocketManager : MonoBehaviour
{
    WebSocket websocket;

    // 🎯 所有声音对象
    Dictionary<string, GameObject> soundObjects = new Dictionary<string, GameObject>();

    // 🎯 存 motion
    Dictionary<string, MotionData> motionMap = new Dictionary<string, MotionData>();

    async void Start()
    {
        websocket = new WebSocket("ws://localhost:8765");

        websocket.OnOpen += () =>
        {
            Debug.Log("✅ Connected to server");
        };

        websocket.OnMessage += (bytes) =>
        {
            string json = System.Text.Encoding.UTF8.GetString(bytes);
            Debug.Log("📩 Received: " + json);

            ProcessCommand(json);
        };

        websocket.OnError += (e) =>
        {
            Debug.LogError("❌ WebSocket Error: " + e);
        };

        websocket.OnClose += (e) =>
        {
            Debug.Log("🔌 Connection closed");
        };

        await websocket.Connect();
    }

    void ProcessCommand(string json)
    {
        CommandWrapper wrapper = JsonUtility.FromJson<CommandWrapper>(json);

        foreach (var cmd in wrapper.commands)
        {
            // =========================
            // 🟢 CREATE
            // =========================
            if (cmd.action == "create")
            {
                if (soundObjects.ContainsKey(cmd.id))
                    continue;

                GameObject obj = new GameObject(cmd.id);

                // 可视化球
                GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                sphere.transform.SetParent(obj.transform);
                sphere.transform.localPosition = Vector3.zero;
                sphere.transform.localScale = Vector3.one * 0.3f;

                AudioSource audio = obj.AddComponent<AudioSource>();

                AudioClip clip = Resources.Load<AudioClip>(cmd.clip);

                if (clip == null)
                {
                    Debug.LogError("❌ Audio not found: " + cmd.clip);
                    continue;
                }

                audio.clip = clip;
                audio.spatialBlend = 1.0f;
                audio.loop = true;
                audio.volume = cmd.volume;
                audio.Play();

                obj.transform.position = new Vector3(
                    cmd.position[0],
                    cmd.position[1],
                    cmd.position[2]
                );

                soundObjects[cmd.id] = obj;

                // 🔥 存 motion
                if (cmd.motion != null)
                {
                    motionMap[cmd.id] = cmd.motion;
                }
            }

            // =========================
            // 🔵 UPDATE
            // =========================
            if (cmd.action == "update" && soundObjects.ContainsKey(cmd.id))
            {
                GameObject obj = soundObjects[cmd.id];

                // 更新位置（如果没有 motion 就用）
                if (cmd.position != null && (cmd.motion == null || cmd.motion.type == "none"))
                {
                    obj.transform.position = new Vector3(
                        cmd.position[0],
                        cmd.position[1],
                        cmd.position[2]
                    );
                }

                // 更新音量
                AudioSource audio = obj.GetComponent<AudioSource>();
                if (audio != null)
                {
                    audio.volume = cmd.volume;
                }

                // 更新 motion
                if (cmd.motion != null)
                {
                    motionMap[cmd.id] = cmd.motion;
                }
            }

            // =========================
            // 🔴 DELETE
            // =========================
            if (cmd.action == "delete" && soundObjects.ContainsKey(cmd.id))
            {
                Destroy(soundObjects[cmd.id]);
                soundObjects.Remove(cmd.id);

                if (motionMap.ContainsKey(cmd.id))
                {
                    motionMap.Remove(cmd.id);
                }
            }
        }
    }

    // =========================
    // 🎯 MOTION SYSTEM（核心🔥）
    // =========================
    void Update()
    {
        float t = Time.time;

        foreach (var pair in motionMap)
        {
            string id = pair.Key;
            MotionData m = pair.Value;

            if (!soundObjects.ContainsKey(id)) continue;
            if (m == null) continue;

            GameObject obj = soundObjects[id];

            // 🌀 Circle
            if (m.type == "circle")
            {
                float x = Mathf.Cos(t * m.speed) * m.radius;
                float z = Mathf.Sin(t * m.speed) * m.radius;
                obj.transform.position = new Vector3(x, 0, z);
            }

            // 🌊 Breathing（你现在最常用）
            else if (m.type == "breathing")
            {
                float r = Mathf.Lerp(
                    m.minRadius,
                    m.maxRadius,
                    (Mathf.Sin(t * m.speed) + 1) / 2
                );

                obj.transform.position = new Vector3(r, 0, r);
            }

            // 🎲 Random jitter
            else if (m.type == "random")
            {
                obj.transform.position += new Vector3(
                    UnityEngine.Random.Range(-0.02f, 0.02f),
                    0,
                    UnityEngine.Random.Range(-0.02f, 0.02f)
                );
            }

            // ⛔ none（不动）
        }
    }

    void OnApplicationQuit()
    {
        websocket.Close();
    }
}

// =========================
// 📦 JSON STRUCTURES
// =========================

[Serializable]
public class CommandWrapper
{
    public List<Command> commands;
}

[Serializable]
public class Command
{
    public string action;
    public string id;
    public string clip;
    public float[] position;
    public float volume;
    public MotionData motion;
}

[Serializable]
public class MotionData
{
    public string type;

    public float speed = 1f;
    public float radius = 2f;

    public float minRadius = 1f;
    public float maxRadius = 3f;
}