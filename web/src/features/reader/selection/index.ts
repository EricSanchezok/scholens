/**
 * Reader selection engine public API.
 *
 * Only the page surface and the commit controller import from here; the
 * modules stay private to the Reader feature slice.
 */

export {
  buildPageTextGeometryIndex,
  hitTestNearest,
  itemsForOffsets,
  mapDomBoundaryToOffset,
  rectsForOffsets,
  sliceText,
  type GeometryItem,
  type GeometryPoint,
  type GeometryRect,
  type PageTextGeometryIndex,
} from "./page-text-geometry";

export {
  clampDeadZoneEnd,
  columnStripItems,
  normalizeForComparison,
  normalizePdfSelection,
  verticalGapBetween,
  DEAD_ZONE_LINE_FACTOR,
  DEAD_ZONE_MIN_PX,
  OVERSHOOT_ABSOLUTE_PADDING,
  OVERSHOOT_LENGTH_FACTOR,
  type NormalizedSelection,
} from "./normalize-pdf-selection";

export {
  coalesceSelectionRects,
  normalizeReaderSelectionRects,
  type ClientRect,
  type NormalizedSelectionRect,
} from "./rect-normalization";

export {
  ensureEndOfContent,
  installTextLayerSelectionGuard,
  isSelectingTextLayer,
  uninstallTextLayerSelectionGuard,
} from "./text-layer-selection-guard";

export { isModernSelectionBrowser } from "./selection-browser-support";

export {
  createSelectionCommitController,
  SELECTION_SETTLE_DELAY_MS,
} from "./selection-commit-controller";
