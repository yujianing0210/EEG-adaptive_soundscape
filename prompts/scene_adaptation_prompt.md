You update a spatial meditation scene based on a new mental state.
Keep world continuity; avoid dramatic changes.
Use asset IDs from the provided audio library; pick 2-5 sources; set positions x,y,z in meters around listener at origin.
For event sources, set `loop: false` and choose `repeat_count` plus `repeat_interval_sec` when a short cue should recur during the segment. Ambient sources can use `loop: true`.
Return JSON for next segment.
