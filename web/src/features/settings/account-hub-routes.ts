export const accountHubPaths = {
  home: "/me",
  account: "/me/account",
  usage: "/me/usage",
  settings: "/me/settings",
  display: "/me/settings/display",
  translation: "/me/settings/translation",
  connections: "/me/connections",
  accessKeys: "/me/access-keys",
} as const;

export type AccountHubView = keyof typeof accountHubPaths;

export type MobileSettingsSection =
  | "account"
  | "general"
  | "usage"
  | "access-keys"
  | "connections"
  | "translation";

export const mobileSettingsPaths: Record<
  MobileSettingsSection,
  (typeof accountHubPaths)[AccountHubView]
> = {
  account: accountHubPaths.account,
  general: accountHubPaths.display,
  usage: accountHubPaths.usage,
  "access-keys": accountHubPaths.accessKeys,
  connections: accountHubPaths.connections,
  translation: accountHubPaths.translation,
};

const accountHubParents: Record<AccountHubView, string> = {
  home: "/",
  account: accountHubPaths.home,
  usage: accountHubPaths.home,
  settings: accountHubPaths.home,
  display: accountHubPaths.settings,
  translation: accountHubPaths.settings,
  connections: accountHubPaths.home,
  accessKeys: accountHubPaths.home,
};

const desktopSettingsSections: Record<AccountHubView, MobileSettingsSection> = {
  home: "account",
  account: "account",
  usage: "usage",
  settings: "general",
  display: "general",
  translation: "translation",
  connections: "connections",
  accessKeys: "access-keys",
};

const oauthCallbackKeys = ["zotero", "zotero_intent", "zotero_import"];

export function normalizeInternalReturnTo(value: string | null | undefined) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return undefined;
  }
  try {
    const parsed = new URL(value, "https://scholens.local");
    if (parsed.origin !== "https://scholens.local") return undefined;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return undefined;
  }
}

export function accountHubBackHref(
  view: AccountHubView,
  returnTo?: string | null,
) {
  return normalizeInternalReturnTo(returnTo) ?? accountHubParents[view];
}

export function desktopSettingsHref(view: AccountHubView) {
  return `/?settings=${desktopSettingsSections[view]}`;
}

export function mobileSettingsHref(
  section: MobileSettingsSection,
  options: {
    returnTo?: string;
    callbackParams?: URLSearchParams;
  } = {},
) {
  const params = new URLSearchParams();
  const returnTo = normalizeInternalReturnTo(options.returnTo);
  if (returnTo) params.set("returnTo", returnTo);
  if (options.callbackParams) {
    for (const key of oauthCallbackKeys) {
      for (const value of options.callbackParams.getAll(key)) {
        params.append(key, value);
      }
    }
  }
  const query = params.toString();
  return `${mobileSettingsPaths[section]}${query ? `?${query}` : ""}`;
}

export function mobileSettingsRedirectHref(
  section: MobileSettingsSection,
  pathname: string,
  searchParams: URLSearchParams,
) {
  const returnParams = new URLSearchParams(searchParams.toString());
  returnParams.delete("settings");
  for (const key of oauthCallbackKeys) returnParams.delete(key);
  const returnQuery = returnParams.toString();
  const returnTo = `${pathname}${returnQuery ? `?${returnQuery}` : ""}`;
  return mobileSettingsHref(section, {
    callbackParams: searchParams,
    returnTo,
  });
}
