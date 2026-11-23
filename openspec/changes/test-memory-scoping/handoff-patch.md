# Surgical Patch Handoff: OpenSpec Change 'test-memory-scoping' [PATCH-02]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `test-memory-scoping`
- **Patch ID**: `PATCH-02`
- **Objective**: Fix `is_real_target` in `tests/test_carver_sim.py` to match `(len(vertices), extents[2])` with a 3-mesh self-test, move `scripts/probe_phase.py` back to `tests/_phase_probe.py` under `scripts/safe-test.sh`, label the historical `2048` probe command in `patch.md` as exploratory/do-not-rerun, and document Task 4.3's deferral to `toolpath-memory` in `verification.md` (unless `>= 9,216 MiB` is available).
- **Feedback & Diagnostic Trace**:
  ```
  PR #5 Verdict: REQUEST CHANGES (b7979d24)
  1. tests/test_carver_sim.py:782-787 (is_real_target): comparing full mesh.bounds with atol=1.0
     returns False on sculpted base_head (max-x shifts 5.6 mm on nose=1.0, chin=0.6, brow=0.4).
  2. scripts/probe_phase.py:8-14: moving probe out of tests/ led to a raw ulimit docstring
     that bypasses flock and the memory floor.
  3. patch.md:8-11: still shows historical tests/_phase_probe.py + SAFE_TEST_MIN_AVAIL_MB=2048
     command without labelling it as historical/do-not-rerun.
  4. tasks.md:32 (Task 4.3): blocked at 4,889 MiB vs 9,216 MiB floor; document formal deferral
     to toolpath-memory in verification.md (or run 4.3 if >= 9,216 MiB is available).
  ```
- **Root Cause Analysis**:
  - `is_real_target` used 3D bounding-box equality (`atol=1.0`), which breaks when facial sliders displace vertices radially/laterally.
  - `scripts/probe_phase.py` was moved outside `tests/`, which `scripts/safe-test.sh` requires for target paths.

## 2. Strict Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `tests/test_carver_sim.py` | `L773-L818` | Update `real` to store `(len(mesh.vertices), float(mesh.extents[2]))`, update `is_real_target(mesh)` to check `len(mesh.vertices) == count and abs(float(mesh.extents[2]) - expected_h) < 0.1 * expected_h`, and add explicit self-test assertions for `is_real_target(sculpted_base_head) is True`, `is_real_target(head_2) is True`, and `is_real_target(short_stock_target) is False`. |
| `scripts/probe_phase.py` $\to$ `tests/_phase_probe.py` | `[MOVE]`, `L1-L30` | Move `scripts/probe_phase.py` back to `tests/_phase_probe.py` (update `ROOT = Path(__file__).resolve().parents[1]`, keep `RUN_PHASE_PROBE=1` gate), and restore `RUN_PHASE_PROBE=1 SAFE_TEST_AS_KB=6291456 scripts/safe-test.sh tests/_phase_probe.py` in its docstring. |
| `openspec/changes/test-memory-scoping/patch.md` | `L5-L15` & `PATCH-02` | Label the `SAFE_TEST_MIN_AVAIL_MB=2048` snippet in section `2.1` as a **historical/exploratory** command (do not rerun; superseded by cap-coupled floor), and mark `PATCH-02` `VERIFIED` after suites pass. |
| `openspec/changes/test-memory-scoping/verification.md` | `L27-L48` | Document Task 4.3's formal deferral to the `toolpath-memory` follow-up change (which lowers `build_finishing`'s ~3.3 GB transient so the heavy cap/floor fits the shared 12 GiB container) unless `>= 9,216 MiB` is available to run 4.3 cleanly. |

## 3. Blast Radius & Invariant Guardrails
- **STRICT BLAST RADIUS**: Modify ONLY the files and line ranges specified in the Target Context Map.
- **FORBIDDEN**:
  - Do NOT modify any production code (`toolpath_sim.py`, `kinematics.py`, `face_sculpt.py`, `server.py`, `tool_model.py`, `static/*`).
  - Do NOT modify `scripts/safe-test.sh` or `AGENTS.md`.
  - Do NOT lower `SAFE_TEST_MIN_AVAIL_MB` below `9216`.
  - Do NOT modify `.env` or credential files.

## 4. Visual & UI Impact
- Status: Non-visual patch. No CSS, HTML, or `DESIGN.md` token modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce First**:
   - Add the 3-mesh `is_real_target` self-test in `tests/test_carver_sim.py` (`TestTiers`), run `scripts/safe-test.sh tests/test_carver_sim.py`, and confirm `is_real_target(sculpted_base_head)` fails (`False != True`).
2. **Apply Minimal Fixes**:
   - Update `is_real_target` to `(len(vertices), extents[2])` in `tests/test_carver_sim.py`.
   - Move `scripts/probe_phase.py` back to `tests/_phase_probe.py` with the `scripts/safe-test.sh` docstring.
   - Update `patch.md` and `verification.md`.
3. **Full Regression Suite**:
   - Run `scripts/safe-test.sh` (default tier, no args) — confirm `peak_rss_mb <= 1536`, `wall_s <= 600`, exit `0`.
   - Run `scripts/safe-test.sh --node` — confirm `32 pass / 0 fail / 1 skip`.
   - Run `openspec validate test-memory-scoping --strict --json` — confirm `valid: true`.

## 6. Surgical Patch Checklist
- [ ] P02.1 Add 3-mesh `is_real_target` self-test in `tests/test_carver_sim.py` (`TestTiers`) and confirm failure on sculpted `base_head`.
- [ ] P02.2 Update `is_real_target` to `(len(vertices), extents[2])` within `10%`, and move `scripts/probe_phase.py` $\to$ `tests/_phase_probe.py` with `scripts/safe-test.sh` docstring.
- [ ] P02.3 Label historical `2048` command in `patch.md` and document Task 4.3 deferral to `toolpath-memory` in `verification.md` (or run 4.3 if `>= 9,216 MiB` available).
- [ ] P02.4 Run `scripts/safe-test.sh`, `scripts/safe-test.sh --node`, and `openspec validate test-memory-scoping --strict --json`; update `tasks.md` (`P02.1–P02.4`) and mark `PATCH-02` `VERIFIED` in `patch.md`.
