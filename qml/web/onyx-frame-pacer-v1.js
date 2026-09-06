/* Cyryx Labs — bounded adaptive scheduling; no geometry or material changes. */
(function (root) {
  'use strict';
  class OnyxFramePacer {
    constructor() {
      this.tiers = [24, 30, 60]; this.tier = 2;
      this.last = null; this.slow = 0; this.healthy = 0;
      this.frames = 0; this.windowStart = null; this.windowFrames = 0;
      this.measuredFps = null;
    }
    target(active, reduced) { return !active ? 0 : reduced ? 12 : this.tiers[this.tier]; }
    due(now, active, reduced, force = false) {
      if (!Number.isFinite(now)) return false;
      const fps = this.target(active, reduced);
      if (!fps) { this.last = null; this.windowStart = null; this.windowFrames = 0; this.measuredFps = null; return false; }
      // A state update must not bypass pacing: audio/pointer events may be frequent.
      return this.last === null || now - this.last >= 1000 / fps - 0.5;
    }
    rendered(now, cost, reduced) {
      const interval = this.last === null ? null : now - this.last;
      this.last = now; this.frames++;
      if (this.windowStart === null) { this.windowStart = now; this.windowFrames = 0; }
      else this.windowFrames++;
      if (now - this.windowStart >= 1000) {
        this.measuredFps = this.windowFrames * 1000 / (now - this.windowStart);
        this.windowStart = now; this.windowFrames = 0;
      }
      if (reduced || !Number.isFinite(cost) || cost < 0) return;
      const budget = 1000 / this.tiers[this.tier];
      if (cost > budget * 0.8 || (interval !== null && interval > budget * 1.8)) {
        this.healthy = 0;
        if (++this.slow >= 8) { this.tier = Math.max(0, this.tier - 1); this.slow = 0; }
      } else {
        this.slow = 0;
        // Recovery requires sustained cheap frames, not one lucky sample.
        if (cost < 6) {
          if (++this.healthy >= 180) { this.tier = Math.min(2, this.tier + 1); this.healthy = 0; }
        } else this.healthy = 0;
      }
    }
  }
  root.OnyxFramePacer = OnyxFramePacer;
  if (typeof module !== 'undefined' && module.exports) module.exports = OnyxFramePacer;
})(globalThis);
