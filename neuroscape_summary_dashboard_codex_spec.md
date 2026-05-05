# Add Post-Meditation Summary Dashboard Page

## Goal

Add a new HTML page that appears automatically after the user finishes a meditation session.

The page should show a **Session Reflection / Summary Dashboard** in the same visual style as the current NEUROSCAPE interface.

The page should summarize:

1. How the user's mental state changed over time.
2. Which audio resources were used at each time period.
3. How audio adaptation may have influenced attention, relaxation, and stability.
4. A short AI-style textual reflection at the end of the session.

---

## Visual Style Requirements

The dashboard must match the current NEUROSCAPE visual style.

Use:

- Dark blurred forest / nature background.
- Centered `NEUROSCAPE` title with wide letter spacing.
- Soft white text.
- Semi-transparent glassmorphism cards.
- Rounded corners.
- Thin translucent borders.
- Soft green / blue / purple accents.
- No left navigation sidebar.
- Full-screen layout.
- Calm meditation atmosphere, not a corporate analytics dashboard.

Suggested CSS style language:

```css
body {
  background: linear-gradient(rgba(5, 20, 10, 0.75), rgba(5, 20, 10, 0.88)),
              url("your-forest-background.jpg");
  background-size: cover;
  background-position: center;
  color: rgba(255,255,255,0.9);
  font-family: Inter, Arial, sans-serif;
}

.glass-card {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(18px);
  border-radius: 22px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
}
```

---

## New Page

Create a new page:

```text
templates/summary.html
```

If the app is not using Flask templates, create:

```text
summary.html
```

The page should be opened automatically after the meditation session ends.

Expected flow:

```text
User Input Page
→ Scene Preview / Enter Page
→ Meditation Session
→ Session End
→ Summary Dashboard Page
```

---

## Auto-Redirect Behavior

When the user clicks the session end button, or when the meditation timer reaches the end, redirect to:

```text
/summary
```

If this is a Flask app, add:

```python
@app.route("/summary")
def summary_page():
    return render_template("summary.html")
```

Wherever the session ends in frontend JavaScript, add:

```javascript
window.location.assign("/summary");
```

Make sure this redirect happens only after the final session data has been saved.

---

# Page Structure

The summary dashboard has 5 main sections:

1. Header
2. Session Overview
3. Mental State Timeline
4. Audio Experience Breakdown
5. Closed-loop System Footer

---

# 1. Header

## Purpose

The header tells the user they are viewing the end-of-session reflection.

## Layout

Top center:

```text
NEUROSCAPE
Your mind. Your soundscape.
```

Below or left-aligned inside the main content:

```text
SESSION REFLECTION
Understand your mental state and the soundscape journey
```

Top-right:

```text
Export Report
```

The export button can be visual only for now.

## HTML Structure

```html
<header class="summary-header">
  <div class="brand-block">
    <div class="brand">NEUROSCAPE</div>
    <div class="tagline">Your mind. Your soundscape.</div>
  </div>

  <div class="page-title-group">
    <h1>SESSION REFLECTION</h1>
    <p>Understand your mental state and the soundscape journey</p>
  </div>

  <button class="export-button">Export Report</button>
</header>
```

## Styling Notes

- `NEUROSCAPE` should use wide letter spacing.
- The page title should be smaller than the brand title.
- The export button should be transparent with a thin white border.

---

# 2. Session Overview

## Purpose

This section gives a quick high-level summary of the meditation session.

## Layout

A wide glass card containing:

- Average Attention
- Relaxation Level
- Stability Score
- AI Summary

Use three circular metric cards on the left and one larger summary card on the right.

## Content

### Metric 1: Average Attention

```text
72 / 100
Average Attention
Moderate
```

Color: soft blue.

### Metric 2: Relaxation Level

```text
78 / 100
Relaxation Level
High
```

Color: soft green.

### Metric 3: Stability Score

```text
65 / 100
Stability Score
Moderate
```

Color: soft purple.

### AI Summary Card

Title:

```text
AI Summary
```

Body:

```text
You gradually transitioned from a distracted state to a more stable and relaxed condition, especially during the latter half of the session.
```

## Data Source

If real data exists, calculate these from EEG window payloads:

```text
average_attention = mean(all window attention values)
average_relaxation = mean(all window relaxation values)
average_stability = mean(all window stability values)
```

If real values are unavailable, use fallback demo values:

```json
{
  "average_attention": 72,
  "average_relaxation": 78,
  "average_stability": 65
}
```

## HTML Structure

```html
<section class="glass-card overview-section">
  <h2>A. Session Overview</h2>

  <div class="overview-grid">
    <div class="metric-card attention">
      <div class="circular-score">72</div>
      <div class="metric-label">Average Attention</div>
      <div class="metric-state">Moderate</div>
    </div>

    <div class="metric-card relaxation">
      <div class="circular-score">78</div>
      <div class="metric-label">Relaxation Level</div>
      <div class="metric-state">High</div>
    </div>

    <div class="metric-card stability">
      <div class="circular-score">65</div>
      <div class="metric-label">Stability Score</div>
      <div class="metric-state">Moderate</div>
    </div>

    <div class="ai-summary-card">
      <h3>AI Summary</h3>
      <p>You gradually transitioned from a distracted state to a more stable and relaxed condition, especially during the latter half of the session.</p>
    </div>
  </div>
</section>
```

---

# 3. Mental State Timeline

## Purpose

This is the main data visualization section.

It should show how attention, relaxation, and stability changed during the session.

It should also mark moments when audio resources changed.

## Layout

A large horizontal glass card.

Inside:

- Title: `B. Mental State Timeline`
- Legend:
  - Attention: blue
  - Relaxation: green
  - Stability: purple
- Main line chart
- Background mental-state zones:
  - Distracted
  - Calm
  - Focused
- Audio event markers below the chart

## Chart Details

X-axis:

```text
Time in minutes
0:00 → session duration
```

Y-axis:

```text
0 → 100
```

Lines:

```text
Attention
Relaxation
Stability
```

Mental-state background zones:

```text
0:00–8:00      Distracted
8:00–16:00     Calm
16:00–24:36    Focused
```

Audio markers:

```text
2:30    Bird sounds introduced
7:00    Ocean waves increased
13:00   Wind ambience added
18:30   Voice guidance triggered
```

## Data Format

```json
[
  {
    "time_sec": 0,
    "attention": 65,
    "relaxation": 30,
    "stability": 38,
    "mental_state": "distracted"
  },
  {
    "time_sec": 300,
    "attention": 70,
    "relaxation": 35,
    "stability": 42,
    "mental_state": "distracted"
  },
  {
    "time_sec": 600,
    "attention": 45,
    "relaxation": 50,
    "stability": 38,
    "mental_state": "calm"
  },
  {
    "time_sec": 900,
    "attention": 55,
    "relaxation": 70,
    "stability": 48,
    "mental_state": "calm"
  },
  {
    "time_sec": 1200,
    "attention": 68,
    "relaxation": 82,
    "stability": 45,
    "mental_state": "focused"
  },
  {
    "time_sec": 1476,
    "attention": 76,
    "relaxation": 90,
    "stability": 58,
    "mental_state": "focused"
  }
]
```

Audio event data:

```json
[
  {
    "time_sec": 150,
    "label": "Bird sounds introduced",
    "type": "event",
    "resource": "bird_calls"
  },
  {
    "time_sec": 420,
    "label": "Ocean waves increased",
    "type": "ambient",
    "resource": "ocean_waves"
  },
  {
    "time_sec": 780,
    "label": "Wind ambience added",
    "type": "ambient",
    "resource": "wind_ambience"
  },
  {
    "time_sec": 1110,
    "label": "Voice guidance triggered",
    "type": "action",
    "resource": "voice_guidance"
  }
]
```

## Implementation Notes

Use one of these:

### Option A: SVG Chart

Recommended. Use SVG paths because it is crisp and easy to style.

### Option B: Canvas Chart

Use a `<canvas>` and draw grid lines, polylines, event markers, and labels.

### Option C: Chart.js

Use this only if Chart.js is already available. Do not add a new dependency unless necessary.

## HTML Structure

```html
<section class="glass-card timeline-section">
  <div class="section-title-row">
    <h2>B. Mental State Timeline</h2>
    <div class="legend">
      <span class="legend-item attention">Attention</span>
      <span class="legend-item relaxation">Relaxation</span>
      <span class="legend-item stability">Stability</span>
    </div>
  </div>

  <div class="timeline-chart" id="mentalTimelineChart">
    <!-- SVG or Canvas chart goes here -->
  </div>

  <div class="audio-event-markers" id="audioEventMarkers">
    <!-- Render event markers here -->
  </div>
</section>
```

---

# 4. Audio Experience Breakdown

## Purpose

This section explains what the user heard during the meditation session.

It should show:

1. Audio timeline
2. Sound composition
3. Top audio elements
4. Insight

## Layout

A wide glass card divided into four areas:

```text
[ Sound Timeline ] [ Sound Composition ] [ Top Audio Elements ] [ Insight ]
```

---

## 4.1 Sound Timeline

## Purpose

Shows which audio layers were active at different times.

Rows:

```text
Ambient
Events
Action
```

Example:

```text
Ambient: Forest Ambience → Ocean Waves → Forest Ambience
Events:  Birds → Wind → Distant Thunder
Action:  Voice Guidance
```

## Data Format

```json
[
  {
    "layer": "ambient",
    "resource": "forest_ambience",
    "label": "Forest Ambience",
    "start_sec": 0,
    "end_sec": 300
  },
  {
    "layer": "ambient",
    "resource": "ocean_waves",
    "label": "Ocean Waves",
    "start_sec": 300,
    "end_sec": 900
  },
  {
    "layer": "ambient",
    "resource": "forest_ambience",
    "label": "Forest Ambience",
    "start_sec": 900,
    "end_sec": 1476
  },
  {
    "layer": "event",
    "resource": "birds",
    "label": "Birds",
    "start_sec": 120,
    "end_sec": 180
  },
  {
    "layer": "event",
    "resource": "wind",
    "label": "Wind",
    "start_sec": 720,
    "end_sec": 780
  },
  {
    "layer": "event",
    "resource": "distant_thunder",
    "label": "Distant Thunder",
    "start_sec": 960,
    "end_sec": 1080
  },
  {
    "layer": "action",
    "resource": "voice_guidance",
    "label": "Voice Guidance",
    "start_sec": 1050,
    "end_sec": 1350
  }
]
```

## UI Details

Use horizontal timeline bars.

Layer colors:

```text
Ambient: soft green
Events: soft orange
Action: soft purple
```

## HTML Structure

```html
<div class="sound-timeline-panel">
  <h3>1. Sound Timeline</h3>

  <div class="sound-row">
    <span class="sound-row-label">Ambient</span>
    <div class="timeline-track" data-layer="ambient"></div>
  </div>

  <div class="sound-row">
    <span class="sound-row-label">Events</span>
    <div class="timeline-track" data-layer="event"></div>
  </div>

  <div class="sound-row">
    <span class="sound-row-label">Action</span>
    <div class="timeline-track" data-layer="action"></div>
  </div>
</div>
```

---

## 4.2 Sound Composition

## Purpose

Shows the percentage of the session occupied by each type of audio.

Example:

```text
Ambient: 60%
Events: 25%
Action: 15%
```

## UI Details

Use a donut chart or circular chart.

If implementing manually, use SVG circles with stroke-dasharray.

Fallback can be a simple legend list.

## HTML Structure

```html
<div class="sound-composition-panel">
  <h3>2. Sound Composition</h3>

  <div class="donut-chart" id="soundCompositionChart">
    <!-- SVG donut chart -->
  </div>

  <ul class="composition-legend">
    <li><span class="dot ambient"></span>Ambient 60%</li>
    <li><span class="dot event"></span>Events 25%</li>
    <li><span class="dot action"></span>Action 15%</li>
  </ul>
</div>
```

---

## 4.3 Top Audio Elements

## Purpose

Ranks the most used audio resources.

Example:

```text
Ocean Waves        40%
Bird Calls         22%
Wind Ambience      18%
Forest Ambience    12%
Distant Thunder     8%
```

## UI Details

Each row should contain:

- small icon or colored dot
- audio label
- progress bar
- percentage

## HTML Structure

```html
<div class="top-audio-panel">
  <h3>3. Top Audio Elements</h3>

  <div id="topAudioElements">
    <!-- Render audio rows here -->
  </div>
</div>
```

---

## 4.4 Insight Card

## Purpose

This is a human-readable interpretation that connects EEG changes to audio changes.

## Text

Use this default text:

```text
Increased relaxation coincided with the introduction of continuous ambient sounds such as ocean waves and forest ambience, which may have helped the user achieve a more stable state.
```

## HTML Structure

```html
<div class="insight-panel">
  <h3>Insight</h3>
  <p id="insightText">
    Increased relaxation coincided with the introduction of continuous ambient sounds such as ocean waves and forest ambience, which may have helped the user achieve a more stable state.
  </p>
</div>
```

---

# 5. Footer: Closed-loop System Summary

## Purpose

Reminds viewers that this is a closed-loop adaptive system.

## Text

At the bottom center:

```text
Closed-loop neuroadaptive system: EEG → Mental State → Audio Adaptation → EEG
```

## HTML Structure

```html
<footer class="system-loop-footer">
  Closed-loop neuroadaptive system:
  <strong>EEG</strong>
  →
  <strong>Mental State</strong>
  →
  <strong>Audio Adaptation</strong>
  →
  <strong>EEG</strong>
</footer>
```

---

# Data Integration

## Preferred Data Sources

Use data from existing session outputs if available.

Likely files:

```text
outputs/current_unity_scene.json
outputs/initial_scene.json
outputs/llm_payloads.json
outputs/llm_payloads.jsonl
outputs/unity_runtime_state.json
```

Potential data sources:

- EEG window payloads
- mental state interpretation results
- scene adaptation outputs
- audio source list from the current Unity scene
- runtime telemetry from Unity

---

# Minimum Data Contract for Summary Page

The summary page should be able to render from this JSON shape:

```json
{
  "session": {
    "date": "May 12, 2025",
    "duration_sec": 1476
  },
  "metrics": {
    "average_attention": 72,
    "average_relaxation": 78,
    "average_stability": 65
  },
  "ai_summary": "You gradually transitioned from a distracted state to a more stable and relaxed condition, especially during the latter half of the session.",
  "mental_timeline": [
    {
      "time_sec": 0,
      "attention": 65,
      "relaxation": 30,
      "stability": 38,
      "mental_state": "distracted"
    }
  ],
  "audio_events": [
    {
      "time_sec": 150,
      "label": "Bird sounds introduced",
      "type": "event",
      "resource": "bird_calls"
    }
  ],
  "audio_timeline": [
    {
      "layer": "ambient",
      "resource": "forest_ambience",
      "label": "Forest Ambience",
      "start_sec": 0,
      "end_sec": 300
    }
  ],
  "audio_composition": {
    "ambient": 60,
    "event": 25,
    "action": 15
  },
  "top_audio_elements": [
    {
      "label": "Ocean Waves",
      "percent": 40,
      "type": "ambient"
    },
    {
      "label": "Bird Calls",
      "percent": 22,
      "type": "event"
    }
  ],
  "insight": "Increased relaxation coincided with the introduction of continuous ambient sounds such as ocean waves and forest ambience, which may have helped the user achieve a more stable state."
}
```

---

# Backend Tasks

## 1. Add Summary Route

If using Flask:

```python
@app.route("/summary")
def summary_page():
    return render_template("summary.html")
```

## 2. Add Summary API Endpoint

```python
@app.route("/api/session_summary")
def session_summary():
    summary = build_session_summary()
    return jsonify(summary)
```

## 3. Build Summary Data

Create a helper function:

```python
def build_session_summary():
    """
    Collect EEG window outputs, scene adaptation history, audio events,
    and runtime state into one JSON object used by the summary dashboard.
    """
```

The function should:

1. Load EEG window payloads.
2. Load mental-state interpretation results.
3. Load audio source changes over time.
4. Calculate average attention, relaxation, stability.
5. Calculate audio composition percentages.
6. Generate fallback insight text if no LLM summary exists.
7. Return the JSON contract above.

## 4. Redirect at End of Session

Wherever the session ends, add:

```javascript
window.location.assign("/summary");
```

This should happen after the final session data has been saved.

---

# Frontend Tasks

## 1. Create Summary HTML

Create:

```text
templates/summary.html
```

or:

```text
summary.html
```

depending on the project structure.

## 2. Create Summary CSS

Either add styles to the existing CSS file or create:

```text
static/summary.css
```

## 3. Create Summary JS

Create:

```text
static/summary.js
```

The JS should:

1. Fetch `/api/session_summary`.
2. Fill metric values.
3. Draw the mental state timeline.
4. Render audio timeline bars.
5. Render audio composition.
6. Render top audio elements.
7. Fill AI summary and insight text.

## 4. Use Demo Fallback Data

If `/api/session_summary` fails, render with demo data so the page never appears empty.

---

# JavaScript Rendering Plan

## On Page Load

```javascript
document.addEventListener("DOMContentLoaded", async () => {
  let data;

  try {
    const res = await fetch("/api/session_summary");
    data = await res.json();
  } catch (err) {
    console.warn("Using demo summary data because API failed:", err);
    data = DEMO_SUMMARY_DATA;
  }

  renderSummary(data);
});
```

## Main Render Function

```javascript
function renderSummary(data) {
  renderHeader(data.session);
  renderMetrics(data.metrics);
  renderAISummary(data.ai_summary);
  renderMentalTimeline(data.mental_timeline, data.audio_events);
  renderAudioTimeline(data.audio_timeline, data.session.duration_sec);
  renderComposition(data.audio_composition);
  renderTopAudioElements(data.top_audio_elements);
  renderInsight(data.insight);
}
```

---

# Acceptance Criteria

The task is complete when:

- A new summary page exists.
- The page visually matches the existing NEUROSCAPE green glassmorphism style.
- There is no left navigation sidebar.
- The page appears after the meditation session ends.
- The dashboard contains:
  - Session Overview
  - Mental State Timeline
  - Audio Experience Breakdown
  - AI Summary
  - Insight
  - Closed-loop footer
- The page can render with real data if available.
- The page falls back to demo data if real data is missing.
- The code does not break the current meditation flow.
