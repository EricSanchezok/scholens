import { delay, http, HttpResponse } from "msw";

const apiUrl = "http://127.0.0.1:7301/api/v1/foundation-check";
const zoteroStatusUrl =
  "http://127.0.0.1:7301/api/v1/integrations/zotero/status";

export const foundationHandler = http.get(apiUrl, async ({ request }) => {
  const scenario = new URL(request.url).searchParams.get("scenario") ?? "";
  const network = scenario.startsWith("slow")
    ? "slow"
    : scenario.startsWith("offline")
      ? "offline"
      : "instant";
  const data = scenario.endsWith("empty")
    ? "empty"
    : scenario.endsWith("error")
      ? "error"
      : "populated";
  if (network === "offline") return HttpResponse.error();
  if (network === "slow") await delay(1800);
  if (data === "error")
    return HttpResponse.json({ message: "Server error" }, { status: 500 });
  return HttpResponse.json({
    items: data === "empty" ? [] : [{ id: "1", title: "Foundation item" }],
  });
});

export const zoteroStatusHandler = http.get(zoteroStatusUrl, () =>
  HttpResponse.json({
    active_operation_id: null,
    active_operation_kind: null,
    auto_import_enabled: false,
    auto_import_state: "off",
    automatic_annotation_sync: "off",
    automatic_sync_eligible: false,
    connected_at: null,
    connection_state: "disconnected",
    last_error_code: null,
    last_successful_sync_at: null,
  }),
);

export const successHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ items: [{ id: "1", title: "Foundation item" }] }),
  ),
];
export const slowHandlers = [
  http.get(apiUrl, async () => {
    await delay(1800);
    return HttpResponse.json({ items: [{ id: "1", title: "Delayed item" }] });
  }),
];
export const emptyHandlers = [
  http.get(apiUrl, () => HttpResponse.json({ items: [] })),
];
export const businessErrorHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json(
      { code: "LIMIT_REACHED", message: "The operation is not available." },
      { status: 409 },
    ),
  ),
];
export const serverErrorHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ message: "Server error" }, { status: 500 }),
  ),
];
export const unauthorizedHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ message: "Unauthorized" }, { status: 401 }),
  ),
];
export const offlineHandlers = [http.get(apiUrl, () => HttpResponse.error())];
