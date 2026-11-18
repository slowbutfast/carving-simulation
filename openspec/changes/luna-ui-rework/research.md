## Source material

- **Porting Handoff (`wax-robot` $\to$ `carving-simulation`)**:
  - `wax-robot/static/xp.css` (1000 lines): Windows XP Luna Blue desktop (`#3a6ea5`), window chrome (`#ece9d8`), Luna titlebar gradient, 3D outset/inset bevels, green action button, and COMCTL32-style `.status-bar`.
  - `wax-robot/static/index.html` & `wax-robot/static/viewer.js`: 6-layer semantic DOM (`div.desktop` $\to$ `main.window` $\to$ `div.titlebar`, `nav.menu-bar`, `div.window-body`, `footer.status-bar`, `div.xp-dialog`) with `ResizeObserver` viewport sizing and `< 900px` `.mobile-tabs`.
- **Google `DESIGN.md` Specification (via `opensrc`)**:
  - Cached at `/home/node/.opensrc/repos/github.com/google-labs-code/design.md/main/README.md`.
  - Defines YAML front matter (`version`, `name`, `description`, `colors`, `typography`, `rounded`, `spacing`, `components` with `{path.to.token}` references) + ordered `##` sections (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`).
- **Emoji-Free Constraint**:
  - All UI labels, titlebar icons, action buttons, and transport controls MUST use plain ASCII text or CSS/SVG geometric shapes—no Unicode emojis.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| Google `DESIGN.md` | YAML-front-matter + ordered-section design spec per `github.com/google-labs-code/design.md` | Unstructured prose |
| `.transport-dock` | Recessed XP playback bar inside `.inset-well.viewport-well` (`Prev`, `Play/Pause`, `Next`, scrubber, `sim-time`, `sim-speed`) | Floating modern pill bar |
| Emoji-Free Chrome | Plain text / ASCII / CSS geometric controls (`Play`, `Pause`, `Prev`, `Next`, `Recalculate Surface`) | Unicode emojis (`🔥`, `⚡`, `▶`, `⏮`, `⏭`) |

## Candidate tech

| Option | Decision | Reason |
| :--- | :--- | :--- |
| **Port `wax-robot/static/xp.css` + `.transport-dock` additions** | Adopted | Authentic XP Luna tactility with zero CSS framework overhead |
| **Google `DESIGN.md` schema for `design.md` & root `DESIGN.md`** | Adopted | Machine-readable tokens + lintable via `@google/design.md` |
| **Unicode emojis for icons/buttons** | Rejected | Explicitly excluded; use clean text/ASCII labels |

## Verified facts

| Claim | Value | How verified | Date |
| :--- | :--- | :--- | :--- |
| Google `DESIGN.md` repo cached in `opensrc` | `github.com/google-labs-code/design.md@main` | `opensrc list` & read `README.md` | 2026-11-18 |
| `wax-robot/static/xp.css` exists | 1000 lines, vanilla CSS | Read `wax-robot/static/xp.css` | 2026-11-17 |
| Required `DESIGN.md` section order | Overview, Colors, Typography, Layout, Elevation & Depth, Shapes, Components, Do's and Don'ts | Read `google-labs-code/design.md/README.md` | 2026-11-18 |

## Unverified assumptions

| Assumption | Confidence | How to verify |
| :--- | :--- | :--- |
| `npx @google/design.md lint` runs cleanly on the generated `DESIGN.md` | High | Run lint check or verify token references and WCAG contrast in `tasks.md` |
