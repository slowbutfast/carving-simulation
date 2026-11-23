## MODIFIED Requirements

### Requirement: Simulation API endpoint and columnar payload contract
`server.py` SHALL expose `GET /api/health` and `POST /api/sculpt-and-sim` accepting `{ sliders, stock_cfg, tool_cfg, preset }` (`"demo"` or `"standard"`), returning the sculpted target mesh, the merged machine config (including the `machine_geometry.json` provenance block), diagnostics, and columnar base64-encoded `Float32Array` trajectory buffers capped at `max_frames` (default `250,000`). `tool_cfg` SHALL accept only `melt_kerf_mm` and `heated_length_mm` (≤ `blade_length_mm`). Blade dimensions are CAD-derived and not client-overridable. Removed cone keys (`tip_radius_mm`, `cone_half_angle_deg`, `engaged_length_mm`, `tip_width_mm`, `shank_radius_mm`, `shank_length_mm`) SHALL be rejected with HTTP 422 naming the key. Both `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs` SHALL acquire the shared per-process `_GEN_SEMAPHORE(1)` non-blockingly and return HTTP 429 if a generation is already active.

#### Scenario: Sculpt-and-sim endpoint returns valid columnar trajectory and diagnostics
- **WHEN** a client sends a valid `POST /api/sculpt-and-sim` request with `preset: "demo"`
- **THEN** the response returns HTTP 200 with decodable columnar frame buffers, target mesh geometry, structured diagnostics, and `config.geometry_provenance.step_sha256`

#### Scenario: Legacy cone tool keys are rejected
- **WHEN** a client sends `tool_cfg: { "cone_half_angle_deg": 30 }`
- **THEN** the response is HTTP 422 and the error names `cone_half_angle_deg`

#### Scenario: Concurrent sync request rejected with 429
- **WHEN** a client sends `POST /api/sculpt-and-sim` while `_GEN_SEMAPHORE` is held by another sync or async generation
- **THEN** the endpoint returns HTTP 429 immediately without blocking a FastAPI worker thread
