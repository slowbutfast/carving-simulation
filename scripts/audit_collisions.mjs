#!/usr/bin/env node
/**
 * Headless wax-SDF collision audit of a saved `POST /api/sculpt-and-sim` body.
 *
 * Usage:
 *   node scripts/audit_collisions.mjs <response_json_path> [--grid N]
 *
 * The response's base64 columnar trajectory is decoded into `{ tip, axis,
 * theta }` poses, then carved with the *same* `carveRange` the viewer's worker
 * uses, with `auditAll: true`: the loop does not stop at the first collision,
 * so the output lists every run of contiguous collisions with its frame range,
 * body, worst signed distance and tool pose.  `--grid` sets the voxel
 * resolution (default 128, i.e. the viewer's).
 *
 * Exits 2 on a missing file / undecodable body so it is usable from a pipeline.
 */

import fs from 'node:fs';
import path from 'node:path';

import { WaxSDFCore, carveRange, toolFromConfig } from '../static/wax_sdf_core.js';

const DEFAULT_GRID = 128;

function parseArgs(argv) {
  let responsePath = null;
  let grid = DEFAULT_GRID;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--grid') {
      const value = Number(argv[index + 1]);
      if (!Number.isFinite(value) || value < 8) {
        throw new Error('--grid needs an integer of at least 8');
      }
      grid = Math.floor(value);
      index += 1;
    } else if (argument.startsWith('--grid=')) {
      const value = Number(argument.slice('--grid='.length));
      if (!Number.isFinite(value) || value < 8) {
        throw new Error('--grid needs an integer of at least 8');
      }
      grid = Math.floor(value);
    } else if (responsePath === null && !argument.startsWith('-')) {
      responsePath = argument;
    } else {
      throw new Error(`unexpected argument ${argument}`);
    }
  }
  if (responsePath === null) {
    throw new Error('usage: node scripts/audit_collisions.mjs <response_json_path> [--grid N]');
  }
  return { responsePath, grid };
}

/** base64 -> typed array, copying out of Node's shared Buffer slab. */
function decodeColumn(column, Type) {
  const buffer = Buffer.from(column.b64, 'base64');
  const copy = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.length);
  return new Type(copy, 0, column.length);
}

function readTrajectory(trajectory) {
  const columns = trajectory.columns;
  const count = Number(trajectory.frame_count);
  const tip = decodeColumn(columns.tip_xyz_wax, Float32Array);
  const axis = decodeColumn(columns.tool_axis_wax, Float32Array);
  const theta = decodeColumn(columns.theta_s, Float32Array);
  const rapid = decodeColumn(columns.is_rapid, Uint8Array);
  const poses = new Array(count);
  for (let index = 0; index < count; index += 1) {
    poses[index] = {
      tip: [tip[index * 3], tip[index * 3 + 1], tip[index * 3 + 2]],
      axis: [axis[index * 3], axis[index * 3 + 1], axis[index * 3 + 2]],
      theta: theta[index],
    };
  }
  return { poses, rapid, count };
}

function audit(body, gridN) {
  const config = body.config;
  if (!config || !config.stock) {
    throw new Error('response has no config/stock: pass the body of a 200 response');
  }
  if (!body.trajectory || !body.trajectory.columns) {
    throw new Error('response has no trajectory to audit');
  }
  const { poses, rapid, count } = readTrajectory(body.trajectory);
  const tool = toolFromConfig(config.tool);
  const core = new WaxSDFCore({
    R_stock: config.stock.R_stock_mm ?? 40,
    H_stock: config.stock.H_stock_mm ?? 120,
    gridN,
    chunkSize: 16,
  });
  const result = carveRange(core, poses, rapid, tool, {
    from: 0,
    to: count - 1,
    auditAll: true,
  });
  return {
    gridN: core.N,
    voxelSize: core.voxelSize,
    frames: count,
    faulted: result.faulted,
    current: result.current,
    runs: result.runs,
  };
}

function main() {
  const { responsePath, grid } = parseArgs(process.argv.slice(2));
  const resolved = path.resolve(responsePath);
  let body;
  try {
    body = JSON.parse(fs.readFileSync(resolved, 'utf8'));
  } catch (error) {
    console.error(`cannot read ${resolved}: ${error.message}`);
    return 2;
  }
  let report;
  try {
    report = audit(body, grid);
  } catch (error) {
    console.error(`cannot audit ${resolved}: ${error.message}`);
    return 2;
  }
  console.log(JSON.stringify(report, null, 2));
  return 0;
}

process.exitCode = main();
