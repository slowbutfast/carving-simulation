/**
 * Unit tests for the pure upload helpers in `static/upload.js`.
 *
 * The module has no DOM or three.js dependency, so it runs directly under
 * `node --test`.  The server advertises its real limits through
 * `GET /api/health`; these tests pin the fallback and refusal behaviour.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_LIMITS,
  checkUploadAllowed,
  limitsFromHealth,
  uploadSubtitle,
} from '../static/upload.js';

test('limitsFromHealth reads server limits and lowercases formats', () => {
  const limits = limitsFromHealth({
    max_upload_bytes: 1234,
    accepted_formats: ['.STL', '.obj'],
  });
  assert.equal(limits.maxUploadBytes, 1234);
  assert.deepEqual(limits.acceptedFormats, ['.stl', '.obj']);
  assert.equal(limits.known, true);
});

test('limitsFromHealth falls back to defaults for invalid or absent fields', () => {
  const bodies = [
    undefined,
    null,
    {},
    { max_upload_bytes: 0 },
    { max_upload_bytes: 'nope' },
    { max_upload_bytes: -1, accepted_formats: [] },
    { accepted_formats: 'not-an-array' },
  ];
  for (const body of bodies) {
    const limits = limitsFromHealth(body);
    assert.equal(
      limits.maxUploadBytes,
      DEFAULT_LIMITS.maxUploadBytes,
      `fallback bytes for ${JSON.stringify(body)}`
    );
    assert.deepEqual(limits.acceptedFormats, [...DEFAULT_LIMITS.acceptedFormats]);
    assert.equal(limits.known, false);
  }
});

test('checkUploadAllowed permits an allowed format under the limit', () => {
  const refusal = checkUploadAllowed({ name: 'model.stl', size: 100 }, DEFAULT_LIMITS);
  assert.equal(refusal, null);
});

test('checkUploadAllowed rejects an unsupported format', () => {
  const refusal = checkUploadAllowed({ name: 'part.gcode', size: 100 }, DEFAULT_LIMITS);
  assert.ok(refusal, 'unsupported extension must be refused');
  assert.match(refusal, /unsupported format/);
});

test('checkUploadAllowed rejects a file over the advertised limit', () => {
  const refusal = checkUploadAllowed(
    { name: 'huge.stl', size: DEFAULT_LIMITS.maxUploadBytes + 1 },
    DEFAULT_LIMITS
  );
  assert.ok(refusal, 'oversized file must be refused');
  assert.match(refusal, /accepts up to/);
  assert.match(refusal, /MB/);
});

test('uploadSubtitle includes the size only when limits are known', () => {
  const known = uploadSubtitle({ ...DEFAULT_LIMITS, known: true });
  assert.match(known, /MB/);

  const unknown = uploadSubtitle({ ...DEFAULT_LIMITS, known: false });
  assert.doesNotMatch(unknown, /MB/);
  assert.match(unknown, /watertight only/);
});
