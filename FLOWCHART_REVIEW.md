# 系统流程图校对与修改建议

## 一句话结论

这张图的总体方向是对的：用户先输入场景意图，系统再结合 EEG 状态更新空间声音体验。但它把当前代码实现画成了“LLM 解释 EEG 后直接生成声音并在 Unity 执行”的线性流程，而实际代码是一个“Flask UI/API -> EEG 窗口特征 -> LLM/规则解释 -> 场景 JSON 更新 -> WebSocket 翻译成 Unity commands -> Unity AudioSource 执行”的循环系统。

## 当前代码里的真实流程

1. 用户在 UI 里输入 prompt，并选择 EEG 数据源：Recorded CSV 或 Muse realtime。
2. 前端调用 `/api/bootstrap`，Flask 在 `app.py` 里执行 `bootstrap_session()`。
3. `scripts/scene_logic.py` 的 `bootstrap_scene()` 先生成初始场景 JSON，并写入 `outputs/initial_scene.json` 和 `outputs/current_unity_scene.json`。
4. 如果是 recorded 模式，`scripts/eeg_pipeline.py` 从 Mind Monitor CSV 读取数据，按窗口提取 Delta/Theta/Alpha/Beta/Gamma 均值、ratio、attention/relaxation/stability 等特征。
5. 如果是 realtime 模式，`muse_realtime.py` 启动 OSC server，接收 Mind Monitor/Muse OSC 数据，累计实时窗口并生成与 recorded 模式相近的 payload。
6. 前端 session timer 每约 30 秒调用 `/api/step`。
7. `app.py` 调用 `interpret_window()`，优先用 OpenAI 模型解释结构化 EEG payload；失败时使用 rule-based fallback。
8. `adapt_scene()` 基于 mental state、上一段 scene、`data/audio_library.json` 的本地音频元数据，更新下一段 Unity-facing scene JSON。
9. `server.py` 读取 `outputs/current_unity_scene.json`，调用 `translator.scene_to_commands()`，通过 WebSocket 发给 Unity。
10. `WebSocketManager.cs` 在 Unity 中执行 create/update/delete，加载 Resources 里的 audio clip，设置 position、volume、loop、repeat 和 motion。

## 图中主要不准确点

| 图中写法 | 为什么不准确 | 建议改法 |
| --- | --- | --- |
| `STEP 0 Scene Generation & Sound Planning & Experience` | 当前代码的 Step 0 更像“Prompt + EEG mode selection + initial scene bootstrap”。真正的 spatial audio experience 在 Unity 端执行，不在 Step 0 完成。 | 改成 `User Prompt + EEG Mode Selection`，后接 `Initial Scene Bootstrap`。 |
| `Muse Headband -> Signal Processing` 是唯一输入 | 当前系统同时支持 recorded CSV 和 realtime Muse OSC。Recorded 模式直接读 `data/mindMonitor_*.csv`；realtime 模式才由 Mind Monitor OSC 输入。 | 在 EEG 输入处画两个分支：`Recorded Mind Monitor CSV` 和 `Realtime Muse / Mind Monitor OSC`。 |
| `Signal Processing -> LLM -> Interpreted Mental States` | LLM 不是接收 raw EEG，也不是只接 Alpha/Beta/Theta/Gamma。代码先提取窗口特征、ratio、deltas、history、rule_state，再把结构化 payload 交给 LLM。 | 在中间加一层 `Window Feature Extraction + Rule State`，再到 `LLM or Rule Fallback Interpretation`。 |
| `Interpreted Mental States: attention -> discrete spatial sound, anxiety -> ambient sound layer, stability` | 当前 mental state 合同更丰富：`state_label/confidence/trend/attention/relaxation/stability/mind_wandering_risk/scene_implication`。`anxiety` 在 adaptation 逻辑中可被使用，但不是 EEG prompt 的必需输出字段。 | 改成 `Mental State + Scene Implication`，列出 `density/eventfulness/motion/guidance/proximity` 等控制变量。 |
| LLM 只出现在 EEG 解释这一处 | 代码里 OpenAI 可能参与三个阶段：初始 scene bootstrap、EEG interpretation、scene adaptation。并且每一步都有 deterministic fallback。 | 把 LLM 画成可选服务，连接到 `Initial Scene Bootstrap`、`Mental State Interpretation`、`Scene Adaptation Planner` 三处。 |
| `Sound Generation: Call ElevenLabs/FreeSound API` | 当前代码没有运行时调用 ElevenLabs 或 Freesound。声音来源是本地 `data/audio_library.json`，并最终映射到 Unity Resources audio clip。 | 改成 `Local Audio Asset Library / Metadata Scheduler`。如果外部 API 是未来计划，标注为 `Future / optional`，不要画进当前实现主流程。 |
| `Sound Source Layer 01/02/03` 过于静态 | 当前调度按 `ambient/event/action` 分层，但选择逻辑会考虑 scene family、density、eventfulness、attention、relaxation、stability、mind_wandering_risk、event cooldown、repeat 等。 | 改成 `Metadata-driven Source Selection: ambient + event + action`。 |
| `DISCRETE (once) - trigger logic?` | 这不是未定义问题。代码里 event/action 已有 repeat、cooldown、motion、loop、event/action coexist 等逻辑，并由 `translator.py` 传给 Unity。 | 改成 `Event: repeat_count + cooldown + finite motion`，`Action: grounding loop/action cue`。 |
| `Unity 3D Execution -> Audio Animator -> Spatial Audio Experience` | Python 侧不会直接驱动 Unity 组件。中间必须经过 `current_unity_scene.json -> server.py WebSocket -> translator commands -> WebSocketManager.cs`。 | 在 Unity 前加 `JSON Output + WebSocket Command Server + Translator`。 |
| 左侧 `Real-time feedback loop` | 当前主要循环是前端 timer 或 button 触发 `/api/step`，不是 Unity 执行结果反馈回来改变 EEG 解释。Unity telemetry 会写 `unity_runtime_state.json`，目前更像 dashboard/runtime 状态，不是主要 adaptation 输入。 | 改成 `Session update loop: every step/window`。如果保留 Unity feedback，标注为 `Unity runtime telemetry for dashboard/debug`。 |
| `STEP 1 Physiological State Interpretation` 在 `STEP 2 Scene Generation` 前 | 初始场景在 EEG 解释前已经生成。之后每个 EEG window 才触发 scene adaptation。 | 分成两条时间线：`Initial bootstrap before EEG` 和 `Per-window adaptation loop`。 |

## 建议改成的流程结构

推荐把图改成四层，而不是左侧 Step 0-3 的单线流程：

1. User/UI layer：prompt、mode selection、session timer、next/end session。
2. EEG layer：recorded CSV 或 Muse OSC，统一变成 EEG window payload。
3. Planning layer：initial scene bootstrap、mental state interpretation、scene adaptation、local audio asset selection。
4. Runtime layer：Unity JSON、WebSocket translator、Unity AudioSource/motion execution、runtime telemetry。

## 可替换的 Mermaid 流程草图

```mermaid
flowchart LR
  U[User prompt + EEG mode selection] --> UI[Flask UI / API]
  UI --> B[Initial scene bootstrap]
  B --> L1{OpenAI available?}
  L1 -->|yes| BS[LLM scene JSON]
  L1 -->|no/fail| BF[Deterministic fallback scene]
  BS --> J[current_unity_scene.json]
  BF --> J

  CSV[Recorded Mind Monitor CSV] --> EP[EEG window feature extraction]
  OSC[Realtime Muse / Mind Monitor OSC] --> RB[Realtime EEG buffer]
  RB --> EP
  EP --> P[Structured EEG payload: bands, ratios, deltas, history, rule_state]

  UI --> STEP[/api/step every session interval]
  STEP --> P
  P --> I[LLM or rule-based mental state interpretation]
  I --> MS[Mental state + scene_implication]
  MS --> A[Scene adaptation planner]
  A --> LIB[Local audio_library.json metadata]
  LIB --> SEL[Source selection: ambient + event + action]
  SEL --> SP[Spatial placement: position, volume, loop, repeat, motion]
  SP --> J

  J --> WS[server.py WebSocket loop]
  WS --> T[translator.scene_to_commands]
  T --> C[Unity commands: create/update/delete]
  C --> UNITY[WebSocketManager.cs AudioSource + motion execution]
  UNITY --> EXP[Spatial audio experience]
  UNITY -. telemetry/debug .-> RT[unity_runtime_state.json / dashboard]
```

## 图面修改建议

- 把 `Step 0` 改成 `Prompt + Initial Scene Bootstrap`，并明确它发生在 EEG adaptation 之前。
- 把 Muse 输入框拆成两个来源：`Recorded CSV` 与 `Realtime OSC`，二者汇入同一个 `EEG Window Payload`。
- 把 `Signal Processing` 改名为 `EEG Feature Extraction`，内容写 `band means, band ratios, motion features, deltas, rule_state, history`。
- 把 `Interpreted Mental States` 改名为 `Mental State + Scene Implication`，避免把 EEG 状态硬编码成“attention/anxiety/stability 三个直接映射”。
- 删除或改弱 `ElevenLabs/Freesound API`，当前实现应写 `Local Audio Asset Library (data/audio_library.json)`。
- 在 Scene/Sound Planning 到 Unity 之间增加 `Unity JSON`、`translator.py`、`server.py WebSocket`。
- 把黄色虚线 feedback loop 改成 `per-window session loop`，不要暗示 Unity runtime 直接反向控制 EEG/LLM。
- `Spatial Arrangement` 里可以去掉 `trigger logic?`，改为已实现字段：`loop, repeat_count, repeat_interval_sec, motion, cooldown, position, volume`。

## 代码依据

- `app.py`：`/api/bootstrap`、`/api/step`、`bootstrap_session()`、`step_scene()` 负责 UI/API 编排，并写 `outputs/current_unity_scene.json`。
- `scripts/eeg_pipeline.py`：recorded CSV 的 EEG windowing、feature extraction、rule_state payload。
- `muse_realtime.py`：realtime OSC 接收、buffer、window payload queue。
- `scripts/scene_logic.py`：OpenAI/fallback scene bootstrap、mental state interpretation、scene adaptation、audio source selection 和 spatial placement。
- `lib/mock_sound_library.py` + `data/audio_library.json`：本地音频资产元数据来源。
- `translator.py`：把 scene JSON 转成 Unity create/update/delete commands。
- `server.py`：每秒读取当前 scene JSON，经 WebSocket 发给 Unity，并接收 Unity runtime telemetry。
- `WebSocketManager.cs`：Unity 侧加载 clip、创建/更新/删除 AudioSource、执行 motion/repeat/loop。
