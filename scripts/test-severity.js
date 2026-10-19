// Minimal Node test runner for frontend/public/severity.js — no framework,
// run with: node scripts/test-severity.js
'use strict';

const assert = require('assert');
const { hasDielineHints, bleedSeverity, rgbSeverity, caliperRecommendation, summaryStatusKey } = require('../frontend/public/severity.js');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

// --- Bleed severity ---

test('missing TrimBox, no manual size -> warning (not critical)', () => {
  assert.strictEqual(bleedSeverity({ has_bleed: false, bleed_warning: false }), 'warning');
});

test('missing TrimBox, manual size declared -> still warning', () => {
  assert.strictEqual(bleedSeverity({ has_bleed: false, bleed_warning: true }), 'warning');
});

test('TrimBox present, actual bleed below threshold -> critical (confirmed)', () => {
  assert.strictEqual(bleedSeverity({ has_bleed: true, bleed_warning: true }), 'critical');
});

test('TrimBox present, bleed sufficient -> ok', () => {
  assert.strictEqual(bleedSeverity({ has_bleed: true, bleed_warning: false }), 'ok');
});

// --- Dieline override ---

test('no dieline hints -> bleed check applies as usual', () => {
  assert.strictEqual(hasDielineHints({ dieline_hints: [] }), false);
  assert.strictEqual(hasDielineHints({}), false);
});

test('dieline hints found -> rectangular bleed check should be skipped', () => {
  assert.strictEqual(hasDielineHints({ dieline_hints: [{ category: 'cut', names: ['CutLine'], count: 1 }] }), true);
});

// --- RGB severity ---

test('RGB images found -> warning (was info)', () => {
  assert.strictEqual(
    rgbSeverity([{ rgb_warning: true }, { rgb_warning: false }]),
    'warning'
  );
});

test('no RGB images -> ok', () => {
  assert.strictEqual(
    rgbSeverity([{ rgb_warning: false }, { rgb_warning: false }]),
    'ok'
  );
});

// --- Caliper recommendation (category ranges, not a linear formula) ---

test('caliper 0.34mm -> 10-12mm flap (below 0.35 boundary)', () => {
  assert.deepStrictEqual(
    caliperRecommendation(0.34),
    { flapLow: 10, flapHigh: 12, creaseMin: 4 }
  );
});

test('caliper 0.35mm -> 12-15mm flap (at 0.35 boundary)', () => {
  const r = caliperRecommendation(0.35);
  assert.strictEqual(r.flapLow, 12);
  assert.strictEqual(r.flapHigh, 15);
});

test('caliper 0.59mm -> 12-15mm flap (below 0.6 boundary)', () => {
  const r = caliperRecommendation(0.59);
  assert.strictEqual(r.flapLow, 12);
  assert.strictEqual(r.flapHigh, 15);
});

test('caliper 0.6mm -> 15-20mm flap (at 0.6 boundary)', () => {
  const r = caliperRecommendation(0.6);
  assert.strictEqual(r.flapLow, 15);
  assert.strictEqual(r.flapHigh, 20);
});

test('caliper 0.99mm -> 15-20mm flap (below 1.0 boundary)', () => {
  const r = caliperRecommendation(0.99);
  assert.strictEqual(r.flapLow, 15);
  assert.strictEqual(r.flapHigh, 20);
});

test('caliper 1.0mm -> 20-25mm flap (at 1.0 boundary)', () => {
  const r = caliperRecommendation(1.0);
  assert.strictEqual(r.flapLow, 20);
  assert.strictEqual(r.flapHigh, 25);
});

test('crease spacing is >= 3x caliper, no artificial upper multiplier', () => {
  assert.strictEqual(caliperRecommendation(2).creaseMin, 6);
});

test('crease spacing floors at 4mm for very thin board', () => {
  assert.strictEqual(caliperRecommendation(0.3).creaseMin, 4);
});

// --- Summary status key (drives both the badge and the plain-language
// summary sentence, so both must always agree) ---

test('0 critical, 0 warning -> ready', () => {
  assert.strictEqual(summaryStatusKey({ critical: 0, warning: 0, info: 2, ok: 5 }), 'ready');
});

test('0 critical, N warning -> manual', () => {
  assert.strictEqual(summaryStatusKey({ critical: 0, warning: 3, info: 1, ok: 4 }), 'manual');
});

test('N critical (regardless of warnings) -> critical', () => {
  assert.strictEqual(summaryStatusKey({ critical: 1, warning: 3, info: 0, ok: 4 }), 'critical');
  assert.strictEqual(summaryStatusKey({ critical: 2, warning: 0, info: 0, ok: 4 }), 'critical');
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests failed.');
}
