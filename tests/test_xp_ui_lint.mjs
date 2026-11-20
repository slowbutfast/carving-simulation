/**
 * Static lint tests for the XP Luna studio shell.
 *
 * These read the shipped sources directly with `node:fs` and pin the structure
 * promised by the `xp-studio-ui` spec: the 6-layer window chrome, the transport
 * dock, exactly five status cells, the /vendor three.js import map, the
 * `+Y`-up zero-trig rig wiring, Google DESIGN.md structure, and a strict
 * no-emoji guard over HTML, CSS and JS.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), 'utf8');

const hasClass = (source, name) =>
  new RegExp(`class="[^"]*\\b${name}\\b[^"]*"`).test(source);

// Emoji and dingbat ranges only.  Typographic punctuation (em dash, middle dot,
// multiplication sign, ellipsis, degree, greater-or-equal) is allowed.
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;

test('index.html renders the 6-layer XP window shell', () => {
  const html = read('static/index.html');

  assert.match(html, /class="desktop"/);
  assert.match(html, /id="studio-window"/);
  assert.ok(hasClass(html, 'titlebar'), 'titlebar class');
  assert.ok(hasClass(html, 'menu-bar'), 'menu-bar class');
  assert.ok(hasClass(html, 'mobile-tabs'), 'mobile-tabs class');
  assert.match(html, /inset-well viewport-well/);
  assert.ok(hasClass(html, 'transport-dock'), 'transport-dock class');
  assert.match(html, /<footer[^>]*class="status-bar"/);

  for (const id of [
    'simulate-button',
    'help-dialog',
    'sim-scrubber',
    'sim-time',
    'sim-speed',
    'preset-select',
    'file-input',
    'model-note',
    'machineDetailBtn',
    'unassigned-note',
  ]) {
    assert.ok(html.includes(`id="${id}"`), `index.html must contain id="${id}"`);
  }

  assert.ok(html.includes('4-DOF Wax Carver Studio 2001'));
  assert.ok(html.includes('/vendor/build/three.module.js'));
});

test('status bar exposes exactly five status cells', () => {
  const html = read('static/index.html');
  for (const id of [
    'status-text',
    'status-joints',
    'status-tip',
    'status-feed',
    'status-state',
  ]) {
    assert.ok(html.includes(`id="${id}"`), `index.html must contain id="${id}"`);
  }
  const cells = html.match(/class="status-cell/g) || [];
  assert.equal(cells.length, 5, `expected 5 status cells, found ${cells.length}`);
});

test('xp.css defines XP chrome, transport dock and 3D material tokens', () => {
  const css = read('static/xp.css');
  for (const selector of [
    '.desktop',
    '.window',
    '.titlebar',
    '.menu-bar',
    '.mobile-tabs',
    '.inset-well',
    '.viewport-well',
    '.transport-dock',
    '.transport-btn',
    '.transport-scrubber',
    '.transport-time',
    '.transport-speed',
    '.status-bar',
    '.status-cell',
    '.status-badge-collision',
  ]) {
    assert.ok(css.includes(selector), `xp.css must define ${selector}`);
  }

  assert.match(css, /--wax-stock\s*:\s*#e8d595/);
  assert.match(css, /--target-face-ghost\s*:\s*#3b82f6/);
  assert.match(css, /--rig-metal\s*:\s*#64748b/);
  assert.match(css, /--cutter-hot\s*:\s*#f97316/);
});

test('app.js wires ResizeObserver, the CAD rig, gallery scene and simulation API', () => {
  const app = read('static/app.js');
  for (const needle of [
    'ResizeObserver',
    'CadCarverRig',
    'RoomEnvironment',
    '0xf0ede0',
    'camera.up.set(0, 1, 0)',
    'sim-scrubber',
    'Machine Detail',
    'Provenance',
    'Unassigned',
  ]) {
    assert.ok(app.includes(needle), `app.js must contain ${needle}`);
  }
  assert.ok(app.includes('/api/sculpt-and-sim'), 'app.js must POST to /api/sculpt-and-sim');
  assert.ok(/\bPOST\b/.test(app), 'app.js must use POST');

  assert.ok(!app.includes('camera.up.set(0, 0, 1)'), 'app.js must not flip the up axis');
  assert.ok(!app.includes('Math.sin'), 'app.js must contain zero Math.sin');
  assert.ok(!app.includes('Math.cos'), 'app.js must contain zero Math.cos');
});

test('cad_rig.js keeps +Y up and zero JavaScript trig', () => {
  const rig = read('static/cad_rig.js');
  assert.ok(!rig.includes('Math.sin'));
  assert.ok(!rig.includes('Math.cos'));
  assert.ok(!rig.includes('camera.up.set(0, 0, 1)'));
});

test('UI sources are free of Unicode emoji', () => {
  for (const relative of [
    'static/index.html',
    'static/xp.css',
    'static/app.js',
  ]) {
    const source = read(relative);
    const match = source.match(EMOJI);
    assert.equal(
      match,
      null,
      `${relative} contains emoji ${match ? JSON.stringify(match[0]) : ''}`
    );
  }
});

test('DESIGN.md has YAML front matter and the ordered design sections', () => {
  const design = read('DESIGN.md');
  const lines = design.split(/\r?\n/);

  assert.equal(lines[0].trim(), '---', 'DESIGN.md must start with YAML front matter');
  const closing = lines.findIndex((line, index) => index > 0 && line.trim() === '---');
  assert.ok(closing > 0, 'DESIGN.md front matter must close with ---');

  const frontMatter = lines.slice(0, closing + 1).join('\n');
  assert.match(frontMatter, /\{colors\./, 'component tokens must reference {colors.*}');

  const headings = [...design.matchAll(/^## (.+)$/gm)].map((match) => match[1].trim());
  assert.deepEqual(headings, [
    'Overview',
    'Colors',
    'Typography',
    'Layout',
    'Elevation & Depth',
    'Shapes',
    'Components',
    "Do's and Don'ts",
  ]);
});
