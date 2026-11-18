---
version: alpha
name: Windows XP Luna Retro Minimalist (Carver Studio 2001)
description: Early-2000s desktop computing aesthetic (Windows XP Luna) migrated from wax-robot, adapted for 4-DOF thermal wax carving simulation.
colors:
  desktop: "#3a6ea5"
  surface: "#ece9d8"
  surface-light: "#ffffff"
  surface-inset: "#f0ede0"

  border-highlight: "#ffffff"
  border-light: "#ece9d8"
  border-shadow: "#918e82"
  border-dark: "#404040"

  titlebar-start: "#0058ee"
  titlebar-mid: "#3593ff"
  titlebar-end: "#072a8c"
  on-titlebar: "#ffffff"

  on-surface: "#222222"
  on-surface-muted: "#555555"
  on-surface-disabled: "#888888"

  action-start: "#70c040"
  action-end: "#3e8e18"
  action-border: "#286010"
  on-action: "#ffffff"

  close-hover: "#e81123"
  fault-error: "#e81123"
  fault-warning: "#f59e0b"

  viewport-bg: "#f0ede0"
  wax-stock: "#e8d595"
  target-face-ghost: "#3b82f6"
  rig-metal: "#64748b"
  cutter-hot: "#f97316"

typography:
  title:
    fontFamily: Tahoma, "Segoe UI", sans-serif
    fontSize: 12px
    fontWeight: 700
    lineHeight: 1.2
  menu:
    fontFamily: Tahoma, "Segoe UI", sans-serif
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.2
  body:
    fontFamily: Tahoma, "Segoe UI", sans-serif
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.3
  label:
    fontFamily: Tahoma, "Segoe UI", sans-serif
    fontSize: 11px
    fontWeight: 700
    lineHeight: 1.2
  code:
    fontFamily: "Courier New", monospace
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.2

rounded:
  none: 0px
  window-top: 6px
  button: 3px

spacing:
  xs: 2px
  sm: 4px
  md: 8px
  lg: 12px
  xl: 16px
---

# Windows XP Luna Retro Minimalist — Carver Studio 2001

## 1. Visual Overview
Replaces the earlier dark-mode UI draft with `wax-robot`'s tactile **Windows XP Luna** desktop window (`.desktop` `#3a6ea5`, `.window` `#ece9d8`, Luna blue `.titlebar`, 2px beveled `.inset-well`, green XP `#simulate-button`, 3-cell `.status-bar`, and `#f0ede0` gallery 3D viewport).

## 2. Component Anatomy & States
- **Window & Menu Bar**: Minimize (`_`), Maximize (`□`), Close (`✕` with `#e81123` hover); `File(F)`, `Presets(P)`, `Simulation(S)`, `Help(H)`.
- **Sidebar (`320px` desktop; `.mobile-tabs` `< 900px`)**: `Model Source` (preset + upload), `Facial Sculpt` (`nose`, `brow`, `cheeks`, `jaw`, `chin` `.xp-slider`s), `Stock & Preset` (`R_stock`, `H_stock`, `demo`/`standard`, `Show Target Ghost`), and green `⚡ SCULPT & SIMULATE` CTA.
- **Simulation Transport Bar (`.transport-bar` below `#viewport`)**:
  - **Idle / Ready**: `Play` and `Carve to End` enabled, scrubber at `0%`, `#telemetry-readout` at home pose.
  - **Playing**: `Pause` active, `1x–20x` speed, live `(r, theta, h, phi)` and `(r_s, theta_s, z_s, v_tip)` in `Courier New`.
  - **Scrubbing**: Rig updates immediately; Worker restores nearest SDF snapshot asynchronously.
  - **Fault / Warning**: Auto-pauses on `RAPID_COLLISION`, `SHANK_COLLISION`, `SOFT_LIMIT_EXCEEDED`, `STOCK_BOUNDS_EXCEEDED` (`#e81123` badge); highlights `#f59e0b` for `SINGULARITY_HIGH_THETA_DOT` / `UNREACHABLE_UNDERCUT_AREA`.

## 3. Do's and Don'ts
- **DO** keep all styling in vanilla `static/xp.css` with no external CSS frameworks or build tools.
- **DO** render the target face mesh as a toggleable translucent ghost (`#3b82f6`) inside the `#e8d595` wax stock.
- **DON'T** duplicate kinematic trigonometry in `static/app.js` or set `camera.up.set(0, 0, 1)`.
