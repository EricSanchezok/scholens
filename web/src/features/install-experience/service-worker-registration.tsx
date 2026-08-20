"use client";

import * as React from "react";

export function ServiceWorkerRegistration() {
  React.useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    function register() {
      void navigator.serviceWorker
        .register("/sw.js", {
          scope: "/",
          updateViaCache: "none",
        })
        .catch(() => undefined);
    }
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });
    return () => window.removeEventListener("load", register);
  }, []);
  return null;
}
