---
name: Carving Studio Clean Technical UI (inherited) + CAD Rig Scene Materials
colors:
  primary: "#2563eb"
  secondary: "#e2e8f0"
  background: "#0f172a"
  surface: "#1e293b"
  text:
    primary: "#f8fafc"
    muted: "#94a3b8"
  border: "#334155"
  status:
    success: "#22c55e"
    warning: "#f59e0b"
    error: "#ef4444"
  scene:
    wax: "#e8d595"
    link_static: "#4b5563"
    link_orbit: "#64748b"
    link_z: "#7c8796"
    link_radial: "#94a3b8"
    link_tilt: "#cbd5e1"
    blade_heated: "#f97316"
    unassigned_ghost: "#a78bfa"
typography:
  fontFamily:
    sans: "Inter, system-ui, -apple-system, sans-serif"
    mono: "'JetBrains Mono', ui-monospace, monospace"
  scale:
    h1: "1.125rem, weight 600"
    h2: "0.875rem, weight 600"
    body: "0.8125rem, weight 400"
    caption: "0.75rem, weight 400"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  full: "9999px"
---

## 1. Visual Overview & Philosophy

This change adds no new shell styling. It inherits the chrome tokens of whichever studio shell is on `main` when it lands. That's the `carver-sim-mvp` tokens above, or the `xp-ui-overhaul` `DESIGN.md` (which absorbed `luna-ui-rework`) if that lands first, in which case its chrome tokens replace the `colors`/`typography`/`spacing`/`rounded` blocks here unchanged. What this change does define is the **3D scene materials** for the CAD rig, plus three small UI elements: the machine-detail toggle, the unassigned-parts note, and the geometry provenance readout.

- **Aesthetic Tone**: Precision CAD/CAM. The machine reads as quiet, desaturated metal and plastic so that the warm wax and the hot blade stay the focal points.
- **Target Surfaces**: The existing desktop split-pane viewport and the mobile stacked layout.
- **Visual References**: Fusion 360's default appearance (neutral greys, per-component tint), and the MVP's wax colour `#e8d595`.

---

## 2. Color System & Contrast Rationale

Chrome tokens are inherited and their contrast was audited in `carver-sim-mvp/design.md`. The new scene tokens are WebGL materials, not text, so the comparison that matters is against the viewport `background` (`#0f172a`) and against each other.

| Token Name | Hex Value | Semantic Role | Background Pair | Contrast Ratio | WCAG Compliance |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `scene.wax` | `#e8d595` | Wax stock (static) | `background` | `12.2:1` | **PASS (UI 3:1)** |
| `scene.blade_heated` | `#f97316` | Heated blade region highlight | `background` | `6.4:1` | **PASS (UI 3:1)** |
| `scene.link_tilt` | `#cbd5e1` | Tilt head (holder, cartridge) | `background` | `12.0:1` | **PASS (UI 3:1)** |
| `scene.link_static` | `#4b5563` | Base, pedestal, races | `background` | `2.4:1` | Decorative (non-informational) |
| `scene.unassigned_ghost` | `#a78bfa` @ 35 % opacity | Parts with unknown role | `background` | `6.6:1` (opaque) | **PASS (UI 3:1)** |
| `text.muted` | `#94a3b8` | Provenance readout | `surface` | `5.7:1` | **PASS (AA)** |

Link greys get lighter from `static` to `tilt`, so the moving chain reads from base to tool without any labels.

---

## 3. Typography Hierarchy

Inherited. New text uses existing levels only:

| Level | Font Family | Size | Weight | Line Height | Intended Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Body` | Sans | `13px` | `400` | `1.4` | Machine-detail toggle label, unassigned-parts note |
| `Mono / Data` | Mono | `12px` | `400` | `1.4` | Provenance readout (`STEP a1b2c3d4…`, `home: unset`) |

---

## 4. Component Anatomy & States

### Component: CAD Rig (3D scene)
- **Placement**: Replaces `PrimitiveCarverRig` in the existing viewport scene graph.
- **States**:
  - **Default**: Links use `MeshStandardMaterial` with `metalness 0.3`, `roughness 0.6` and their `scene.link_*` colour. The blade's heated 14 mm uses `scene.blade_heated` with a low emissive (`0.25`). Shaft and body use `link_tilt`.
  - **Playing**: Same materials. Only transforms change.
  - **Collision / Limit Fault**: The offending body (blade, shaft, body, or head) switches to `status.error` for the faulted frame, and the existing transport auto-pause applies.
  - **GLB load failure**: Machine links are hidden. A tool-only rig (blade, shaft, body from `tool_model` constants) and the wax remain, and a `status.warning` toast says "Machine model failed to load — showing tool only".

### Component: Machine-detail toggle
- **Placement**: In the existing viewport/display controls group.
- **States**:
  - **Full** (default): All links visible.
  - **Tool only**: `static`, `orbit` and `z` links hidden, `radial` and `tilt` visible. This is for inspecting the cut.
  - **Hover / Focus / Disabled**: Inherited control styles. Disabled while GLBs are loading.

### Component: Unassigned-parts note
- **Placement**: A single muted line under the viewport toolbar, shown only when `unassigned_parts` is non-empty: "2 CAD parts not simulated: Cold_Tool_6mm_Shank, Dowel_3x37".
- **States**: Default only. Clicking it toggles the ghost visibility of those parts.

### Component: Geometry provenance readout
- **Placement**: Appended to the existing telemetry/status area in `Mono / Data`: `STEP <first 8 of sha256> · home: unset`.
- **States**: Default only.

---

## 5. Responsive Layout & Breakpoints

| Viewport | Breakpoint | Layout Pattern | Navigation / Sizing Rules |
| :--- | :--- | :--- | :--- |
| **Mobile** | `< 900px` | Inherited stacked layout. The machine-detail toggle defaults to **Tool only** to keep the GPU load down. | Toggle touch target ≥ 44px. The provenance readout is truncated to the hash. |
| **Desktop** | `≥ 900px` | Inherited split-pane | Full detail by default |

---

## 6. Interaction, Motion & Sound

- **Transitions**: Inherited `150ms ease-out` on controls. Rig motion is driven only by `THREE.Clock` playback, with no tweening between frames (frames are the truth).
- **Feedback & Alerts**: `BLADE_BROADSIDE_FEED` uses the existing `status.warning` badge path.
- **Audio Affordance**: None.

---

## 7. Do's and Don'ts

- **DO** take scene colours from the `scene.*` tokens via one material factory in `cad_rig.js`.
- **DO** keep the wax visually dominant, with links desaturated.
- **DON'T** render `stock_placeholder` parts (the rectangular CAD wax block). They would contradict the simulated cylinder.
- **DON'T** tint links per CAD part or bring in Fusion appearance colours. One colour per link keeps the kinematic chain readable.
- **DON'T** add emojis to any new label (consistent with `xp-ui-overhaul`).
