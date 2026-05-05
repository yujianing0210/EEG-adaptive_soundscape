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
    public float spatialBlend = 0.88f;

    [Range(1f, 80f)]
    public float minDistance = 1.2f;

    [Range(10f, 200f)]
    public float maxDistance = 18f;

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
    public float motionSpeedMultiplier = 1.35f;

    [Range(0.2f, 4f)]
    public float visualMarkerScale = 0.7f;

    [Header("Frontend Sync")]
    [Range(0.05f, 2f)]
    public float telemetryInterval = 0.1f;

    [Header("Debug / Sync")]
    public bool pruneObjectsNotInSnapshot = true;

    readonly Dictionary<string, GameObject> soundObjects = new Dictionary<string, GameObject>();
    readonly Dictionary<string, MotionData> motionMap = new Dictionary<string, MotionData>();
    readonly Dictionary<string, Vector3> basePositionMap = new Dictionary<string, Vector3>();
    readonly Dictionary<string, Vector3> listenerLocalPositionMap = new Dictionary<string, Vector3>();
    readonly Dictionary<string, string> layerMap = new Dictionary<string, string>();
    readonly Dictionary<string, string> categoryMap = new Dictionary<string, string>();
    readonly Dictionary<string, float> targetVolumeMap = new Dictionary<string, float>();
    readonly Dictionary<string, Coroutine> repeatCoroutineMap = new Dictionary<string, Coroutine>();
    readonly Dictionary<string, string> repeatConfigMap = new Dictionary<string, string>();
    readonly Dictionary<string, float> motionStartTimeMap = new Dictionary<string, float>();
    readonly Dictionary<string, float> motionVolumeFactorMap = new Dictionary<string, float>();

    float lastTelemetryAt = -999f;

    async void Start()
    {
        ApplyImmersiveAudioDefaults();
        AudioListener.volume = 1f;
        websocket = new WebSocket("ws://localhost:8765");

        websocket.OnOpen += () =>
        {
            // New websocket sessions should start from a clean runtime snapshot.
            ClearAllSoundsImmediate();
            Debug.Log("Connected to Python websocket server");
        };

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

    void ApplyImmersiveAudioDefaults()
    {
        if (spatialBlend < 0.6f)
        {
            spatialBlend = 0.88f;
        }
        if (minDistance > 8f)
        {
            minDistance = 1.2f;
        }
        if (maxDistance > 60f)
        {
            maxDistance = 18f;
        }
        if (motionSpeedMultiplier < 1.1f)
        {
            motionSpeedMultiplier = 1.35f;
        }
    }

    void ProcessCommand(string json)
    {
        CommandWrapper wrapper = JsonUtility.FromJson<CommandWrapper>(json);
        if (wrapper == null || wrapper.commands == null)
        {
            Debug.LogWarning("Command JSON parsed empty.");
            return;
        }

        Debug.Log($"Parsed command count: {wrapper.commands.Length}");
        HashSet<string> snapshotIds = new HashSet<string>();

        foreach (var cmd in wrapper.commands)
        {
            if (cmd == null || string.IsNullOrEmpty(cmd.id))
            {
                continue;
            }

            string mtype = (cmd.motion != null && !string.IsNullOrEmpty(cmd.motion.type)) ? cmd.motion.type : "none";
            Debug.Log($"Parsed cmd -> action={cmd.action}, id={cmd.id}, layer={cmd.layer}, category={cmd.category}, loop={cmd.loop}, motion={mtype}");

            if (cmd.action == "create")
            {
                CreateSoundObject(cmd);
                snapshotIds.Add(cmd.id);
            }
            else if (cmd.action == "update")
            {
                UpdateSoundObject(cmd);
                snapshotIds.Add(cmd.id);
            }
            else if (cmd.action == "delete")
            {
                DeleteSoundObject(cmd.id);
            }
        }

        if (pruneObjectsNotInSnapshot && snapshotIds.Count > 0)
        {
            PruneMissingObjects(snapshotIds);
        }
    }

    void PruneMissingObjects(HashSet<string> snapshotIds)
    {
        List<string> toDelete = new List<string>();
        foreach (var key in soundObjects.Keys)
        {
            if (!snapshotIds.Contains(key))
            {
                toDelete.Add(key);
            }
        }

        foreach (var id in toDelete)
        {
            DeleteSoundObject(id);
        }
    }

    void ClearAllSoundsImmediate()
    {
        foreach (var pair in soundObjects)
        {
            if (pair.Value != null)
            {
                Destroy(pair.Value);
            }
        }

        soundObjects.Clear();
        motionMap.Clear();
        basePositionMap.Clear();
        listenerLocalPositionMap.Clear();
        layerMap.Clear();
        categoryMap.Clear();
        targetVolumeMap.Clear();
        motionStartTimeMap.Clear();
        motionVolumeFactorMap.Clear();
        repeatConfigMap.Clear();

        List<string> repeatIds = new List<string>(repeatCoroutineMap.Keys);
        foreach (var id in repeatIds)
        {
            StopRepeat(id);
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
        StoreBasePosition(cmd.id, cmd, basePosition);
        StoreSourceMeta(cmd);
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
        StoreBasePosition(cmd.id, cmd, basePosition);
        StoreSourceMeta(cmd);

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
        listenerLocalPositionMap.Remove(id);
        layerMap.Remove(id);
        categoryMap.Remove(id);
        targetVolumeMap.Remove(id);
        motionStartTimeMap.Remove(id);
        motionVolumeFactorMap.Remove(id);
        repeatConfigMap.Remove(id);
        StopRepeat(id);
        Debug.Log("Deleted " + id);
    }

    void ApplyMotion(string id, MotionData motion)
    {
        if (motion != null && !string.IsNullOrEmpty(motion.type) && motion.type != "none")
        {
            bool shouldResetClock = true;
            if (motionMap.TryGetValue(id, out MotionData existing) && MotionEquivalent(existing, motion))
            {
                shouldResetClock = false;
            }
            motionMap[id] = motion;
            if (shouldResetClock || !motionStartTimeMap.ContainsKey(id))
            {
                motionStartTimeMap[id] = Time.time;
            }
            if (!motionVolumeFactorMap.ContainsKey(id))
            {
                motionVolumeFactorMap[id] = 1f;
            }
        }
        else
        {
            motionMap.Remove(id);
            motionStartTimeMap.Remove(id);
            motionVolumeFactorMap[id] = 1f;
        }
    }

    Vector3 CommandPosition(Command cmd)
    {
        if (cmd.position == null || cmd.position.Length < 3)
        {
            return cmd.relative_to_listener ? MotionPoint(null, Vector3.zero, true) : new Vector3(0f, 0f, 2f);
        }
        Vector3 localOrWorld = new Vector3(cmd.position[0], cmd.position[1], cmd.position[2]);
        return cmd.relative_to_listener ? MotionPoint(cmd.position, Vector3.zero, true) : localOrWorld;
    }

    void StoreBasePosition(string id, Command cmd, Vector3 basePosition)
    {
        if (cmd.relative_to_listener)
        {
            listenerLocalPositionMap[id] = cmd.position != null && cmd.position.Length >= 3
                ? new Vector3(cmd.position[0], cmd.position[1], cmd.position[2])
                : Vector3.zero;
            basePositionMap[id] = basePosition;
            return;
        }
        listenerLocalPositionMap.Remove(id);
        basePositionMap[id] = basePosition;
    }

    void StoreSourceMeta(Command cmd)
    {
        layerMap[cmd.id] = string.IsNullOrEmpty(cmd.layer) ? cmd.category : cmd.layer;
        categoryMap[cmd.id] = string.IsNullOrEmpty(cmd.category) ? cmd.layer : cmd.category;
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
        string cfg = $"{cmd.segment_id}|{cmd.loop}|{cmd.repeat_count}|{cmd.repeat_interval_sec:F3}";
        bool unchanged = repeatConfigMap.TryGetValue(id, out string prevCfg) && prevCfg == cfg;
        repeatConfigMap[id] = cfg;

        if (unchanged)
        {
            return;
        }

        StopRepeat(id);
        if (cmd.loop)
        {
            return;
        }

        audio.Stop();
        audio.time = 0f;
        audio.Play();

        if (cmd.repeat_count <= 1)
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

    Vector3 VecFromArray(float[] arr, Vector3 fallback)
    {
        if (arr == null || arr.Length < 3)
        {
            return fallback;
        }
        return new Vector3(arr[0], arr[1], arr[2]);
    }

    float MotionElapsed(string id)
    {
        if (motionStartTimeMap.TryGetValue(id, out float startTime))
        {
            return Mathf.Max(0f, Time.time - startTime);
        }
        motionStartTimeMap[id] = Time.time;
        return 0f;
    }

    float NormalizedProgress(float elapsed, float duration, bool repeat)
    {
        float d = Mathf.Max(0.01f, duration);
        if (repeat)
        {
            return Mathf.PingPong(elapsed / d, 1f);
        }
        return Mathf.Clamp01(elapsed / d);
    }

    bool FloatNear(float a, float b, float eps = 0.0001f)
    {
        return Mathf.Abs(a - b) <= eps;
    }

    bool VecNear(float[] a, float[] b)
    {
        if (a == null && b == null)
        {
            return true;
        }
        if (a == null || b == null || a.Length < 3 || b.Length < 3)
        {
            return false;
        }
        return FloatNear(a[0], b[0]) && FloatNear(a[1], b[1]) && FloatNear(a[2], b[2]);
    }

    bool MotionEquivalent(MotionData a, MotionData b)
    {
        if (a == null || b == null)
        {
            return false;
        }
        if (!string.Equals(a.type, b.type, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (!FloatNear(a.speed, b.speed) || !FloatNear(a.radius, b.radius) || !FloatNear(a.duration, b.duration))
        {
            return false;
        }
        if (a.repeat != b.repeat)
        {
            return false;
        }
        if (!string.Equals(a.volume_curve ?? "", b.volume_curve ?? "", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (a.pass_count != b.pass_count)
        {
            return false;
        }
        if (!VecNear(a.start, b.start) || !VecNear(a.end, b.end) || !VecNear(a.mid, b.mid) || !VecNear(a.center, b.center))
        {
            return false;
        }
        return true;
    }

    Vector3 EvaluateMotionPosition(string id, MotionData motion, Vector3 center, float timeSec)
    {
        if (motion == null || string.IsNullOrEmpty(motion.type))
        {
            return center;
        }

        float elapsed = MotionElapsed(id);
        float speed = Mathf.Max(0.01f, motion.speed) * motionSpeedMultiplier;
        float radius = Mathf.Max(0.01f, motion.radius);
        float phase = Mathf.Abs(id.GetHashCode() % 360) * Mathf.Deg2Rad;

        if (motion.type == "circle" || motion.type == "orbit")
        {
            Vector3 orbitCenter = MotionPoint(motion.center, center, motion.around_listener || motion.relative_to_listener);
            if (motion.around_listener || motion.relative_to_listener)
            {
                Transform listener = ListenerTransform();
                if (listener != null)
                {
                    float angle = timeSec * speed + phase;
                    return orbitCenter
                        + listener.right * (Mathf.Cos(angle) * radius)
                        + listener.forward * (Mathf.Sin(angle) * radius);
                }
            }
            return new Vector3(
                orbitCenter.x + Mathf.Cos(timeSec * speed + phase) * radius,
                orbitCenter.y,
                orbitCenter.z + Mathf.Sin(timeSec * speed + phase) * radius
            );
        }

        if (motion.type == "breathing")
        {
            float r = Mathf.Lerp(
                motion.minRadius,
                motion.maxRadius,
                (Mathf.Sin(timeSec * speed) + 1f) * 0.5f
            );
            return center + new Vector3(r, 0f, r);
        }

        if (motion.type == "random")
        {
            return center + new Vector3(
                UnityEngine.Random.Range(-0.04f, 0.04f),
                0f,
                UnityEngine.Random.Range(-0.04f, 0.04f)
            );
        }

        if (motion.type == "local_random")
        {
            Vector3 c = MotionPoint(motion.center, center, motion.relative_to_listener);
            float rad = Mathf.Max(0.05f, motion.radius);
            float sx = Mathf.PerlinNoise((id.GetHashCode() & 1023) * 0.01f, timeSec * speed) * 2f - 1f;
            float sz = Mathf.PerlinNoise((id.GetHashCode() & 2047) * 0.01f, timeSec * speed + 13.37f) * 2f - 1f;
            float sy = Mathf.PerlinNoise((id.GetHashCode() & 4095) * 0.01f, timeSec * speed + 7.11f) * 2f - 1f;
            return c + new Vector3(sx * rad, sy * rad * 0.35f, sz * rad);
        }

        if (motion.type == "drift")
        {
            Vector3 start = MotionPoint(motion.start, center, motion.relative_to_listener);
            Vector3 end = MotionPoint(motion.end, center, motion.relative_to_listener);
            float t = NormalizedProgress(elapsed, motion.duration, motion.repeat);
            return Vector3.Lerp(start, end, t);
        }

        if (motion.type == "overhead_pass")
        {
            Vector3 start = MotionPoint(motion.start, center, motion.relative_to_listener);
            Vector3 end = MotionPoint(motion.end, center, motion.relative_to_listener);
            int passCount = Mathf.Max(1, motion.pass_count);
            float duration = Mathf.Max(0.01f, motion.duration);
            float t;
            if (motion.repeat)
            {
                t = Mathf.Repeat(elapsed / duration, 1f);
            }
            else if (passCount <= 1)
            {
                t = Mathf.Clamp01(elapsed / duration);
            }
            else
            {
                float totalDuration = duration * passCount;
                if (elapsed >= totalDuration)
                {
                    t = 1f;
                }
                else
                {
                    float inPass = Mathf.Repeat(elapsed, duration);
                    t = Mathf.Clamp01(inPass / duration);
                }
            }
            return Vector3.Lerp(start, end, t);
        }

        if (motion.type == "approach_recede")
        {
            Vector3 start = MotionPoint(motion.start, center, motion.relative_to_listener);
            Vector3 mid = MotionPoint(motion.mid, center, motion.relative_to_listener);
            Vector3 end = MotionPoint(motion.end, center, motion.relative_to_listener);
            int passCount = Mathf.Max(1, motion.pass_count);
            float duration = Mathf.Max(0.01f, motion.duration);
            float t;
            if (motion.repeat)
            {
                t = Mathf.Repeat(elapsed / duration, 1f);
            }
            else if (passCount <= 1)
            {
                t = Mathf.Clamp01(elapsed / duration);
            }
            else
            {
                float totalDuration = duration * passCount;
                if (elapsed >= totalDuration)
                {
                    t = 1f;
                }
                else
                {
                    float inPass = Mathf.Repeat(elapsed, duration);
                    t = Mathf.Clamp01(inPass / duration);
                }
            }
            if (t < 0.5f)
            {
                return Vector3.Lerp(start, mid, t / 0.5f);
            }
            return Vector3.Lerp(mid, end, (t - 0.5f) / 0.5f);
        }

        return center;
    }

    Vector3 ListenerPosition()
    {
        AudioListener listener = FindObjectOfType<AudioListener>();
        if (listener != null)
        {
            return listener.transform.position;
        }
        if (Camera.main != null)
        {
            return Camera.main.transform.position;
        }
        return Vector3.zero;
    }

    Transform ListenerTransform()
    {
        AudioListener listener = FindObjectOfType<AudioListener>();
        if (listener != null)
        {
            return listener.transform;
        }
        if (Camera.main != null)
        {
            return Camera.main.transform;
        }
        return null;
    }

    Vector3 MotionPoint(float[] arr, Vector3 fallback, bool relativeToListener)
    {
        if (relativeToListener)
        {
            Vector3 local = VecFromArray(arr, Vector3.zero);
            Transform listener = ListenerTransform();
            if (listener != null)
            {
                return listener.position
                    + listener.right * local.x
                    + listener.up * local.y
                    + listener.forward * local.z;
            }
            return ListenerPosition() + local;
        }
        return VecFromArray(arr, fallback);
    }

    float EvaluateMotionVolumeFactor(MotionData motion, string id)
    {
        if (motion == null || string.IsNullOrEmpty(motion.type))
        {
            return 1f;
        }
        if (motion.type != "approach_recede")
        {
            return 1f;
        }
        if (!string.Equals(motion.volume_curve, "fade_in_then_out", StringComparison.OrdinalIgnoreCase))
        {
            return 1f;
        }

        float elapsed = MotionElapsed(id);
        float duration = Mathf.Max(0.01f, motion.duration);
        int passCount = Mathf.Max(1, motion.pass_count);
        float t;
        if (motion.repeat)
        {
            t = Mathf.Repeat(elapsed / duration, 1f);
        }
        else if (passCount <= 1)
        {
            t = Mathf.Clamp01(elapsed / duration);
        }
        else
        {
            float totalDuration = duration * passCount;
            if (elapsed >= totalDuration)
            {
                t = 1f;
            }
            else
            {
                float inPass = Mathf.Repeat(elapsed, duration);
                t = Mathf.Clamp01(inPass / duration);
            }
        }
        if (t < 0.5f)
        {
            return Mathf.Lerp(0.2f, 1f, t / 0.5f);
        }
        return Mathf.Lerp(1f, 0f, (t - 0.5f) / 0.5f);
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
            obj.transform.position = EvaluateMotionPosition(id, motion, center, t);
            motionVolumeFactorMap[id] = EvaluateMotionVolumeFactor(motion, id);
        }

        foreach (var pair in listenerLocalPositionMap)
        {
            string id = pair.Key;
            if (motionMap.ContainsKey(id))
            {
                continue;
            }
            if (!soundObjects.TryGetValue(id, out GameObject obj))
            {
                continue;
            }
            obj.transform.position = MotionPoint(new float[] { pair.Value.x, pair.Value.y, pair.Value.z }, Vector3.zero, true);
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
            if (motionVolumeFactorMap.TryGetValue(id, out float motionFactor))
            {
                target *= Mathf.Clamp01(motionFactor);
            }
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
        Vector3 listenerPosition = ListenerPosition();
        state.listener_position = new float[] { listenerPosition.x, listenerPosition.y, listenerPosition.z };
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
                layer = layerMap.ContainsKey(id) ? layerMap[id] : "",
                category = categoryMap.ContainsKey(id) ? categoryMap[id] : "",
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
    public Command[] commands;
}

[Serializable]
public class Command
{
    public string action;
    public string id;
    public string clip;
    public string layer;
    public string category;
    public string segment_id;
    public float[] position;
    public bool relative_to_listener = false;
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
    public float[] start;
    public float[] end;
    public float[] mid;
    public float[] center;
    public float duration = 8f;
    public bool repeat = false;
    public int pass_count = 1;
    public string volume_curve;
    public bool around_listener = false;
    public bool relative_to_listener = false;
}

[Serializable]
public class UnityRuntimeState
{
    public string type;
    public float time;
    public float[] listener_position;
    public List<UnityRuntimeSource> sources;
}

[Serializable]
public class UnityRuntimeSource
{
    public string id;
    public string clip;
    public string layer;
    public string category;
    public float[] position;
    public float volume;
    public bool loop;
    public bool isPlaying;
    public MotionData motion;
}
