type NavigatorWithStandalone = Navigator & { standalone?: boolean };

function browserMatchMedia(query: string) {
  return typeof window.matchMedia === "function"
    ? window.matchMedia(query)
    : ({ matches: false } as MediaQueryList);
}

export function isStandaloneDisplayMode({
  matchMedia = browserMatchMedia,
  navigatorObject = window.navigator,
}: {
  matchMedia?: (query: string) => MediaQueryList;
  navigatorObject?: NavigatorWithStandalone;
} = {}) {
  return (
    matchMedia("(display-mode: standalone)").matches ||
    navigatorObject.standalone === true
  );
}
