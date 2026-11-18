---
name: Carving Studio Clean Technical UI
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

Clean dark technical CAD/CAM studio layout prioritizing high contrast for the translucent target face mesh, warm machinable-wax SDF stock (`#e8d595`), metallic primitive gantry links, and glowing rapid/cut toolpath overlays.

- **Aesthetic Tone**: Precision dark-mode CAD/CAM workstation.
- **Target Surfaces**: Desktop browser split-pane (left control sidebar, full-height WebGL viewport, bottom simulation transport bar).

---

## 2. Color System & Contrast Rationale

| Token Name | Hex Value | Semantic Role | Background Pair | Contrast Ratio | WCAG Compliance |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `text.primary` | `#f8fafc` | Labels, readouts, headers | `surface` (`#1e293b`) | `14.2:1` | **PASS (AAA)** |
| `text.muted` | `#94a3b8` | Units, captions | `surface` (`#1e293b`) | `5.9:1` | **PASS (AA)** |
| `primary` | `#2563eb` | Play / Sculpt & Simulate CTA | `text.primary` (`#f8fafc`) | `5.1:1` | **PASS (AA)** |
| `status.error` | `#ef4444` | `RAPID_COLLISION` / limit alert | `surface` (`#1e293b`) | `4.6:1` | **PASS (AA)** |

---

## 3. Typography Hierarchy

| Level | Font Family | Size | Weight | Line Height | Intended Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `H1` | Sans | `18px` | `600` | `1.3` | Application header |
| `H2` | Sans | `14px` | `600` | `1.3` | Panel titles (Facial Sculpt, Stock, Playback) |
| `Body` | Sans | `13px` | `400` | `1.4` | Slider labels and buttons |
| `Mono / Data` | Mono | `12px` | `400` | `1.4` | Live `(r, theta, h, phi)` and `v_tip` telemetry |

---

## 4. Component Anatomy & States

### Component: Simulation Transport Bar & Telemetry Readout
- **Placement**: Docked along the bottom of the 3D viewport.
- **States**:
  - **Idle / Ready**: `Play` enabled, timeline scrubber at `0%`, live coordinates at home pose.
  - **Playing**: `Pause` active, scrubber advancing smoothly, speed selector (`1x`, `5x`, `10x`, `20x`), real-time joint + tip readout updating.
  - **Collision / Limit Fault**: Transport pauses automatically, status badge highlights `#ef4444` (`RAPID_COLLISION` or `SOFT_LIMIT_EXCEEDED`), and the offending cutter segment renders red.

---

## 5. Responsive Layout & Breakpoints

| Viewport | Breakpoint | Layout Pattern | Sizing Rules |
| :--- | :--- | :--- | :--- |
| **Desktop** | `>= 900px` | Left sidebar (`320px`) + full viewport + bottom transport | Compact sliders, fixed monospace readout cells |
| **Mobile** | `< 900px` | Top 3D viewport + scrollable stacked controls | Touch targets $\ge 44\text{px}$ on transport buttons |

---

## 6. Interaction, Motion & Sound
- **Transitions**: `150ms ease-out` on buttons and slider thumbs; `THREE.Clock` drives frame-independent 3D motion.

---

## 7. Do's and Don'ts
- **DO** render the target face mesh as a toggleable translucent wireframe/ghost inside the carved wax SDF so users can visually compare carved progress against the target.
- **DON'T** duplicate kinematic math in UI components; render strictly from backend-sampled telemetry.
