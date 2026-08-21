import { pwaColors } from "@/design-system/generated/theme-metadata";

const release = process.env.NEXT_PUBLIC_RELEASE_SHA ?? "development";

function serviceWorkerSource() {
  const offlineDocument = `<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Scholens · Offline</title>
<style>
  :root { color-scheme: light dark; font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: ${pwaColors.light.canvas}; color: ${pwaColors.light.textPrimary}; }
  body { box-sizing: border-box; display: grid; min-width: 320px; min-height: 100dvh; margin: 0; padding: max(24px, env(safe-area-inset-top)) max(20px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(20px, env(safe-area-inset-left)); place-items: center; }
  main { width: min(100%, 400px); }
  h1 { margin: 0; font-size: 28px; letter-spacing: -0.03em; }
  p { margin: 12px 0 0; color: ${pwaColors.light.textSecondary}; line-height: 1.7; }
  a { display: inline-flex; min-height: 44px; margin-top: 24px; align-items: center; color: inherit; font-weight: 600; }
  .zh { margin-top: 20px; padding-top: 20px; border-top: 1px solid ${pwaColors.light.borderDefault}; }
  @media (prefers-color-scheme: dark) { :root { background: ${pwaColors.dark.canvas}; color: ${pwaColors.dark.textPrimary}; } p { color: ${pwaColors.dark.textSecondary}; } .zh { border-color: ${pwaColors.dark.borderDefault}; } }
</style>
<main>
  <h1>You’re offline</h1>
  <p>Scholens does not store papers or account data for offline use. Reconnect to continue your research.</p>
  <div class="zh" lang="zh-CN">
    <h1>当前处于离线状态</h1>
    <p>Scholens 不会离线保存论文或账户数据。恢复网络连接后即可继续。</p>
  </div>
  <a href="/">Try Scholens again · 重新进入</a>
</main>
</html>`;

  return `const RELEASE = ${JSON.stringify(release)};
const OFFLINE_DOCUMENT = ${JSON.stringify(offlineDocument)};
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => new Response(OFFLINE_DOCUMENT, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    }
  })));
});
void RELEASE;
`;
}

export function GET() {
  return new Response(serviceWorkerSource(), {
    headers: {
      "Cache-Control": "no-cache, no-store, must-revalidate",
      "Content-Security-Policy":
        "default-src 'none'; script-src 'self'; connect-src 'self'",
      "Content-Type": "application/javascript; charset=utf-8",
      "Service-Worker-Allowed": "/",
    },
  });
}
