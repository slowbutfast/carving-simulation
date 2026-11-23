---
version: "alpha"
name: "Windows XP Luna Progress Overlay (Toolpath Loading Bar)"
description: "Emoji-free, accessible Windows XP Luna segmented progress bar inside .processing-overlay for async toolpath generation."
colors:
  surface: "#ece9d8"
  surface-light: "#ffffff"
  border-highlight: "#ffffff"
  border-shadow: "#918e82"
  on-surface: "#222222"
  progress-fill: "#70c040"
---

## Overview
Replaces `.processing-spinner` inside PR #3's existing `.processing-overlay` / `[hidden]` rules with an authentic **Windows XP Luna segmented green progress bar** (`#70c040` blocks inside an inset `#ffffff` well on `#ece9d8` XP chrome), strictly emoji-free.

## Components
- **`#processing-overlay` / `.processing-progress-box`**:
  - `#progress-label` (`aria-live="polite"`): updated **only** when `phase` changes (`Sculpting`, `Roughing`, `Finishing`, `Resampling`, `Trajectory`, `Gouge check`, `Feed check`, `Encoding`).
  - `#progress-bar` (`role="progressbar"`, `aria-labelledby="progress-label"`, `aria-valuemin="0"`, `aria-valuemax="100"`, `aria-valuenow`): houses `<div class="xp-progress-fill" id="progress-fill">` (`repeating-linear-gradient` `#70c040` 8px blocks, 2px gap).
  - `#progress-pct` and `#progress-elapsed` (`Courier New 11px`).
  - Reuses PR #3's `.processing-overlay` and `.processing-overlay[hidden] { display: none; }` rules in `static/xp.css`.
  - `@media (prefers-reduced-motion: reduce)` sets `.xp-progress-fill { transition: none; }`.
- **Visual States**:
  - **Busy / Active**: `#processing-overlay` visible, `#simulate-button` disabled, `#progress-fill.xp-progress-fill` advancing smoothly.
  - **Phase Transition**: `#progress-label` updates text (triggering `aria-live="polite"` once per phase).
  - **Complete (`done`)**: `#progress-fill` reaches `100%` briefly as `/result` loads, then `#processing-overlay` hides in `finally`.
  - **Error / `429` Stopping**: `#processing-overlay` hides in `finally`; `#status-state` shows `ERROR` (red `.status-badge-collision`) for `422`/`500`/`404`, or `"Previous generation is stopping — try again in a moment"` for `429`.
