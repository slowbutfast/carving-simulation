---
version: "alpha"
name: "Windows XP Luna Studio (4-DOF Wax Carver)"
description: "Early-2000s Windows XP Luna desktop aesthetic adapted for an emoji-free 4-DOF thermal wax carving CAD/CAM workstation."
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
  collision-bg: "#e81123"
  collision-text: "#ffffff"
  viewport-bg: "#f0ede0"
  wax-stock: "#dfa030"
  cutter-tip: "#333333"
typography:
  title:
    fontFamily: "Tahoma, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    lineHeight: 1.2
  menu:
    fontFamily: "Tahoma, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.2
  body:
    fontFamily: "Tahoma, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.3
  label:
    fontFamily: "Tahoma, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1.2
  code:
    fontFamily: "Courier New, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.2
rounded:
  none: "0px"
  button: "3px"
  window-top: "6px"
spacing:
  xs: "2px"
  sm: "4px"
  md: "8px"
  lg: "12px"
  xl: "16px"
components:
  window:
    backgroundColor: "{colors.surface}"
    borderTopLeftRadius: "{rounded.window-top}"
    borderTopRightRadius: "{rounded.window-top}"
  titlebar:
    backgroundColor: "{colors.titlebar-start}"
    textColor: "{colors.on-titlebar}"
  action-button:
    backgroundColor: "{colors.action-end}"
    textColor: "{colors.on-action}"
    borderRadius: "{rounded.button}"
  transport-dock:
    backgroundColor: "{colors.surface}"
    padding: "{spacing.sm} {spacing.md}"
  status-collision:
    backgroundColor: "{colors.collision-bg}"
    textColor: "{colors.collision-text}"
---

## Overview

Windows XP Luna Retro Minimalist meets 4-DOF Thermal CNC Wax Carving. The UI preserves the crisp tactility of a single native 2000s desktop window floating over a classic Luna blue desktop (`#3a6ea5`), pairing beveled Tahoma controls and inset telemetry cells with an interactive Three.js subtractive carving viewport.

## Colors

- **Desktop (`#3a6ea5`)**: Classic Windows XP desktop backdrop behind the floating studio window.
- **Surface (`#ece9d8`) & Inset (`#f0ede0`, `#ffffff`)**: Warm cream/grey XP chrome contrasting against the `#f0ede0` 3D gallery viewport well.
- **Luna Titlebar (`#0058ee` -> `#3593ff` -> `#072a8c`)**: Horizontal royal-blue gradient with `#ffffff` bold title text.
- **Action Green (`#70c040` -> `#3e8e18`, border `#286010`)**: High-contrast Start-style CTA for `RECALCULATE SURFACE`.
- **Collision Alert (`#e81123` on `#ffffff` text)**: High-urgency red badge for `.status-badge-collision` and close-button hover.
- **3D Materials**: Machinable wax (`#dfa030`) and metallic conical-bevel tip (`#333333`).

## Typography

- **UI Chrome & Labels**: `Tahoma, Segoe UI, sans-serif` at exact pixel sizes (`12px` bold titlebar, `11px` menus, body, and bold field labels).
- **Telemetry & Time**: `Courier New, monospace` (`11px`) for `.transport-time` and `.status-cell` joint/tip coordinate readouts so numeric columns never jitter.

## Layout

- **Desktop (`>= 900px`)**: `.window` (`96vw`, `max-width: 1400px`, `height: 92vh`) with horizontal `.window-body` (`aside.sidebar` + `section.viewport-shell`).
- **Mobile (`< 900px`)**: `.window-body` stacks vertically (`flex-direction: column`) and `.mobile-tabs` (`Sculpt`, `Machine`, `Export`) toggle `data-tab-panel` visibility.
- **Transport Dock**: Anchored inside `.inset-well.viewport-well` (`bottom: 8px; left: 8px; right: 8px; z-index: 10`).

## Elevation & Depth

- **Outset Bevels**: Top/left `#ffffff`, bottom/right `#404040` (with `#918e82` secondary shadow) for `.window`, `.transport-dock`, and `.transport-btn`.
- **Inset Wells**: Top/left `#918e82`, bottom/right `#ffffff` for `.inset-well.viewport-well`, `.xp-input`, and `.status-cell` panes.

## Shapes

- **Window Frame**: `6px` rounded top corners (`borderTopLeftRadius`, `borderTopRightRadius`), `0px` squared bottom corners.
- **Buttons**: `3px` corner radius on primary action buttons; `0px`–`2px` crisp edges on `.transport-btn` and `.status-cell`.

## Components

- **Titlebar & Menu Bar**: `4-DOF Wax Carver Studio 2001`, `Minimize` (`_`), `Maximize` (`□`), `Close` (`×`), and `File(F)`, `View(V)`, `Help(H)` dropdowns.
- **Sidebar Panels**: `Facial Sculpt Deformer (RBF)` sliders, `Wax Stock & Tool Setup` numeric inputs, and `CAM Output` export buttons.
- **Transport Dock (`.transport-dock`)**: Plain-text `Prev`, `Play`/`Pause`, `Next` `.transport-btn`s, `#sim-scrubber`, `#sim-time`, and `#sim-speed` (`1x`, `2x`, `5x`, `10x`).
- **Status Bar (`footer.status-bar`)**: Five inset `.status-cell` panes (`#status-text`, `#status-joints`, `#status-tip`, `#status-feed`, `#status-state`).

## Do's and Don'ts

- **DO** use exact pixel sizing (`11px`, `12px`) for Tahoma typography and `Courier New` for live joint/tip telemetry.
- **DO** keep all styling in vanilla `static/xp.css` with zero external CSS frameworks or Node build steps.
- **DO** use `ResizeObserver` on `#viewport` so `WebGLRenderer` tracks sidebar/window resizes.
- **DON'T** use Unicode emojis anywhere in labels, titlebar icons, buttons, or transport controls (use plain ASCII text or CSS geometric borders instead).
- **DON'T** use rounded modern pills, dark-mode gradients, or borderless flat cards that break the Windows XP Luna aesthetic.
