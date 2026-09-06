const assert = require('node:assert/strict');
const Pacer = require('../qml/web/onyx-frame-pacer-v1.js');
const p = new Pacer();
assert.equal(p.target(true, false), 60);
assert.equal(p.measuredFps, null);
assert.equal(p.due(0, true, false), true);
p.rendered(0, 2, false);
assert.equal(p.due(1, true, false, true), false);
for (let n = 1; n <= 60; n++) {
  assert.equal(p.due(n * 1000 / 60, true, false), true);
  p.rendered(n * 1000 / 60, 2, false);
}
assert.ok(Math.abs(p.measuredFps - 60) < 0.1);
for (let n = 0; n < 8; n++) p.rendered(p.last + 40, 30, false);
assert.equal(p.target(true, false), 30);
for (let n = 0; n < 180; n++) p.rendered(p.last + 1000 / 30, 2, false);
assert.equal(p.target(true, false), 60);
assert.equal(p.target(true, true), 12);
assert.equal(p.due(10000, false, false, true), false);
assert.equal(p.measuredFps, null);
assert.equal(p.due(NaN, true, false), false);
console.log('PASS: cap, pacing, measured FPS, downgrade, recovery, reduced motion, inactive');
