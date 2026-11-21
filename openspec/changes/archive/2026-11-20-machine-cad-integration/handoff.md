# OpenCode Orchestration Handoff: OpenSpec Change 'machine-cad-integration'

You are the orchestration agent for OpenSpec change 'machine-cad-integration' running in OpenCode.
Your primary directive is to execute this change using the **`openspec-apply-sub`** skill, which delegates task implementation to the `spec-coder-sub` subagent.

## 1. Orchestration Directive
- **Change Name**: machine-cad-integration
- **Target Skill**: `openspec-apply-sub` (or `/opsx:apply-sub machine-cad-integration`)
- **Architecture Paradigm**: Vertical Slice Architecture (VSA). Maintain strict isolation between feature compartments and avoid horizontal abstractions. Here the slices are:
  - offline CAD extraction (`scripts/extract_machine.py` → committed JSON/GLB)
  - `tool_model.py` (the only runtime tool definition)
  - kinematics/config
  - toolpath/API
  - viewer (`cad_rig.js`, worker SDF)

  Slices talk only through `machine_geometry.json`, the merged config and `tool_model`'s public functions.
- **Branch**: `feat/machine-cad-integration` from `main` at or after `f207131` (contains the MVP squash `98ac91d`, this change's artifacts, and the byte-exact STEP).
- **Read first, in order**:
  1. `research.md` (glossary + Verified/Unverified tables)
  2. `proposal.md`
  3. all five `specs/*/spec.md`
  4. `architecture.md`
  5. `tests.md`
  6. `tasks.md`
  7. `design.md`

  The glossary is binding: "tool reference point" (not "apex"), "orbit ring" (not "platter"), signed `r`, and `h` to the pivot.

## 2. Target Context Map
Line numbers are for `main` at `f207131`.

| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `requirements-cad.txt` | `[NEW]` | `cadquery-ocp==8.0.1.1.0`, `trimesh`, `numpy`. Dev-only. Never add OCP to `requirements.txt`. |
| `cad_part_roles.json` | `[NEW]` | Ordered prefix → link rules from the architecture.md §2 draft table. `FST_*` handling. Default `unassigned`. `Cold_Tool_6mm_Shank`, `Dowel_3x37` → `unassigned`. `Wax_Block_Cast` → `stock_placeholder`. |
| `scripts/extract_machine.py` | `[NEW]` | XCAF walk. OCP 8.0.1 quirks: no `TDF_LabelSequence`, so use `TDF_ChildIterator` + `IsComponent_s`/`IsFree_s`; use `Bnd_Box.CornerMin/CornerMax`, not `Get()`; use `TopoDS.Face`, not `Face_s`; set `Interface_Static.SetCVal_s("xstep.cascade.unit","MM")`. CAD→machine `(x,y,z)→(x,−z,y−seat_y_cad)`, `seat_y_cad=3.0`. Writes constants with provenance, travel, tool block (incl. explicit head-envelope hull), `cad_reference_pose`, `home_pose: null`, `pivot_candidates`, `step_sha256`, `ocp_version`, sorted and rounded JSON, and per-link GLBs. |
| `machine_geometry.json` | `[NEW]` (generated, committed) | Never hand-edit. Regenerate. |
| `static/models/{static,orbit,z,radial,tilt,unassigned}.glb` | `[NEW]` (generated, committed) | ≤ 8 MiB total. Cartridge deflection ≤ 0.02 mm. Node names = CAD occurrence names. |
| `tool_model.py` | `[NEW]` | Frame (a_n, a_w, u) right-handed with `a_n × a_w = u`, a_w = e_θ, **a_n = −e_r at φ = 0**. `heated_sdf` (exact box − kerf). `place_on_contact` (support function, centroid tie-break). `body_penetrates` (shaft/body/head rings, explicit sign handling). `feed_class`. |
| `kinematics.py` | `L135-L143` (`load_config`) | Merge `machine_geometry.json` under `machine_config.json`. Config may narrow, never widen, CAD travel. A `null` CAD limit needs an explicit conservative, provenance-labelled config fallback, else fail closed. Blade dims are not overridable. |
| `kinematics.py` | `L179-L226` (`forward_kinematics`) | Docstrings/datums only: orbit θ, signed r, h to the pivot (h2 = 0), "tool reference point". The equations keep their form. |
| `kinematics.py` | `L235-L306` (`validate_joints`) | Signed `r_limits_mm`, CAD-derived θ/h/r limits, null-limit fail-closed. |
| `kinematics.py` | `L308-L400` (`_project_normal`, `phi_selection_policy`, `inverse_kinematics_with_policy`) | Signed-r branch choice (θ-limit feasibility, then min \|Δθ\|). φ_ideal projected into the chosen solution's own e_r. |
| `kinematics.py` | `L420-L553` (`segment_timing`, `build_trajectory`) | \|r_s\| singularity check across axis crossings. |
| `machine_config.json` | whole file (82 lines) | Remove cone/shank keys. Add `heated_length_mm`, `broadside_threshold_deg`, `finish_phi_search_step_deg`. `v_max.theta_rad_s` ≤ 1.0. Stock R/H stay configurable (unverified). Drop geometry now owned by `machine_geometry.json`. |
| `toolpath_sim.py` | `L1-L30` (module docstring), `L150-L260` (`_engaged*` helpers, `resample_path`) | Sampling bound 0.5·(blade_thickness + 2·kerf) over heated-region corner points. Remove `tip_width`/`engaged` reads at L238-L240. |
| `toolpath_sim.py` | `L669-L826` (`finishing_phi`, `cutter_location`, `tool_body_penetrates`) | Replace cone geometry (α at L681, `ρ+kerf` at L699-L702, cone stations at L735-L813) with `tool_model` calls. Keep `section_polylines` (L550) frozen. It's tool-agnostic and verified. |
| `toolpath_sim.py` | `L828-L990` (`build_roughing`) | Remove the cone shank-safe step-down (L843-L864). `place_on_contact` against the shadow. θ-direction ring passes. `feed_class` → `BLADE_BROADSIDE_FEED`. |
| `toolpath_sim.py` | `L991-L1220` (`_tool_body_clearance`, `_sample_poses`, `exit_moves`, `entry_moves`) | Clearance from the tool's radial support extent (L995-L997 are cone). Body checks via `tool_model.body_penetrates`. |
| `toolpath_sim.py` | `L1221-L1382` (`build_finishing`) | Collision search over φ candidates ordered from φ_ideal, early exit. `UNREACHABLE_UNDERCUT_AREA`/`GOUGE`. No closed-form cone bound. |
| `server.py` | `L55-L67` (`ToolCfg`), `L166-L200` (`sculpt-and-sim`) | `tool_cfg` whitelist `melt_kerf_mm`, `heated_length_mm` (≤ blade length). 422 naming any removed cone key. `config.geometry_provenance` in the response. |
| `static/wax_sdf_core.js` | `L10`, `L39`, `L298-L350` (`subtractTool`, `subtractSegment`), `L426-L500` (`checkRapid`, `checkShank`) | Blade inflated-box SDF in the tool frame rebuilt from `theta_s` + `tool_axis_wax`. Per-body shank checks reporting `shaft`/`body`/`head`. |
| `static/wax_worker.js` | `L18-L32` (tool `pick(...)`), `L110-L125` | Read blade constants from the config payload. Delete cone `pick`s. |
| `static/cad_rig.js` | `[NEW]` | `CadCarverRig`: GLTFLoader at the Three version pinned in `static/index.html`'s importmap (`package.json`: `three@0.187.0`). `static ⊃ orbit ⊃ z ⊃ radial ⊃ tilt`. Deltas from `cad_reference_pose`. Pre-baked tilt pivot. Ghosted `unassigned`, hidden `stock_placeholder`. Tip marker. Load-failure fallback. Zero trig. |
| `static/machine_rig.js` | whole file | **Delete** (after `cad_rig.js` is wired). |
| `static/app.js` | `L10`, `L139`, `L425-L445` (badges) + display controls | Swap to `CadCarverRig`, wax parented to `static`, machine-detail toggle, unassigned note, provenance readout, `BLADE_BROADSIDE_FEED` warning badge. |
| `tests/test_machine_cad.py`, `tests/test_machine_cad_extract.py`, `tests/test_tool_model.py`, `tests/test_cad_rig.mjs`, `tests/fixtures/heated_sdf_parity.json` | `[NEW]` | Per tests.md. |
| `tests/test_carver_sim.py` | `L78-L312` (kinematics classes), `L375-L481`, `L563-L724` (incl. `@unittest.expectedFailure` at **L589**), `L725-L1033` (`TestFinishingHelpers`), `L1034-L1069` | Migrate fixtures that encode p = 30, the cone or `r ≥ 0`. **Remove the L589 `expectedFailure` and make the test pass** (exit criterion). Every migrated assertion goes in `patch.md` with its reason. |
| `tests/test_wax_sdf.mjs`, `tests/test_wax_worker.mjs` | existing cone cases | Blade stamp, parity, direction-dependent kerf, per-body shank. |
| `README.md` | setup section | `.venv-cad` instructions. |
| `openspec/changes/machine-cad-integration/{research,patch,verification,tasks}.md` | append | 0.3 baseline row. Owner answers (7.x). Patch log. Verification. |

## 3. Technical & Architectural Boundaries
- **In-Scope Decisions**:
  - **CAD is the source of truth via offline extraction.** Runtime code never imports `OCP` or reads `.stp`, and an import-scan test guards this. Artifacts are regenerated, never hand-edited. `step_sha256` must equal `00882f0ebeaeaae66b7b8eb28e4d2dc9bbf30d65c2d66705f86deec566fd7bd0`. `.gitattributes` marks `*.stp`/`*.glb` binary, so don't change that.
  - **Kinematics keep the FK equation form.** Datum changes: θ = orbit ring, signed r to the pivot, h to the pivot (h2 = 0), x = `pivot_radial_offset_mm` (0.0), p = 60.0.
  - **`tool_model.py` is the only tool definition.** The JS SDF mirrors its constants from the same JSON, pinned by a 1e-5 mm parity fixture.
  - **CL placement:** `cl = cc + kerf·n − s₀(−n)`, where s₀ includes the box centre offset `heated_length/2` along −u. Never `cc + (ρ+kerf)·n`.
  - **Sign conventions:** trimesh `signed_distance` is **positive inside**, and the wax SDF is **negative inside**. This cost two PATCH-10 rounds. State the convention in every test docstring that touches it.
  - **Unknowns stay explicit:** `home_pose: null`. Unknown travel limits fail closed without a labelled config fallback. `Cold_Tool_6mm_Shank` stays `unassigned`. The rectangular wax block is `stock_placeholder` and is never rendered or simulated.
- **Hard Exclusions / No-Go**:
  - Do NOT modify `.env`, `.env.*`, or credential files.
  - Do NOT introduce unapproved external dependencies. The only addition is `cadquery-ocp==8.0.1.1.0` in `requirements-cad.txt`. No networkx, no mesh-decimation library, no `cascadio`/`gmsh`.
  - Do NOT perform code modifications outside the Target Context Map without prior task coverage.
  - Do NOT touch `openspec/changes/xp-ui-overhaul/` or start any XP/Luna UI work. That change runs **after** this one.
  - Do NOT commit `assets/*.stl`, `.venv*`, `.sweep/`, or generated scratch output.
  - Do NOT edit `section_polylines` (`toolpath_sim.py:L550`). It's tool-agnostic and verified.
  - Do NOT redesign the finishing *strategy* (pass ordering, slice-oriented contours). Swap geometry primitives only. The strategy redesign is a follow-up change.
  - Do NOT weaken a spec-derived assertion to make a test pass. If a fixture encodes the old machine, migrate it to the new geometry and log it in `patch.md`. If you think a spec scenario is wrong, stop and report it rather than editing the test.
  - Stop and report (don't guess) if extraction contradicts research.md → Verified facts by more than the stated tolerances: p 60.0 ± 0.05, r travel [−51, 135] ± 0.5, reference point (0, 0, 91.0) ± 0.05.

## 4. Visual & UI Design Specifications & Vision Verification
- **Theme**: Carving Studio Clean Technical UI (inherited chrome) + CAD Rig Scene Materials.
- **Key Tokens**:
  - Primary: `#2563eb` | Background: `#0f172a` | Surface: `#1e293b`
  - Text: Primary `#f8fafc`, Muted `#94a3b8`
  - Scene: wax `#e8d595`, links `static #4b5563` → `orbit #64748b` → `z #7c8796` → `radial #94a3b8` → `tilt #cbd5e1`, blade heated `#f97316` (emissive 0.25), unassigned ghost `#a78bfa` @ 35 % opacity. Status: warning `#f59e0b`, error `#ef4444`.
  - One material factory in `cad_rig.js`. One colour per link (no per-part or Fusion colours). `MeshStandardMaterial` metalness 0.3, roughness 0.6.
- **Component Anatomy & States**:
  - **CAD rig**: Default / Playing (transforms only) / Fault (the offending body, whether blade, shaft, body or head, turns `status.error` for that frame, with the existing auto-pause) / GLB load failure (machine links hidden, tool-only rig + wax, `status.warning` toast "Machine model failed to load — showing tool only").
  - **Machine-detail toggle**: Full (default on desktop) / Tool only (`static`/`orbit`/`z` hidden). Inherited hover/focus. Disabled while GLBs load.
  - **Unassigned-parts note**: one muted line, shown only when non-empty. Clicking toggles ghost visibility.
  - **Provenance readout**: `Mono / Data` 12px, `STEP <sha8> · home: unset` appended to telemetry.
  - **`BLADE_BROADSIDE_FEED`**: existing amber warning badge path.
- **Responsive Layout**: ≥ 900px inherited split-pane, Full detail. < 900px inherited stack, toggle defaults to **Tool only**, touch targets ≥ 44px.
- **Multi-Modal Vision Verification**:
  - `deepseek-flash` natively supports vision inputs. For visual tasks, capture UI state screenshots using Playwright CLI (e.g. `npx playwright screenshot <url> <output.png>`), and inspect the resulting image file directly. Check: the machine at `cad_reference_pose` with the T12 pointing down and no rectangular block; the ring orbiting with static wax mid-playback; Tool-only at 390px width.
  - If a task requires subjective eye-ball tuning or physical hardware display calibration beyond automated inspection, leave that specific visual check marked for manual maintainer review while completing all automated code, test, and layout tasks. Task 7.1's owner sign-off on roles and the joint sweep is one of these. Produce the recording and the roles file, then leave it for the owner.

## 5. Test Scaffolding & Verification Commands
- **Environment setup** (worktree has no venvs yet):
  - `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
  - `python3 -m venv .venv-cad && .venv-cad/bin/pip install -r requirements-cad.txt` (about 100 MB of wheels from PyPI. Needs network.)
- **Primary Test Runners**:
  - `.venv/bin/python -m unittest discover -s tests -v`. The MVP suite takes about 11 min. Run focused classes while iterating, e.g. `.venv/bin/python -m unittest tests.test_tool_model -v`.
  - `node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs tests/test_cad_rig.mjs`. Name files explicitly. `scripts/sweep_path.mjs` is a CLI, not a test.
  - `.venv-cad/bin/python -m unittest tests.test_machine_cad_extract -v`. OCP-gated with `skipUnless`.
  - Extraction: `.venv-cad/bin/python scripts/extract_machine.py` (regenerates `machine_geometry.json` + GLBs. Run twice and diff for determinism).
- **TDD Requirement**: Task group ## 1 MUST scaffold failing unit/integration tests before touching implementation code. Verify they fail initially, and record the expected-red list in `patch.md` (task 1.9). Task 0.3 (baseline timing on `98ac91d`) must be recorded **before** any `toolpath_sim.py` edit.

## 6. Implementation Task Checklist
- [x] 0.1 `carver-sim-mvp` merged to `main` on 2026-11-19 as squash commit `98ac91d` (PR #1). It merged **with** cone-based undercut finishing (`build_finishing` composed from PATCH-10c helpers 1–5), not descoped, and `test_finishing_follows_planar_contours` is marked `@unittest.expectedFailure` (PATCH-10f: corner-normal standoff collapse). This change **replaces** that cone geometry in `build_finishing` and its helpers (`finishing_phi`, `cutter_location`, `tool_body_penetrates`, `entry_moves`/`exit_moves`) with `tool_model.py`. Exit criterion: that `expectedFailure` is removed and the test passes, or the test is rewritten against `place_on_contact` with the change recorded in `patch.md`. Branch `feat/machine-cad-integration` from `main` at or after `98ac91d`.
- [x] 0.2 Commit `assets/Wax+Face+Carver+v2.stp`. Add `assets/*.stl` to `.gitignore` with a comment ("derived, nameless; use the STEP").
- [ ] 0.3 On `main` at `98ac91d`, record the MVP `demo` toolpath-generation wall-time baseline in `research.md` → Verified facts, including revision, enabled stages, slider values, frame count, and environment. Compare only the same enabled stages in the performance guard.
- [ ] 1.1 Write failing `tests/test_machine_cad.py` for "Deterministic STEP extraction into derived machine artifacts" (units/frame/orbit axis, provenance/staleness, runtime import guard).
- [ ] 1.2 Write failing `tests/test_machine_cad.py` cases for "Explicit CAD part-to-link role mapping with unassigned reporting" (295 coverage, unassigned/placeholder lists).
- [ ] 1.3 Write failing `tests/test_machine_cad.py` cases for "CAD-derived kinematic constants and travel evidence with provenance" and "Link meshes in the machine frame within a size budget".
- [ ] 1.4 Write `tests/test_machine_cad_extract.py` (OCP-gated `skipUnless`): determinism, committed-artifact-current, unmatched-part surfacing.
- [ ] 1.5 Write failing `tests/test_tool_model.py` for all five blade-tool-model requirements (frame, heated SDF probes, support placement, body collision, feed class).
- [ ] 1.6 Migrate `tests/test_carver_sim.py` kinematics tests to the new datums (signed r, orbit θ, CAD reference pose, synthetic θ-stop signed-r IK, |r_s| singularity, v_max θ default, and rejection of a null CAD limit without an explicit fallback). List every migrated assertion and its reason in `patch.md`.
- [ ] 1.7 Add failing `tests/test_carver_sim.py` cases for the modified face-sculpt-sim requirements (roughing slice fraction, `place_on_contact` CL, collision-search reachability, blade sampling bound, rapid tool-extent clearance, API 422 on cone keys, provenance in response, performance guard).
- [ ] 1.8 Add failing `tests/test_wax_sdf.mjs` cases (parity fixture, direction-dependent kerf, per-body `SHANK_COLLISION`, zero-trig guard on `cad_rig.js`). Add failing `tests/test_cad_rig.mjs` (tip tracking, static wax, GLB-failure fallback).
- [ ] 1.9 Run the suites and record the expected-red list in `patch.md`. No implementation edits in this group.
- [ ] 2.1 Add `requirements-cad.txt` (`cadquery-ocp==8.0.1.1.0`, `trimesh`, `numpy`) and a README note: `python -m venv .venv-cad && .venv-cad/bin/pip install -r requirements-cad.txt`.
- [ ] 2.2 Write `cad_part_roles.json` from the architecture draft table (ordered prefix rules, plus `FST_*` handling, plus `unassigned` default).
- [ ] 2.3 Implement `scripts/extract_machine.py`: XCAF walk (`TDF_ChildIterator`, `IsComponent_s` / `IsFree_s`, `CornerMin/CornerMax`, `TopoDS.Face`); mm units and recording of `source_length_unit`; CAD → machine transform with `seat_y_cad`; role assignment; `unassigned` / `stock_placeholder` lists; SHA-256 and OCP version; sorted, rounded JSON output.
- [ ] 2.4 Compute the constants: pivot from the servo horn axis, also recording the `Dowel_3x37` axis as `pivot_candidates`; tool reference point from the cartridge's lowest face centre; `pivot_to_tip_mm`, `pivot_radial_offset_mm`, `tangential_tool_offset_mm`; `r_travel_mm` from the radial stop faces and carriage half-length; `h_travel_mm` from the Z stops and the carriage-to-pivot offset; `theta_travel_deg` from the stop block vs the arm's swept envelope (`null` plus `reason` if it can't be computed); `cad_reference_pose`, and `home_pose: null`.
- [ ] 2.5 Compute the tool block: blade dims from cartridge sections, shaft/body radii and spans, `head_clearance_mm`, and an explicit head envelope hull (box or capsule) with dimensions and pose relative to the tool reference point, for the tilt link minus the cartridge.
- [ ] 2.6 Export per-link GLBs (node names = occurrence names, per-link linear deflection, cartridge ≤ 0.02 mm) within the 8 MiB budget. Commit `machine_geometry.json` and `static/models/*.glb`.
- [ ] 2.7 Get 1.1–1.4 green.
- [ ] 3.1 Add a config loader that merges `machine_geometry.json` under `machine_config.json`. Config may narrow CAD travel limits but never widen them; a null CAD limit requires an explicit conservative, provenance-labeled config fallback. Blade dims are not overridable.
- [ ] 3.2 Update `machine_config.json`: remove the cone keys; add `heated_length_mm`, `broadside_threshold_deg` and `finish_phi_search_step_deg`; set `v_max.theta_rad_s` ≤ 1.0; stock R/H stay configurable and are marked unverified.
- [ ] 3.3 Update `kinematics.py`: orbit-θ datum docs; signed r; h to the pivot (h2 = 0); |r_s| singularity check; signed-r IK branch selection with θ-limit feasibility and minimum |Δθ|; φ policy projected into the chosen solution's frame.
- [ ] 3.4 Get the 1.6 kinematics tests green.
- [ ] 4.1 Implement `tool_model.py`: frame, `heated_sdf`, `place_on_contact` (support function with centroid tie-break), `body_penetrates` (shaft/body/head ring sampling, explicit sign handling), and `feed_class`.
- [ ] 4.2 Generate `tests/fixtures/heated_sdf_parity.json` from `tool_model.py` (seeded).
- [ ] 4.3 Get 1.5 green.
- [ ] 5.1 Update `toolpath_sim.py` roughing: CL placement against the shadow via `place_on_contact`; θ-direction ring passes with radial stepovers only; classify segments with `feed_class` and emit `BLADE_BROADSIDE_FEED`.
- [ ] 5.2 Update finishing: φ_ideal from the IK policy; `place_on_contact`; `body_penetrates` search over φ candidates ordered by distance from φ_ideal, with early exit; `UNREACHABLE_UNDERCUT_AREA` / `GOUGE`; remove the closed-form cone bound and all cone-key reads; replace the MVP cone helpers (`finishing_phi`'s α term, `cutter_location`'s `ρ + kerf` offset, `tool_body_penetrates`'s cone stations, `entry_moves`/`exit_moves` clearance) with `tool_model` calls, migrating `TestFinishingHelpers` fixtures that encode the cone or `p = 30` (each listed in `patch.md`); remove `@unittest.expectedFailure` from `test_finishing_follows_planar_contours` and get it passing (the 0.1 exit criterion).
- [ ] 5.3 Update the sampling bound to 0.5·(blade_thickness + 2·kerf) over heated-region corner points, and make rapid retract clearance include the tool's radial support extent.
- [ ] 5.4 Update `server.py`: `tool_cfg` whitelist (`melt_kerf_mm`, `heated_length_mm` ≤ blade length); 422 naming removed cone keys; `config.geometry_provenance` in the response.
- [ ] 5.5 Get 1.7 green, including the performance guard.
- [ ] 6.1 Update `static/wax_sdf_core.js` and `wax_worker.js`: blade inflated-box SDF stamp, with the tool frame from `theta_s` + `tool_axis_wax`; constants from the config payload; per-body shank checks (shaft, body, head) reporting the body name.
- [ ] 6.2 Implement `static/cad_rig.js` `CadCarverRig`: GLTFLoader at the app's pinned Three version; `static ⊃ orbit ⊃ z ⊃ radial ⊃ tilt`; deltas from `cad_reference_pose`; pre-baked tilt pivot; ghosted `unassigned`, hidden `stock_placeholder`; tip marker; load-failure fallback.
- [ ] 6.3 Wire `static/app.js`: replace `PrimitiveCarverRig` and delete `static/machine_rig.js`; wax parented to `static`; machine-detail toggle (Tool-only default under 900px); unassigned-parts note; provenance readout; `BLADE_BROADSIDE_FEED` warning badge. Use the `scene.*` tokens from `design.md`.
- [ ] 6.4 Get 1.8 green.
- [ ] 7.1 Present `cad_part_roles.json` plus a joint-sweep recording for owner sign-off. Apply corrections by regenerating artifacts, not by hand-editing the JSON.
- [ ] 7.2 Ask the owner about the pivot axis (servo horn vs `Dowel_3x37`) and the cylinder stock R/H. Record the answers in research.md (move from Unverified to Verified facts), and regenerate or retune if needed.
- [ ] 7.3 Leave `home_pose`, `Cold_Tool_6mm_Shank` and `heated_length_mm` as recorded open items unless the owner supplies them.
- [ ] 8.1 Run the full regression suite: `.venv/bin/python -m unittest discover -s tests`, `node --test tests/`, and `.venv-cad/bin/python -m unittest tests.test_machine_cad_extract`. Verify clean passes and record pass/skip counts. Check `demo`/`standard` frame counts and toolpath-generation wall time against the 0.3 baseline (`98ac91d`) using equivalent enabled stages and inputs.
- [ ] 8.2 Populate `verification.md`: Requirement Adherence Matrix (every requirement and scenario in all five spec files → test name → result); resolved and remaining assumptions (pivot, heated length, stock, home pose, cold tool); `machine_geometry.json` SHA and `step_sha256`; verbatim execution logs.

> **Owner gates (7.1, 7.2):** you cannot get answers from the owner headlessly. Produce the artifacts (roles file, joint-sweep recording, the questions), leave 7.1/7.2 unticked, list the questions verbatim at the top of your final report, and continue with everything else. Do not block the PR on them.

## 7. Post-Implementation & Verification Obligations
When `spec-coder-sub` finishes:
1. Verify all checkboxes in `tasks.md` are marked `- [x]`. Only tick boxes that genuinely ran and passed. 7.1 and 7.2 stay unticked pending the owner. Say so explicitly.
2. Check data preservation: per-link occurrence counts sum to 295. `unassigned_parts` and `stock_placeholder_parts` are listed by name. `demo`/`standard` frame counts and wall time are compared against the 0.3 baseline.
3. Ensure `openspec/changes/machine-cad-integration/verification.md` is populated with:
   - Executive Summary & Environment
   - Requirement Adherence Audit Matrix (mapping every spec scenario to its verifying test)
   - Resolved Assumptions & Empirical Proof
   - Nomenclature & Code Symbol Audit (grep proof that no `tip_radius_mm`, `cone_half_angle_deg`, `engaged_length_mm`, `tip_width_mm`, `shank_radius_mm`, `shank_length_mm`, `PrimitiveCarverRig` or `machine_rig` references remain outside `patch.md`/archived docs. "apex" survives only in historical text.)
   - Verbatim Execution Logs
4. Automatically run verification via `openspec-verify-change`.
5. If clean with no critical issues, sync specs: `openspec specs apply --change "machine-cad-integration"`.
6. **Open a Pull Request**: Once implementation is complete and `openspec/changes/machine-cad-integration/verification.md` is written and verified with zero critical issues:
   - Ensure your work is on a dedicated feature branch (create/switch to `feat/machine-cad-integration` if currently on `main`/`master`).
   - Stage and commit all implementation code and every artifact within the change directory (`git add openspec/changes/machine-cad-integration openspec/specs <implementation-files>`), then push the branch (`git push -u origin HEAD`).
   - Open a Pull Request using `gh pr create --fill` (or with a concise title and a body summarizing `proposal.md` and `verification.md`, including the open owner questions) and report the PR URL.
