export function readSessionState<T>(key: string): T | undefined {
  try {
    const value = window.sessionStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : undefined;
  } catch {
    return undefined;
  }
}

export function writeSessionState(key: string, value: unknown) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function removeSessionState(key: string) {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // A denied storage write is non-fatal; local state remains usable.
  }
}
