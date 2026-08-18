/**
 * Browser feature detection for the selection sentinel workaround.
 *
 * PDF.js only moves the sentinel on legacy Chromium; Firefox and modern
 * Chromium (>= 148) handle dead-zone expansion natively and the moving
 * sentinel would be wasted work. The commit controller still reads exact text
 * and geometry from the browser Range regardless of this check.
 */

type NavigatorWithUAData = Navigator & {
  userAgentData?: {
    brands: Array<{ brand: string; version: string }>;
  };
};

let cached: boolean | undefined;

export function isModernSelectionBrowser(): boolean {
  if (cached !== undefined) return cached;
  if (typeof navigator === "undefined" || typeof document === "undefined") {
    cached = true;
    return cached;
  }
  const probe = document.createElement("div");
  probe.style.userSelect = "none";
  const isFirefox =
    getComputedStyle(probe).getPropertyValue("-moz-user-select") === "none";
  if (isFirefox) {
    cached = true;
    return cached;
  }
  const nav = navigator as NavigatorWithUAData;
  const chromiumVersion = nav.userAgentData
    ? nav.userAgentData.brands.find((brand) => brand.brand === "Chromium")
        ?.version
    : /\bChrome\/(\d+)\b/.exec(navigator.userAgent)?.[1];
  const version = chromiumVersion ? Number.parseInt(chromiumVersion, 10) : NaN;
  cached = Number.isFinite(version) && version >= 148;
  return cached;
}
