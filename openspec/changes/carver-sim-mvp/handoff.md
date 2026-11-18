# OpenCode Orchestration Handoff: OpenSpec Change 'carver-sim-mvp'

You are the orchestration agent for OpenSpec change 'carver-sim-mvp' running in OpenCode.
Your primary directive is to execute this change using the **`openspec-apply-sub`** skill, which delegates task implementation to the `spec-coder-sub` subagent.

## 1. Orchestration Directive
- **Change Name**: `carver-sim-mvp`
- **Target Skill**: `openspec-apply-sub` (or `/opsx:apply-sub carver-sim-mvp`)
- **Architecture Paradigm**: Vertical Slice Architecture (VSA). Maintain strict isolation between feature compartments (`carver-kinematics`, `face-sculpt-sim`, `volumetric-wax-viewer`) and avoid horizontal abstractions.

## 2. Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `machine_config.json` | `[NEW]` | Define turntable/wax datums, `pivot_to_tip_mm`, `arm_radial_offset_mm`, `arm_to_pivot_z_mm`, conical-bevel + shank profile, `melt_kerf_mm`, stock/plinth defaults (`R_stock=40.0`, `H_stock=120.0`, `z_plinth_mm=10.0`, `finish_allowance_mm=1.5`), feeds, per-axis `v_max`, singularity thresholds (`r_s_min_mm=2.0`, `theta_dot_warn_rad_s=3.0`), and soft limits. |
| `package.json` | `[NEW]` | Pin Node `>=20` and Three.js dependency/version for deterministic browser and `node --test` execution. |
| `kinematics.py` | `[NEW]` | Single-source-of-truth 4-DOF FK/IK (`theta = theta_ring - theta_platter`, $+\phi$ about $+\hat{e}_\theta$), `tip_xyz_wax` & `tool_axis_wax`, $r$–$Z$ normal projection, `PHI_POLICY_CLAMPED`, `SOFT_LIMIT_EXCEEDED`, feed/joint-velocity timing, relative $v_{\text{tip}}$ (unwrapped $\theta$), and `SINGULARITY_HIGH_THETA_DOT`. |
| `presets/base_head.stl` | `[NEW]` | Procedurally generated, watertight, positive-volume base head mesh facing `+X` at $\theta=0$ seated on cylindrical plinth $z \in [0, z_{\text{plinth}}]$. |
| `presets/base_head_landmarks.json` | `[NEW]` | Landmark centers, radii, and max displacement bounds for `nose`, `brow`, `cheeks`, `jaw`, `chin`. |
| `face_sculpt.py` | `[NEW]` | `apply_facial_modifications` using `scipy.spatial.cKDTree` RBF/Gaussian normal displacement, non-self-intersection guard, and `STOCK_BOUNDS_EXCEEDED` validation. |
| `toolpath_sim.py` | `[NEW]` | `generate_synthetic_carve_path` with Stage 1 shadow-aware cylindrical roughing ($\phi=0^\circ$, $r_{\text{shadow}}$), Stage 2 2D $r$–$Z$ slice undercut finishing + CC$\to$CL offset + `UNREACHABLE_UNDERCUT_AREA`/`GOUGE`, safe-by-construction `is_rapid` retracts, engaged-length resampling ($\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$), and `demo`/`standard` presets. |
| `server.py` | `[NEW]` | FastAPI app exposing `GET /api/health`, `POST /api/sculpt-and-sim` (columnar base64 `Float32Array`/`Uint8Array` buffers, `max_frames=250_000` cap), and static mount. |
| `static/machine_rig.js` | `[NEW]` | `PrimitiveCarverRig` inside `-90°` X-rotated root group (machine `+Z` up $\to$ Three.js `+Y` up) driven solely by backend poses with zero JS trig. |
| `static/wax_sdf_core.js` | `[NEW]` | Pure JS (zero DOM/Three.js imports) exact Euclidean cylinder SDF + exterior padding, conical-bevel + `melt_kerf_mm` subtraction, `16³` chunks with 1-voxel apron + neighbor dirtying + global gradient normals, `RAPID_COLLISION`, `SHANK_COLLISION`, and periodic snapshots. |
| `static/wax_worker.js` | `[NEW]` | Web Worker wrapping `wax_sdf_core.js` for off-thread subtraction, snapshot restore/replay on scrub, and transferable `Float32Array` chunk mesh buffers. |
| `static/wax_sdf.js` | `[NEW]` | `VolumetricWaxGrid` Three.js `BufferGeometry` adapter communicating with `static/wax_worker.js`. |
| `static/index.html` | `[NEW]` | Split-pane dark CAD/CAM studio UI (left control sidebar, full-height WebGL viewport, bottom transport bar). |
| `static/app.js` | `[NEW]` | Facial sliders, `Demo`/`Standard` preset selector, `THREE.Clock` loop, `Play/Pause`/`Scrub`/`1x–20x`/`Carve to End`, fault auto-pause, and live telemetry readout (zero JS trig). |
| `tests/test_carver_sim.py` | `[NEW]` | Python `unittest` suite covering FK algebraic/sign + pending-hardware `±1.0 mm` fixture, IK round-trip + `PHI_POLICY_CLAMPED` + `SOFT_LIMIT_EXCEEDED`, `v_tip` + singularity, watertight/non-self-intersecting sculpting + `STOCK_BOUNDS_EXCEEDED`, roughing/finishing/resampling, and `POST /api/sculpt-and-sim`. |
| `tests/test_wax_sdf.mjs` | `[NEW]` | Node `node --test` suite covering `wax_sdf_core.js` undercut subtraction across `16³` chunk boundaries + dirty neighbors, `RAPID_COLLISION`, `SHANK_COLLISION`, snapshot scrub replay, surface fidelity, and zero-trig JS lint. |

## 3. Technical & Architectural Boundaries
- **In-Scope Decisions**:
  - **Single-Source-of-Truth Kinematics in Python**: `theta = theta_ring - theta_platter` (`rad`, wax azimuth $\theta_s = \theta$); wrist $+\phi$ rotates about $+\hat{e}_\theta$ tilting inward toward $-r$; Python emits `tip_xyz_wax` and `tool_axis_wax` so Three.js performs zero kinematic trig.
  - **Chunked Volumetric SDF in Web Worker**: `128³` float32 (`8 MiB`) partitioned into `16³` chunks (`512` chunks) with exact Euclidean cylinder initialization, `>= 2` voxel exterior padding, 1-voxel apron + neighbor dirtying + global central-difference normals, and periodic `8 MiB` scrub snapshots in `wax_worker.js`.
  - **Pure JS Core Split**: `static/wax_sdf_core.js` has zero DOM/Three.js imports so `node --test tests/test_wax_sdf.mjs` runs natively in Node `v22.23.2`.
  - **Columnar API Payload**: `POST /api/sculpt-and-sim` returns base64-encoded `Float32Array` / `Uint8Array` trajectory buffers capped at `250,000` frames.
- **Hard Exclusions / No-Go**:
  - Do NOT modify `.env`, `.env.*`, or credential files.
  - Do NOT introduce unapproved external dependencies outside `requirements.txt`, `requirements-dev.txt`, and `package.json`.
  - Do NOT implement controller-specific G-code emission (`G93`/`G94`), CAD `.glb` skinning, or transient thermal PDEs (deferred).
  - Do NOT perform code modifications outside the Target Context Map without prior task coverage.

## 4. Visual & UI Design Specifications
- **Theme**: `Carving Studio Clean Technical UI` (precision dark-mode CAD/CAM workstation)
- **Key Tokens**:
  - Primary: `#2563eb` | Background: `#0f172a` | Surface: `#1e293b` | Border: `#334155` | Wax Stock: `#e8d595`
  - Text: Primary `#f8fafc`, Muted `#94a3b8`
  - Status: Success `#22c55e`, Warning `#f59e0b`, Error `#ef4444`
  - Fonts: Sans `Inter, system-ui, -apple-system, sans-serif`; Mono `'JetBrains Mono', ui-monospace, monospace`
- **Component Anatomy & States (Simulation Transport Bar & Telemetry Readout)**:
  - **Idle / Ready**: `Play` and `Carve to End` enabled, preset selector (`Demo` / `Standard`), timeline scrubber at `0%`, live coordinates at home pose.
  - **Playing**: `Pause` active, scrubber advancing smoothly, speed selector (`1x`, `5x`, `10x`, `20x`), real-time joint + tip readout updating.
  - **Scrubbing**: Rig updates immediately to scrubbed frame while Web Worker restores nearest preceding SDF snapshot and replays intervening subtractions asynchronously.
  - **Collision / Limit Fault**: Transport pauses automatically, status badge highlights `#ef4444` (`RAPID_COLLISION`, `SHANK_COLLISION`, or `SOFT_LIMIT_EXCEEDED`), and offending cutter/shank segment renders red (`#f59e0b` badge for `SINGULARITY_HIGH_THETA_DOT` or `UNREACHABLE_UNDERCUT_AREA`).
- **Responsive Layout**:
  - Desktop (`>= 900px`): Left sidebar (`320px`) + full viewport + bottom transport bar.
  - Mobile (`< 900px`): Top 3D viewport + scrollable stacked controls, touch targets `>= 44px`.

## 5. Test Scaffolding & Verification Commands
- **Primary Test Runners**:
  - Python (`Python 3.11.2`): `python3 -m unittest discover -s tests -v`
  - Node (`Node v22.23.2`): `node --test tests/test_wax_sdf.mjs`
- **TDD Requirement**: Task group `## 1` MUST scaffold failing unit/integration tests before touching implementation code. Verify they fail initially.

## 6. Implementation Task Checklist
- [ ] 1.1 Scaffold failing tests in `tests/test_carver_sim.py` for 4-DOF FK algebraic/sign verification ($\phi = 0^\circ, 90^\circ$, `tip_xyz_wax`, `tool_axis_wax`), IK round-trip + `PHI_POLICY_CLAMPED` + tangential-normal fallback, `SOFT_LIMIT_EXCEEDED`, and a pending-hardware `±1.0 mm` calibration fixture
- [ ] 1.2 Scaffold failing tests for relative tip speed (`v_tip` on pure $\theta$ rotation and combined $(r, \theta, h, \phi)$ motion with $\phi \ne 0^\circ$ and unwrapped $\theta$), timing model, and `SINGULARITY_HIGH_THETA_DOT`
- [ ] 1.3 Scaffold failing tests for watertight, non-self-intersecting parametric facial deformation (`apply_facial_modifications`) bounded inside $(R_{\text{stock}} - \text{finish\_allowance\_mm}, H_{\text{stock}})$ and `STOCK_BOUNDS_EXCEEDED`
- [ ] 1.4 Scaffold failing tests for shadow-clipped roughing, $r$–$Z$ undercut finishing (`UNREACHABLE_UNDERCUT_AREA`, `GOUGE`), engaged-length resampling ($\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$), and `POST /api/sculpt-and-sim` columnar base64 payload contract
- [ ] 1.5 Scaffold failing Node tests in `tests/test_wax_sdf.mjs` for `wax_sdf_core.js`: undercut subtraction across `16³` chunk boundaries + dirty neighbors, `RAPID_COLLISION`, `SHANK_COLLISION`, snapshot scrub replay, surface fidelity, and zero-trig JS lint
- [ ] 2.1 Create `machine_config.json` (datums, `pivot_to_tip_mm`, conical-bevel + shank profile, `melt_kerf_mm`, stock/plinth defaults, feeds, per-axis `v_max`, singularity thresholds, soft limits) and `package.json` (pinning Node `>=20` and Three.js)
- [ ] 2.2 Implement `kinematics.py` with Python-only FK/IK (`tip_xyz_wax`, `tool_axis_wax`, $r$–$Z$ normal projection, `PHI_POLICY_CLAMPED`, `SOFT_LIMIT_EXCEEDED`), segment timing, relative $v_{\text{tip}}$, and `SINGULARITY_HIGH_THETA_DOT`
- [ ] 2.3 Procedurally generate watertight `presets/base_head.stl` + `presets/base_head_landmarks.json` and implement `face_sculpt.py` (`cKDTree` RBF/Gaussian normal deformations, non-self-intersection guard, `STOCK_BOUNDS_EXCEEDED`)
- [ ] 2.4 Implement `toolpath_sim.py` Stage 1: shadow-aware cylindrical roughing ($\phi = 0^\circ$) with safe-by-construction `is_rapid` retracts
- [ ] 2.5 Implement `toolpath_sim.py` Stage 2: 2D $r$–$Z$ slice undercut finishing, $\phi$ selection, CC$\to$CL offset, `UNREACHABLE_UNDERCUT_AREA` / `GOUGE` diagnostics, engaged-length resampling, and `demo`/`standard` presets
- [ ] 2.6 Implement `server.py` (FastAPI) exposing `GET /api/health`, `POST /api/sculpt-and-sim` (columnar base64 `Float32Array`/`Uint8Array` buffers, `max_frames` cap), and static file serving
- [ ] 3.1 Run SDF performance benchmark spike measuring `128³` conical-bevel subtraction + `16³` dirty-chunk Marching Cubes remesh time to verify $\ge 30\text{ FPS}$ budget
- [ ] 3.2 Implement `static/machine_rig.js` (`PrimitiveCarverRig` inside `-90°` X-rotated root group, driven solely by backend poses with zero JS trig)
- [ ] 3.3 Implement `static/wax_sdf_core.js` (pure JS exact cylinder SDF + exterior padding, conical-bevel subtraction, `16³` chunks with 1-voxel apron + neighbor dirtying + global gradient normals, `RAPID_COLLISION`, `SHANK_COLLISION`, and snapshots)
- [ ] 3.4 Implement `static/wax_worker.js` and `static/wax_sdf.js` (Web Worker with transferable chunk mesh buffers and Three.js `BufferGeometry` adapter)
- [ ] 3.5 Implement `static/index.html` and `static/app.js` with facial sliders, `Demo`/`Standard` preset, `THREE.Clock` loop, transport bar (`Play/Pause`, `Scrub`, `1x–20x`, `Carve to End`), fault auto-pause, and live telemetry
- [ ] 4.1 Run full Python (`python3 -m unittest discover -s tests -v`) and Node (`node --test tests/test_wax_sdf.mjs`) test suites and verify clean passes
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate carver-sim-mvp --strict`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix, resolved assumptions, hardware calibration fixture status, and verbatim execution logs

## 7. Post-Implementation & Verification Obligations
When `spec-coder-sub` finishes:
1. Verify all checkboxes in `tasks.md` are marked `- [x]`. Only tick boxes that genuinely ran and passed.
2. Check data preservation: confirm record/feature counts before and after if touching data models.
3. Ensure `openspec/changes/carver-sim-mvp/verification.md` is populated with:
   - Executive Summary & Environment
   - Requirement Adherence Audit Matrix (mapping every spec scenario to its verifying test)
   - Resolved Assumptions & Empirical Proof (including SDF benchmark spike timings and hardware calibration fixture status)
   - Nomenclature & Code Symbol Audit
   - Verbatim Execution Logs
4. Automatically run verification via `openspec-verify-change`.
5. If clean with no critical issues, sync specs: `openspec specs apply --change "carver-sim-mvp"`.
6. **Open a Pull Request**: Once implementation is complete and `openspec/changes/carver-sim-mvp/verification.md` is written and verified with zero critical issues:
   - Ensure your work is on a dedicated feature branch (create/switch to `feat/carver-sim-mvp` if currently on `main`/`master`).
   - Stage and commit all implementation code and every artifact within the change directory (`git add openspec/changes/carver-sim-mvp openspec/specs <implementation-files>`), then push the branch (`git push -u origin HEAD`).
   - Open a Pull Request using `gh pr create --fill` (or with a concise title and a body summarizing `openspec/changes/carver-sim-mvp/proposal.md` and `openspec/changes/carver-sim-mvp/verification.md`) and report the PR URL.
