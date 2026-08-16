export type ZoteroOAuthIntent = "manage" | "import";

const callbackKeys = ["zotero", "zotero_intent", "zotero_import"] as const;

export function buildZoteroReturnPath(
  pathname: string,
  search: string,
  intent: ZoteroOAuthIntent,
) {
  const params = new URLSearchParams(search);
  for (const key of callbackKeys) params.delete(key);
  if (intent === "import") params.set("zotero_import", "1");
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function clearZoteroCallbackParams(search: string) {
  const params = new URLSearchParams(search);
  for (const key of callbackKeys) params.delete(key);
  return params;
}

export function shouldOpenZoteroLibrary(search: string) {
  const params = new URLSearchParams(search);
  return (
    params.get("zotero") === "connected" &&
    (params.get("zotero_intent") === "import" ||
      params.get("zotero_import") === "1")
  );
}
