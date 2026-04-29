import os
import torch
import numpy as np
import librosa
import soundfile as sf
from tqdm import tqdm
import laion_clap
import requests
import uuid

# -----------------------------
# CONFIG
# -----------------------------
AUDIO_FOLDER = r"D:\Users\Teres\OneDrive\OneDrive - Harvard University\embodied_arch\json_to_unity\clap_test\audio_mono"
EMBEDDING_FILE = "audio_embeddings.npy"
THRESHOLD = 0.6
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

FREESOUND_API_KEY = "AIC1EHFnEnPuyWTHwQ2aXezlDxJBjxDeLsnn4won"

# -----------------------------
# LOAD MODEL
# -----------------------------
print("Loading CLAP model...")
model = laion_clap.CLAP_Module(enable_fusion=False)
model.load_ckpt()
model.to(DEVICE)

# -----------------------------
# LOAD AUDIO FILES
# -----------------------------
def load_audio_files(folder):
    return [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(".wav")
    ]

audio_files = load_audio_files(AUDIO_FOLDER)
print(f"Loaded {len(audio_files)} audio files")

if len(audio_files) == 0:
    print("❌ No audio found")
    exit()

# -----------------------------
# EMBEDDING
# -----------------------------
def get_audio_embedding(path):
    audio, sr = librosa.load(path, sr=48000, mono=True)
    audio = audio[:48000 * 10]

    audio_tensor = torch.tensor(audio).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        emb = model.get_audio_embedding_from_data(audio_tensor, use_tensor=True)

    return emb.cpu().numpy()[0] if isinstance(emb, torch.Tensor) else emb[0]

# -----------------------------
# LOAD / CACHE
# -----------------------------
if os.path.exists(EMBEDDING_FILE):
    print("⚡ Loading cached embeddings...")
    audio_embeddings = np.load(EMBEDDING_FILE)

    if len(audio_embeddings) != len(audio_files):
        print("⚠️ Library changed → recompute")
        audio_embeddings = None
else:
    audio_embeddings = None

if audio_embeddings is None:
    print("🐢 Computing embeddings...")
    audio_embeddings = np.array([get_audio_embedding(f) for f in tqdm(audio_files)])
    np.save(EMBEDDING_FILE, audio_embeddings)

# -----------------------------
# TEXT EMBEDDING
# -----------------------------
def get_text_embedding(text):
    with torch.no_grad():
        emb = model.get_text_embedding([text])

    return emb.cpu().numpy()[0] if isinstance(emb, torch.Tensor) else emb[0]

# -----------------------------
# SEARCH (CLAP)
# -----------------------------
def search_audio(query, top_k=3):
    text_emb = get_text_embedding(query)

    sims = np.dot(audio_embeddings, text_emb) / (
        np.linalg.norm(audio_embeddings, axis=1) * np.linalg.norm(text_emb)
    )

    idx = np.argsort(sims)[::-1][:top_k]
    idx = [i for i in idx if i < len(audio_files)]

    return [(audio_files[i], float(sims[i])) for i in idx]

# -----------------------------
# FREESOUND SEARCH
# -----------------------------
def search_freesound(query):
    url = "https://freesound.org/apiv2/search/text/"
    headers = {"Authorization": f"Token {FREESOUND_API_KEY}"}

    keywords = [
        w for w in query.lower().split()
        if w not in ["stormy", "very", "strong", "slightly"]
    ] or [query]

    all_results = []

    for word in keywords:
        params = {
            "query": word,
            "fields": "id,name,previews",  # 🔥 必须加这一行！！
            "page_size": 5
        }

        r = requests.get(url, params=params, headers=headers)

        if r.status_code == 200:
            results = r.json().get("results", [])
            print(f"DEBUG '{word}' → {len(results)} raw")

            for s in results:
                previews = s.get("previews")

                if not previews:
                    continue

                # 🔥 自动选可用格式
                if "preview-hq-mp3" in previews:
                    s["download_url"] = previews["preview-hq-mp3"]
                elif "preview-lq-mp3" in previews:
                    s["download_url"] = previews["preview-lq-mp3"]
                elif "preview-hq-ogg" in previews:
                    s["download_url"] = previews["preview-hq-ogg"]
                else:
                    continue

                all_results.append(s)

    return all_results
# -----------------------------
# DOWNLOAD + MONO
# -----------------------------
def download_and_convert(sound):
    url = sound.get("download_url")

    if not url:
        print("⚠️ No valid preview:", sound.get("name"))
        return None

    name = sound["name"].replace(" ", "_")
    wav_name = f"{name}_{uuid.uuid4().hex[:4]}.wav"
    wav_path = os.path.join(AUDIO_FOLDER, wav_name)

    temp_path = wav_path.replace(".wav", ".tmp")

    try:
        data = requests.get(url).content
        with open(temp_path, "wb") as f:
            f.write(data)

        audio, sr = librosa.load(temp_path, sr=48000, mono=True)
        sf.write(wav_path, audio, sr)

        os.remove(temp_path)

        print(f"🎧 Downloaded: {wav_name}")
        return wav_path

    except Exception as e:
        print("❌ Download failed:", e)
        return None
# -----------------------------
# CLAP RERANK
# -----------------------------
def rerank_with_clap(query, paths):
    text_emb = get_text_embedding(query)
    scored = []

    for p in paths:
        emb = get_audio_embedding(p)
        sim = np.dot(emb, text_emb) / (
            np.linalg.norm(emb) * np.linalg.norm(text_emb)
        )
        scored.append((p, sim))

    return sorted(scored, key=lambda x: x[1], reverse=True)

# -----------------------------
# CLASSIFY
# -----------------------------
def classify_sound(query):
    q = query.lower()

    if any(x in q for x in ["wind", "rain", "ocean", "forest", "ambient"]):
        return "ambient"

    if any(x in q for x in ["bird", "click", "drop"]):
        return "event"

    if any(x in q for x in ["footstep", "breathing", "walk"]):
        return "embodied"

    return "ambient"

# -----------------------------
# FALLBACK (FULL PIPELINE)
# -----------------------------
def generate_audio_fallback(query):
    print(f"\n🌐 Freesound search: {query}")

    results = search_freesound(query)

    print("DEBUG: number of results =", len(results))

    if not results:
        print("❌ No Freesound results")
        return None

    paths = []

    for sound in results[:5]:
        try:
            print("Downloading:", sound["name"])
            path = download_and_convert(sound)
            if path:
                paths.append(path)
        except Exception as e:
            print("❌ Download error:", e)

    print("DEBUG: downloaded files =", len(paths))

    if not paths:
        print("❌ No valid downloads")
        return None

    ranked = rerank_with_clap(query, paths)

    print("\n🔎 CLAP rerank:")
    for p, s in ranked:
        print(f"{os.path.basename(p)} | {s:.3f}")

    best_path, _ = ranked[0]

    category = classify_sound(query)

    print(f"\n🎯 Selected: {os.path.basename(best_path)}")
    print(f"📂 Category: {category}")

    return best_path
# -----------------------------
# UPDATE LIBRARY
# -----------------------------
def add_new_audio(path):
    global audio_files, audio_embeddings

    emb = get_audio_embedding(path)

    audio_files.append(path)
    audio_embeddings = np.vstack([audio_embeddings, emb])

    np.save(EMBEDDING_FILE, audio_embeddings)

    print("✅ Library updated")

# -----------------------------
# MAIN LOOP
# -----------------------------
print("\n🎧 Ready!\n")

while True:
    query = input("Enter sound description (or 'exit'): ")

    if query.lower() == "exit":
        break

    results = search_audio(query)

    print("\nTop matches:")
    for p, s in results:
        print(f"{os.path.basename(p)} | {s:.3f}")

    if results[0][1] < THRESHOLD:
        new_audio = generate_audio_fallback(query)

        if new_audio:
            add_new_audio(new_audio)
            print("\n👉 Using Freesound + CLAP audio\n")
    else:
        print("\n✅ Using existing audio\n")

    print("-" * 40)