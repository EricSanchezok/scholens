export const READER_SELECTION_PAGE_ACK_TIMEOUT_MS = 1_000;

export type ReaderSelectionRouteDecision =
  "acknowledged" | "continue" | "defer";

export function createReaderSelectionPageCoordinator({
  onGuardChange,
  onReportPage,
  onSettleReport,
}: {
  onGuardChange: (guarded: boolean) => void;
  onReportPage: (pageNumber: number) => void;
  onSettleReport: (pageNumber: number, acknowledged: boolean) => void;
}) {
  let acknowledgementTimer: ReturnType<typeof setTimeout> | undefined;
  let awaitingPage: number | undefined;
  let disposed = false;
  let gestureRoutePage: number | undefined;
  let guarded = false;

  function clearAcknowledgementTimer() {
    if (acknowledgementTimer === undefined) return;
    clearTimeout(acknowledgementTimer);
    acknowledgementTimer = undefined;
  }

  function setGuarded(nextGuarded: boolean) {
    if (guarded === nextGuarded) return;
    guarded = nextGuarded;
    if (!disposed) onGuardChange(nextGuarded);
  }

  function settleReport(acknowledged: boolean) {
    const pageNumber = awaitingPage;
    if (pageNumber === undefined) return;
    clearAcknowledgementTimer();
    awaitingPage = undefined;
    gestureRoutePage = undefined;
    if (!disposed) onSettleReport(pageNumber, acknowledged);
    setGuarded(false);
  }

  return {
    dispose() {
      if (disposed) return;
      const pendingPage = awaitingPage;
      disposed = true;
      clearAcknowledgementTimer();
      awaitingPage = undefined;
      gestureRoutePage = undefined;
      guarded = false;
      if (pendingPage !== undefined) onSettleReport(pendingPage, false);
    },
    finishGesture(pendingPage: number | undefined) {
      if (disposed) return;
      if (pendingPage === undefined) {
        settleReport(false);
        gestureRoutePage = undefined;
        setGuarded(false);
        return;
      }
      if (awaitingPage !== undefined) settleReport(false);
      awaitingPage = pendingPage;
      acknowledgementTimer = setTimeout(() => {
        settleReport(false);
      }, READER_SELECTION_PAGE_ACK_TIMEOUT_MS);
      onReportPage(pendingPage);
    },
    isGuarded() {
      return guarded;
    },
    routePageChanged(pageNumber: number): ReaderSelectionRouteDecision {
      if (awaitingPage !== undefined) {
        if (pageNumber === awaitingPage) {
          settleReport(true);
          return "acknowledged";
        }
        if (pageNumber === gestureRoutePage) return "defer";
        settleReport(false);
        return "continue";
      }
      return guarded ? "defer" : "continue";
    },
    startGesture(routePage: number) {
      if (disposed) return;
      settleReport(false);
      gestureRoutePage = routePage;
      setGuarded(true);
    },
  };
}
