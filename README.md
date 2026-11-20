# Carving Simulation — 4-DOF Thermal CNC Wax Carver Digital Twin

Interactive 3D kinematic, facial-sculpting, and volumetric material-removal simulator for a custom **4-DOF Cylindrical Thermal CNC Wax Carver**. The machine is modelled from the owner's Fusion export (`assets/Wax+Face+Carver+v2.stp`): a static wax stock, an orbiting ring that carries the column, a Z carriage, a signed radial carriage, and a wrist-pitch joint with a heated rectangular blade (1.2 x 6.0 x 14.0 mm).

## Architecture

- **Backend (`Python` / `FastAPI`)**
  - `machine_geometry.json`: CAD-derived constants, travel evidence, tool geometry, link roles and provenance. Generated, never hand-edited.
  - `machine_config.json`: feeds, stock, presets and limits. It may narrow CAD travel but never widen it; unknown CAD travel fails closed unless an explicitly labelled fallback is configured.
  - `kinematics.py`: single-source-of-truth 4-DOF forward/inverse kinematics (orbit `theta`, signed `r` to the pivot, `h` to the pivot, `phi`) and singularity/limit diagnostics.
  - `tool_model.py`: the only runtime definition of the blade tool frame, heated-region SDF, support-function CC->CL placement, collision bodies and feed classification.
  - `face_sculpt.py`: smooth `scipy.spatial.cKDTree` RBF/Gaussian facial modifications on a base head mesh inside cylindrical wax stock bounds.
  - `toolpath_sim.py`: synthetic 4-DOF roughing + undercut-capable finishing trajectory generator sampled by heated-blade swept distance.
- **Frontend (`Three.js`)**
  - `CadCarverRig` loads `static/models/{static,orbit,z,radial,tilt,unassigned}.glb` and applies joint deltas without kinematic trigonometry.
  - `VolumetricWaxGrid` (chunked 3D SDF + Marching Cubes) supporting `phi`-axis undercuts, blade-box subtraction and current-stock rapid/shank collision checks.

## Setup

Runtime and tests (about 250 MB):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
npm install
```

CAD extraction (dev-only, needs network for about 100 MB of OCP wheels). The
server and the runtime tests never import OCP or read the STEP:

```bash
python3 -m venv .venv-cad
.venv-cad/bin/pip install -r requirements-cad.txt
```

Regenerate the committed CAD artifacts after a STEP revision:

```bash
.venv-cad/bin/python scripts/extract_machine.py
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs tests/test_cad_rig.mjs
.venv-cad/bin/python -m unittest tests.test_machine_cad_extract -v
```

See [`HANDOFF.md`](HANDOFF.md) for the original architectural specification.
