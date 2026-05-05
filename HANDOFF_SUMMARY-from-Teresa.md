# NeuroScape 项目交接简述

## 1) 本轮对话结论（简短）
- 已把音频调度从“文件名匹配”升级为“读取 `audio_library.json` 元数据驱动”。
- 已打通并修复 Python -> WebSocket -> Unity 的 motion 传输与执行链路。
- 已支持新 motion 类型（`drift / overhead_pass / approach_recede / local_random`）并保留兼容。
- 已增强 event/action 调度：
  - event 不再每窗固定出现；
  - event 去重/冷却，减少连续同一音效；
  - action 现在允许与 event 同时出现（按你的最新要求）。
- 最新偏好已生效：
  - 所有 bird/seagull 事件轨迹统一为 circle/orbit；
  - event 每次出现重复播放 2~4 次；
  - 所有 scene（forest/night_forest/ocean/ocean_beach）使用统一规则。

## 2) 主要改动文件与改动点

### `scripts/scene_logic.py`
- 音频选择改为基于 `audio_library.json` 结构化字段（scene/layer/tags/use_when/avoid_when/...）。
- `choose_sources()`：
  - 场景筛选（forest/ocean_beach 等）；
  - 分层选择（ambient/event/action）；
  - EEG 关联（attention/relaxation/anxiety/mind_wandering_risk/stability）；
  - event 去重与冷却（`played_event_counts/recent_event_ids/last_event_segment`）；
  - action 可与 event 同时出现（最新）。
- `place_sources()`：
  - 默认位置/音量/loop/motion 从 metadata 读取；
  - 保留下游兼容字段（id/asset_id/source_id/asset_ref/position/volume/loop/motion/repeat...）。
- 全场景统一：
  - 增加 scene canonicalization（`ocean_beach/beach/ocean` -> `ocean`）。
- 最新行为：
  - bird/seagull event 强制 `orbit`；
  - event `repeat_count` 默认 2~4（当库内未指定>1）。

### `translator.py`
- 保持命令 schema 兼容；
- motion 标准化与透传增强：
  - 支持 `drift/overhead_pass/approach_recede/local_random`；
  - 透传 `pass_count` 给 Unity（用于单窗内有限次运动）。

### `WebSocketManager.cs`
- 命令解析与调试日志增强（可看到每条 cmd 的 `id/loop/motion`）。
- 修复状态同步问题：
  - 新连接时清理旧对象；
  - 按快照 prune 不在当前命令中的对象，避免“残留对象不动”。
- 运动执行增强：
  - 支持 `drift/overhead_pass/approach_recede/local_random/orbit`；
  - `pass_count` 支持（可做 1~2 次后停止）。
- 重复播放逻辑：
  - 非 loop 事件按 `repeat_count/repeat_interval_sec` 重播，避免每次 update 重启协程。

### `data/audio_library.json`
### `lib_audio/data/audio_library.json`
- 已补充并使用结构化字段（layer/role/recommended_distance/recommended_volume/use_when/avoid_when/spatial_behavior/default_motion/default_position 等）。
- 场景资产已按 forest / ocean_beach / common-action 组织并用于调度。

## 3) 当前系统选择逻辑（给队友）
- 每个窗口按 EEG + 场景状态选源：
  - 1 个 ambient（主背景）；
  - event 按概率与状态触发（并去重）；
  - action 按 grounding 逻辑触发，且可与 event 共存（最新）。
- Unity 仅消费 translator 输出的最终字段，不直接读 metadata。

## 4) 队友接手先做这几步
1. 确认 Unity 工程里实际运行的是最新 `WebSocketManager.cs`（Assets 内脚本需同步）。
2. 启动 Python 侧（`app.py` / `server.py`）后，Unity Console 检查 `Parsed cmd` 日志。
3. 验证：
   - bird/seagull 为 orbit；
   - event `repeat_count` 在 2~4；
   - event + action 可同时出现；
   - forest/ocean 都按统一规则生效。

## 5) 已知注意事项
- 若 Unity 看到对象不动但 JSON 有 motion，优先检查是否在跑旧版 `WebSocketManager.cs`。
- 建议提交前检查 `.env` 中敏感 key，不要入库。

