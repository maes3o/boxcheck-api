// Pure, DOM-free severity/detection helpers shared by index.html and
// scripts/test-severity.js. Keep these free of DOM/browser globals so they
// stay testable under plain Node.

function hasDielineHints(d) {
  return (d.dieline_hints || []).length > 0;
}

function bleedSeverity(d) {
  // Critical only for a confirmed insufficient bleed: TrimBox/CropBox is
  // explicitly set apart from MediaBox and the actual bleed is below the
  // profile threshold. A missing TrimBox is insufficient data to confirm
  // anything, so it's a warning, not a critical, regardless of whether the
  // user declared a finished size manually.
  if (!d.has_bleed) return 'warning';
  if (d.bleed_warning) return 'critical';
  return 'ok';
}

function caliperRecommendation(caliper) {
  // Category ranges, not a linear formula: FEFCO/ECMA don't specify exact
  // mm for glue flap width (it depends on box style, glue, and equipment),
  // and a caliper*5 formula with a 20mm floor made every typical corrugated
  // caliper (0.3-1.5mm) collapse to the same identical-looking advice.
  let flapLow, flapHigh;
  if (caliper < 0.35) { flapLow = 10; flapHigh = 12; }
  else if (caliper < 0.6) { flapLow = 12; flapHigh = 15; }
  else if (caliper < 1.0) { flapLow = 15; flapHigh = 20; }
  else { flapLow = 20; flapHigh = 25; }
  // Common packaging-engineering rule of thumb: minimum spacing between
  // crease lines (and from a crease to the edge) is >= 3x board thickness.
  // 4mm floor kept as a practical minimum for very thin board.
  const creaseMin = Math.round(Math.max(4, caliper * 3) * 10) / 10;
  return { flapLow, flapHigh, creaseMin };
}

function rgbSeverity(imgs) {
  // Most print shops require CMYK/spot; any RGB image usually means rework
  // before print, so this is a warning (same level as low DPI), not info.
  const rgbBad = imgs.filter(i => i.rgb_warning);
  return rgbBad.length === 0 ? 'ok' : 'warning';
}

function summaryStatusKey(counts) {
  // Single source of truth for "what's the overall verdict", used both for
  // the colored status badge and the plain-language summary sentence, so
  // the two can never disagree about what the counts mean.
  if (counts.critical > 0) return 'critical';
  if (counts.warning > 0) return 'manual';
  return 'ready';
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { hasDielineHints, bleedSeverity, rgbSeverity, caliperRecommendation, summaryStatusKey };
}
