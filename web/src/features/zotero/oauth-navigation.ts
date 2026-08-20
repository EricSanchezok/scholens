import { isStandaloneDisplayMode } from "@/lib/browser/display-mode";

export const zoteroOAuthPendingKey = "scholens:zotero-oauth-pending:v1";

type AuthorizationWindow = Pick<Window, "close" | "location">;

function writePending(value: boolean) {
  try {
    if (value) window.sessionStorage.setItem(zoteroOAuthPendingKey, "1");
    else window.sessionStorage.removeItem(zoteroOAuthPendingKey);
  } catch {
    // OAuth still works when a WebView denies session storage.
  }
}

export function hasPendingZoteroAuthorization() {
  try {
    return window.sessionStorage.getItem(zoteroOAuthPendingKey) === "1";
  } catch {
    return false;
  }
}

export function clearPendingZoteroAuthorization() {
  writePending(false);
}

export function prepareZoteroAuthorizationWindow({
  openWindow = () => window.open("about:blank", "_blank"),
  standalone = isStandaloneDisplayMode(),
}: {
  openWindow?: () => Window | null;
  standalone?: boolean;
} = {}) {
  if (!standalone) return undefined;
  const authorizationWindow = openWindow();
  if (authorizationWindow) authorizationWindow.opener = null;
  return authorizationWindow;
}

export function continueZoteroAuthorization(
  authUrl: string,
  authorizationWindow: AuthorizationWindow | null | undefined,
  assign = (url: string) => window.location.assign(url),
) {
  if (authorizationWindow) {
    writePending(true);
    authorizationWindow.location.href = authUrl;
    return "external" as const;
  }
  assign(authUrl);
  return "current" as const;
}

export function cancelPreparedZoteroAuthorization(
  authorizationWindow: AuthorizationWindow | null | undefined,
) {
  authorizationWindow?.close();
}
