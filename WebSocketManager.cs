using UnityEngine;
using NativeWebSocket;
using System;
using System.Collections;
using System.Collections.Generic;

public class WebSocketManager : MonoBehaviour
{
    WebSocket websocket;

    [Header("Audio")]
    [Range(0f, 4f)]
    public float masterVolumeMultiplier = 1.0f;

    [Range(0f, 1f)]
    public float spatialBlend = 0.22f;

    [Range(1f, 80f)]
    public float minDistance = 25f;

    [Range(10f, 200f)]
    public float maxDistance = 100f;

    [Range(1f, 8f)]
    public float signalGain = 1.0f;

    [Header("Loudness Normalization")]
    public bool normalizeClipLoudness = true;

    [Range(0.01f, 0.25f)]
    public float targetRms = 0.045f;

    [Range(0.5f, 8f)]
    public float maxAutoGain = 2.0f;

    [Range(0.2f, 1f)]
    public float outputCeiling = 0.52f;

    [Range(0.05f, 10f)]
    public float fadeSeconds = 2.5f;

    [Header("Motion")]
    [Range(0.1f, 5f)]
    public float motionSpeedMultiplier = 1.0f;

    [Range(0.2f, 4f)]
    public float visualMarkerScale = 0.7f;

    [Header("Frontend Sync")]
    [Range(0.05f, 2f)]
    public float telemetryInterval = 0.1f;

    readonly Dictionary<string, GameObject> soundObjects = new Dictionary<string, GameObject>();
    readonly Dictionary<string, MotionData> motionMap = new Dictionary<string, MotionData>();
    readonly Dictionary<string, Vector3> basePositionMap = new Dictionary<string, Vector3>();
    readonly Dictionary<string, float> targetVolumeMap = new Dictionary<string, float>();
    readonly Dictionary<string, Coroutine> repeatCoroutineMap = new Dictionary<string, Coroutine>();

    float lastTelemetryAt = -999f;

    async void Start()
    {
        AudioListener.volume = 1f;
        websocket = new WebSocket("ws://localhost:8765");

        websocket.OnOpen += () => Debug.Log("Connected to Python websocket server");

        websocket.OnMessage += (bytes) =>
        {
            string json = System.Text.Encoding.UTF8.GetString(bytes);
            Debug.Log("Received from Python: " + json);
            ProcessCommand(json);
        };

        websocket.OnError += (e) => Debug.LogError("WebSocket error: " + e);
        websocket.OnClose += (e) => Debug.Log("WebSocket closed: " + e);

        await websocket.Connect();
    }

    void ProcessCommand(string json)
    {
        CommandWrapper wrapper = JsonUtility.FromJson<CommandWrapper>(json);
        if (wrapper == null || wrapper.commands == null)
        {
            Debug.LogWarning("Command JSON parsed empty.");
            return;
        }

        foreach (var cmd in wrapper.commands)
        {
            if (cmd == null || string.IsNullOrEmpty(cmd.id))
            {
                continue;
            }

            if (cmd.action == "create")
            {
                CreateSoundObject(cmd);
            }
            else if (cmd.action == "update")
            {
                UpdateSoundObject(cmd);
            }
            else if (cmd.action == "delete")
            {
                DeleteSoundObject(cmd.id);
            }
        }
    }

    void CreateSoundObject(Command cmd)
    {
        if (soundObjects.ContainsKey(cmd.id))
        {
            UpdateSoundObject(cmd);
            return;
        }

        GameObject obj = new GameObject(cmd.id);

        GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        sphere.name = cmd.id + "_marker";
        sphere.transform.SetParent(obj.transform);
        sphere.transform.localPosition = Vector3.zero;
        sphere.transform.localScale = Vector3.one * visualMarkerScale;

        AudioClip clip = LoadClip(cmd.clip);
        if (clip == null)
        {
            Debug.LogError("Audio not found in Resources: " + cmd.clip);
            Destroy(obj);
            return;
        }

        AudioSource audio = obj.AddComponent<AudioSource>();
        audio.clip = clip;
        ConfigureAudio(audio, cmd);
        audio.volume = 0f;

        AudioSignalBooster booster = obj.AddComponent<AudioSignalBooster>();
        ConfigureBooster(booster);

        Vector3 basePosition = CommandPosition(cmd);
        obj.transform.position = basePosition;

        soundObjects[cmd.id] = obj;
        basePositionMap[cmd.id] = basePosition;
        ApplyMotion(cmd.id, cmd.motion);
        targetVolumeMap[cmd.id] = TargetVolume(cmd.volume);

        if (cmd.loop && clip.length > 1f)
        {
            audio.time = StableOffsetSeconds(cmd.id, clip.length);
        }
        audio.Play();
        StartRepeatIfNeeded(cmd.id, audio, cmd);
        Debug.Log($"Created {cmd.id}: clip={cmd.clip}, volume={audio.volume:F2}, blend={audio.spatialBlend:F2}, base={basePosition}, motion={MotionLabel(cmd.motion)}");
    }

    void UpdateSoundObject(Command cmd)
    {
        if (!soundObjects.TryGetValue(cmd.id, out GameObject obj))
        {
            CreateSoundObject(cmd);
            return;
        }

        AudioSource audio = obj.GetComponent<AudioSource>();
        if (audio != null)
        {
            ConfigureAudio(audio, cmd);
        }

        AudioSignalBooster booster = obj.GetComponent<AudioSignalBooster>();
        if (booster != null)
        {
            ConfigureBooster(booster);
        }

        Vector3 basePosition = CommandPosition(cmd);
        basePositionMap[cmd.id] = basePosition;

        if (cmd.motion == null || cmd.motion.type == "none")
        {
            obj.transform.position = basePosition;
        }

        ApplyMotion(cmd.id, cmd.motion);
        targetVolumeMap[cmd.id] = TargetVolume(cmd.volume);
        if (audio != null)
        {
            StartRepeatIfNeeded(cmd.id, audio, cmd);
        }
        Debug.Log($"Updated {cmd.id}: volume={(audio != null ? audio.volume : 0f):F2}, base={basePosition}, motion={MotionLabel(cmd.motion)}");
    }

    void DeleteSoundObject(string id)
    {
        if (soundObjects.TryGetValue(id, out GameObject obj))
        {
            StartCoroutine(FadeOutAndDestroy(id, obj));
            soundObjects.Remove(id);
        }
        motionMap.Remove(id);
        basePositionMap.Remove(id);
        targetVolumeMap.Remove(id);
        StopRepeat(id);
        Debug.Log("Deleted " + id);
    }

    void ApplyMotion(string id, MotionData motion)
    {
        if (motion != null && !string.IsNullOrEmpty(motion.type) && motion.type != "none")
        {
            motionMap[id] = motion;
        }
        else
        {
            motionMap.Remove(id);
        }
    }

    Vector3 CommandPosition(Command cmd)
    {
        if (cmd.position == null || cmd.position.Length < 3)
        {
            return new Vector3(0f, 0f, 2f);
        }
        return new Vector3(cmd.position[0], cmd.position[1], cmd.position[2]);
    }

    AudioClip LoadClip(string clipPath)
    {
        if (string.IsNullOrEmpty(clipPath))
        {
            return null;
        }

        AudioClip clip = Resources.Load<AudioClip>(clipPath);
        if (clip != null)
        {
            return clip;
        }

        string basename = System.IO.Path.GetFileNameWithoutExtension(clipPath);
        if (!string.IsNullOrEmpty(basename) && basename != clipPath)
        {
            clip = Resources.Load<AudioClip>(basename);
        }
        return clip;
    }

    void ConfigureAudio(AudioSource audio, Command cmd)
    {
        audio.loop = cmd.loop;
        audio.playOnAwake = false;
        audio.spatialBlend = spatialBlend;
        audio.rolloffMode = AudioRolloffMode.Linear;
        audio.minDistance = minDistance;
        audio.maxDistance = maxDistance;
        audio.dopplerLevel = 0f;
        audio.priority = 32;
    }

    float TargetVolume(float commandVolume)
    {
        return Mathf.Clamp01(commandVolume * masterVolumeMultiplier);
    }

    void ConfigureBooster(AudioSignalBooster booster)
    {
        booster.baseGain = signalGain;
        booster.normalize = normalizeClipLoudness;
        booster.targetRms = targetRms;
        booster.maxAutoGain = maxAutoGain;
        booster.outputCeiling = outputCeiling;
    }

    float StableOffsetSeconds(string id, float clipLength)
    {
        int hash = Mathf.Abs(id.GetHashCode());
        return (hash % 1000) / 1000f * Mathf.Max(0f, clipLength - 0.1f);
    }

    IEnumerator FadeOutAndDestroy(string id, GameObject obj)
    {
        AudioSource audio = obj.GetComponent<AudioSource>();
        float startVolume = audio != null ? audio.volume : 0f;
        float t = 0f;
        while (audio != null && t < fadeSeconds)
        {
            t += Time.deltaTime;
            audio.volume = Mathf.Lerp(startVolume, 0f, t / fadeSeconds);
            yield return null;
        }
        Destroy(obj);
    }

    void StartRepeatIfNeeded(string id, AudioSource audio, Command cmd)
    {
        StopRepeat(id);
        if (cmd.loop || cmd.repeat_count <= 1)
        {
            return;
        }

        float interval = cmd.repeat_interval_sec > 0f ? cmd.repeat_interval_sec : Mathf.Max(1f, audio.clip.length + 0.5f);
        repeatCoroutineMap[id] = StartCoroutine(RepeatEventAudio(id, audio, cmd.repeat_count, interval));
    }

    void StopRepeat(string id)
    {
        if (repeatCoroutineMap.TryGetValue(id, out Coroutine coroutine) && coroutine != null)
        {
            StopCoroutine(coroutine);
        }
        repeatCoroutineMap.Remove(id);
    }

    IEnumerator RepeatEventAudio(string id, AudioSource audio, int repeatCount, float interval)
    {
        int played = 1;
        while (audio != null && played < repeatCount)
        {
            yield return new WaitForSeconds(interval);
            if (audio == null || !soundObjects.ContainsKey(id))
            {
                yield break;
            }
            audio.Stop();
            audio.time = 0f;
            audio.Play();
            played++;
            Debug.Log($"Repeated {id}: {played}/{repeatCount}");
        }
        repeatCoroutineMap.Remove(id);
    }

    void Update()
    {
#if !UNITY_WEBGL || UNITY_EDITOR
        if (websocket != null)
        {
            websocket.DispatchMessageQueue();
        }
#endif

        float t = Time.time;

        foreach (var pair in motionMap)
        {
            string id = pair.Key;
            MotionData motion = pair.Value;

            if (!soundObjects.TryGetValue(id, out GameObject obj) || motion == null)
            {
                continue;
            }

            Vector3 center = basePositionMap.ContainsKey(id) ? basePositionMap[id] : Vector3.zero;

            if (motion.type == "circle")
            {
                float phase = Mathf.Abs(id.GetHashCode() % 360) * Mathf.Deg2Rad;
                float speed = Mathf.Max(0.05f, motion.speed) * motionSpeedMultiplier;
                float radius = Mathf.Max(0.2f, motion.radius);
                obj.transform.position = new Vector3(
                    center.x + Mathf.Cos(t * speed + phase) * radius,
                    center.y,
                    center.z + Mathf.Sin(t * speed + phase) * radius
                );
            }
            else if (motion.type == "breathing")
            {
                float speed = Mathf.Max(0.05f, motion.speed) * motionSpeedMultiplier;
                float radius = Mathf.Lerp(
                    motion.minRadius,
                    motion.maxRadius,
                    (Mathf.Sin(t * speed) + 1f) * 0.5f
                );
                obj.transform.position = center + new Vector3(radius, 0f, radius);
            }
            else if (motion.type == "random")
            {
                obj.transform.position += new Vector3(
                    UnityEngine.Random.Range(-0.04f, 0.04f),
                    0f,
                    UnityEngine.Random.Range(-0.04f, 0.04f)
                );
            }
        }

        foreach (var pair in soundObjects)
        {
            string id = pair.Key;
            AudioSource audio = pair.Value.GetComponent<AudioSource>();
            if (audio == null || !targetVolumeMap.ContainsKey(id))
            {
                continue;
            }
            float target = targetVolumeMap[id];
            float step = fadeSeconds <= 0f ? 1f : Time.deltaTime / fadeSeconds;
            audio.volume = Mathf.MoveTowards(audio.volume, target, step);
        }

        if (Time.time - lastTelemetryAt >= telemetryInterval)
        {
            lastTelemetryAt = Time.time;
            SendRuntimeTelemetry();
        }
    }

    async void SendRuntimeTelemetry()
    {
        if (websocket == null || websocket.State != WebSocketState.Open)
        {
            return;
        }

        UnityRuntimeState state = new UnityRuntimeState();
        state.type = "unity_runtime_state";
        state.time = Time.time;
        state.sources = new List<UnityRuntimeSource>();

        foreach (var pair in soundObjects)
        {
            string id = pair.Key;
            GameObject obj = pair.Value;
            if (obj == null)
            {
                continue;
            }

            AudioSource audio = obj.GetComponent<AudioSource>();
            Vector3 p = obj.transform.position;
            MotionData motion = motionMap.ContainsKey(id) ? motionMap[id] : null;

            state.sources.Add(new UnityRuntimeSource
            {
                id = id,
                clip = audio != null && audio.clip != null ? audio.clip.name : "",
                position = new float[] { p.x, p.y, p.z },
                volume = audio != null ? audio.volume : 0f,
                loop = audio != null && audio.loop,
                isPlaying = audio != null && audio.isPlaying,
                motion = motion
            });
        }

        await websocket.SendText(JsonUtility.ToJson(state));
    }

    async void OnApplicationQuit()
    {
        if (websocket != null)
        {
            await websocket.Close();
        }
    }

    string MotionLabel(MotionData motion)
    {
        if (motion == null)
        {
            return "none";
        }
        return $"{motion.type} speed={motion.speed:F2} radius={motion.radius:F2}";
    }
}

public class AudioSignalBooster : MonoBehaviour
{
    public float baseGain = 1f;
    public bool normalize = true;
    public float targetRms = 0.045f;
    public float maxAutoGain = 2.0f;
    public float outputCeiling = 0.52f;

    float smoothedGain = 1f;

    void OnAudioFilterRead(float[] data, int channels)
    {
        float rms = 0f;
        if (normalize)
        {
            for (int i = 0; i < data.Length; i++)
            {
                rms += data[i] * data[i];
            }
            rms = Mathf.Sqrt(rms / Mathf.Max(1, data.Length));
        }

        float desiredGain = baseGain;
        if (normalize && rms > 0.0001f)
        {
            desiredGain *= Mathf.Clamp(targetRms / rms, 0.25f, maxAutoGain);
        }
        smoothedGain = Mathf.Lerp(smoothedGain, desiredGain, 0.08f);

        for (int i = 0; i < data.Length; i++)
        {
            float sample = data[i] * smoothedGain;
            data[i] = Mathf.Clamp(sample, -outputCeiling, outputCeiling);
        }
    }
}

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
    public bool loop;
    public int repeat_count = 1;
    public float repeat_interval_sec = 0f;
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

[Serializable]
public class UnityRuntimeState
{
    public string type;
    public float time;
    public List<UnityRuntimeSource> sources;
}

[Serializable]
public class UnityRuntimeSource
{
    public string id;
    public string clip;
    public float[] position;
    public float volume;
    public bool loop;
    public bool isPlaying;
    public MotionData motion;
}
