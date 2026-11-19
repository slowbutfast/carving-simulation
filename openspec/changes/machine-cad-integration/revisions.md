### Revision: 2026-11-19 (post-merge precondition update)

- **Feedback Source**: The owner merged `carver-sim-mvp` as-is (PR #1 squash `98ac91d`) instead of via the PATCH-10 fallback.
- **Key Changes**:
  - `tasks.md`: 0.1 ticked and rewritten. The MVP merged *with* cone-based finishing and one `expectedFailure` (PATCH-10f). This change replaces that cone geometry, and removing the `expectedFailure` on `test_finishing_follows_planar_contours` is an exit criterion. 0.2 ticked (STEP committed, STL ignored). 0.3 baseline pinned to `98ac91d`. 5.2 gains cone-helper replacement and the `expectedFailure` removal.
  - `proposal.md` (Impact), `architecture.md` (Context, Risks, Migration step 1), `tests.md` (performance guard), `research.md` (Raised but not acted on): dropped the "finishing descoped" assumption.
  - `design.md`: `luna-ui-rework` references now point to `xp-ui-overhaul`, which absorbed it.
- **Validation**: `openspec validate machine-cad-integration --strict` passed.

### Revision: 2026-11-19 01:41 UTC

- **Feedback Source**: OpenSpec review of `machine-cad-integration`.
- **Key Changes**:
  - `research.md`, `architecture.md`, `specs/blade-tool-model/`: made the tool frame right-handed and consistent with its cross-product definition; clarified that blade thickness is an unoriented axis. Specified the tool-local origin and explicit serialized tilt-head envelope needed for matching Python and JS collision samples.
  - `specs/carver-kinematics/`: made the signed-r branch example explicitly synthetic, and required an explicit conservative configuration limit when a CAD travel limit is unknown.
  - `tests.md` and `specs/volumetric-wax-viewer/`: aligned frame and collision fixtures with those definitions; added coverage for unknown travel limits and scoped the performance comparison to equivalent post-fallback MVP stages/configurations.
  - `tasks.md` / `architecture.md`: specified the comparable baseline fields, explicit head-envelope extraction, and the fail-closed behavior for unknown orbit travel.
- **Validation**: `openspec validate machine-cad-integration --strict --json` passed.
