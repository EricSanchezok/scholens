export const motionInitializationScript = `
(() => {
  const root = document.documentElement;
  const cookies = Object.fromEntries(document.cookie.split("; ").filter(Boolean).map((entry) => {
    const separator = entry.indexOf("=");
    return separator < 0 ? [entry, ""] : [entry.slice(0, separator), entry.slice(separator + 1)];
  }));
  let storedCandidate;
  try {
    storedCandidate = localStorage.getItem("scholens-motion");
  } catch {}
  const candidate = storedCandidate || cookies["scholens-motion"];
  const preference = ["system", "reduced", "full"].includes(candidate) ? candidate : "system";
  const reduced = preference === "reduced" || (
    preference === "system" && matchMedia("(prefers-reduced-motion: reduce)").matches
  );
  root.dataset.motionPreference = preference;
  root.dataset.motion = reduced ? "reduced" : "full";
})();`;
