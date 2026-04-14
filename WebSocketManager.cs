using UnityEngine;
using NativeWebSocket;
using System.Collections.Generic;
using System;

public class WebSocketManager : MonoBehaviour
{
    WebSocket websocket;

    Dictionary<string, GameObject> soundObjects = new Dictionary<string, GameObject>();
    Dictionary<string, MotionData> motions = new Dictionary<string, MotionData>();

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
                if (soundObjects.ContainsKey(cmd.id)) continue;

                GameObject obj = new GameObject(cmd.id);

                // 可视化
                GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                sphere.transform.SetParent(obj.transform);
                sphere.transform.localScale = Vector3.one * 0.3f;

                AudioSource audio = obj.AddComponent<AudioSource>();
                AudioClip clip = Resources.Load<AudioClip>(cmd.clip);

                if (clip == null)
                {
                    Debug.LogError("❌ Audio NOT FOUND: " + cmd.clip);
                    continue;
                }

                audio.clip = clip;
                audio.spatialBlend = 1.0f;
                audio.loop = true;
                audio.volume = cmd.volume;
                audio.Play();

                obj.transform.position = ToVector3(cmd.position);

                soundObjects[cmd.id] = obj;

                if (cmd.motion != null)
                {
                    motions[cmd.id] = cmd.motion;
                }
            }

            // =========================
            // 🔵 UPDATE
            // =========================
            if (cmd.action == "update" && soundObjects.ContainsKey(cmd.id))
            {
                GameObject obj = soundObjects[cmd.id];
                if (obj == null) continue;

                obj.transform.position = ToVector3(cmd.position);

                AudioSource audio = obj.GetComponent<AudioSource>();
                if (audio != null)
                {
                    audio.volume = cmd.volume;
                }
            }

            // =========================
            // 🔴 DELETE
            // =========================
            if (cmd.action == "delete" && soundObjects.ContainsKey(cmd.id))
            {
                Destroy(soundObjects[cmd.id]);
                soundObjects.Remove(cmd.id);

                if (motions.ContainsKey(cmd.id))
                {
                    motions.Remove(cmd.id);
                }
            }
        }
    }

    void Update()
    {
        if (websocket != null)
        {
            websocket.DispatchMessageQueue();
        }

        // =========================
        // 🔥 MOTION SYSTEM
        // =========================
        foreach (var pair in motions)
        {
            string id = pair.Key;
            MotionData m = pair.Value;

            if (!soundObjects.ContainsKey(id)) continue;

            GameObject obj = soundObjects[id];
            if (obj == null) continue;

            float t = Time.time;

            // 🟢 CIRCLE
            if (m.type == "circle")
            {
                float x = Mathf.Cos(t * m.speed) * m.radius;
                float z = Mathf.Sin(t * m.speed) * m.radius;
                obj.transform.position = new Vector3(x, 0, z);
            }

            // 🧘 BREATHING
            else if (m.type == "breathing")
            {
                float r = Mathf.Lerp(m.minRadius, m.maxRadius,
                    (Mathf.Sin(t * m.speed) + 1) / 2);

                obj.transform.position = new Vector3(0, 0, r);
            }

            // 🎲 RANDOM
            else if (m.type == "random")
            {
                obj.transform.position += new Vector3(
                    UnityEngine.Random.Range(-0.02f, 0.02f),
                    0,
                    UnityEngine.Random.Range(-0.02f, 0.02f)
                );
            }

            // 🌀 SPIRAL
            else if (m.type == "spiral")
            {
                float r = m.radius + t * 0.2f;
                float x = Mathf.Cos(t * m.speed) * r;
                float z = Mathf.Sin(t * m.speed) * r;

                obj.transform.position = new Vector3(x, 0, z);
            }

            // 🛤 PATH
            else if (m.type == "path")
            {
                if (m.path != null && m.path.Count > 1)
                {
                    int index = Mathf.FloorToInt(t * m.speed) % m.path.Count;
                    Vector3 target = ToVector3(m.path[index]);

                    obj.transform.position = Vector3.Lerp(
                        obj.transform.position,
                        target,
                        Time.deltaTime * 2f
                    );
                }
            }

            // 🐦 SWARM
            else if (m.type == "swarm")
            {
                Vector3 center = Vector3.zero;

                Vector3 randomOffset = new Vector3(
                    UnityEngine.Random.Range(-0.05f, 0.05f),
                    0,
                    UnityEngine.Random.Range(-0.05f, 0.05f)
                );

                Vector3 toCenter = (center - obj.transform.position) * 0.01f;

                obj.transform.position += randomOffset + toCenter;
            }

            // 🌊 FIELD
            else if (m.type == "field")
            {
                float x = obj.transform.position.x;
                float z = obj.transform.position.z;

                float dx = Mathf.PerlinNoise(x + t * 0.1f, z) - 0.5f;
                float dz = Mathf.PerlinNoise(x, z + t * 0.1f) - 0.5f;

                obj.transform.position += new Vector3(dx, 0, dz) * 0.1f;
            }
        }
    }

    Vector3 ToVector3(float[] arr)
    {
        if (arr == null || arr.Length < 3) return Vector3.zero;
        return new Vector3(arr[0], arr[1], arr[2]);
    }
}

#region DATA STRUCTURES

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

    public List<float[]> path;
}

#endregion