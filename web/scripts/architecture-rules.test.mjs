import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { hasInvalidManualSvg } from "./architecture-rules.mjs";

describe("semantic SVG architecture rule", () => {
  it("accepts a named data visualization", () => {
    assert.equal(
      hasInvalidManualSvg(
        '<svg data-visualization="trend" role="img" aria-label={label}>',
      ),
      false,
    );
    assert.equal(
      hasInvalidManualSvg(
        '<svg data-visualization="map" role="img" aria-labelledby="map-title">',
      ),
      false,
    );
  });

  it("rejects unmarked SVG, missing semantics, and imperative SVG", () => {
    assert.equal(
      hasInvalidManualSvg('<svg role="img" aria-label="Icon">'),
      true,
    );
    assert.equal(
      hasInvalidManualSvg(
        '<svg data-visualization="trend" aria-label="Trend">',
      ),
      true,
    );
    assert.equal(
      hasInvalidManualSvg('<svg data-visualization="trend" role="img">'),
      true,
    );
    assert.equal(hasInvalidManualSvg('createElement("svg")'), true);
  });
});
