"use client";

import type { CSSProperties } from "react";

type GlobalErrorFallbackProps = {
  reset: () => void;
};

const bodyStyle: CSSProperties = {
  background: "Canvas",
  color: "CanvasText",
  colorScheme: "light dark",
  fontFamily:
    "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
  margin: 0,
};

const surfaceStyle: CSSProperties = {
  alignContent: "center",
  background: "Canvas",
  boxSizing: "border-box",
  color: "CanvasText",
  display: "grid",
  gap: 20,
  margin: "0 auto",
  maxWidth: 560,
  minHeight: "100dvh",
  padding: 24,
};

const artworkStyle: CSSProperties = {
  backgroundImage: "url('/brand/scholens-raven-portrait-128.png')",
  backgroundPosition: "center",
  backgroundSize: "cover",
  borderRadius: "50%",
  display: "block",
  height: 80,
  width: 80,
};

const copyStyle: CSSProperties = {
  display: "grid",
  gap: 8,
};

const headingStyle: CSSProperties = {
  fontSize: 24,
  fontWeight: 600,
  letterSpacing: "-0.015em",
  lineHeight: 1.2,
  margin: 0,
};

const descriptionStyle: CSSProperties = {
  color: "GrayText",
  fontSize: 14,
  lineHeight: 1.6,
  margin: 0,
};

const buttonStyle: CSSProperties = {
  background: "CanvasText",
  border: "1px solid CanvasText",
  borderRadius: 8,
  color: "Canvas",
  cursor: "pointer",
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  justifySelf: "start",
  minHeight: 44,
  padding: "0 16px",
};

export function GlobalErrorFallback({ reset }: GlobalErrorFallbackProps) {
  return (
    <main data-global-error-surface style={surfaceStyle}>
      <style>{`
        .global-error-retry:focus-visible {
          background: GrayText;
          background: color-mix(in srgb, CanvasText 86%, Canvas);
          outline: none;
          transform: translateY(-1px);
        }

        @media (forced-colors: active) {
          .global-error-retry:focus-visible {
            background: CanvasText;
            outline: 2px solid Highlight;
            outline-offset: 2px;
            transform: none;
          }
        }
      `}</style>
      <span aria-hidden="true" data-global-error-artwork style={artworkStyle} />
      <div style={copyStyle}>
        <h1 style={headingStyle}>Scholens could not start</h1>
        <p style={descriptionStyle}>Try the startup sequence again.</p>
      </div>
      <button
        className="global-error-retry"
        onClick={reset}
        style={buttonStyle}
        type="button"
      >
        Try again
      </button>
    </main>
  );
}

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" style={{ colorScheme: "light dark" }}>
      <head>
        <title>Scholens could not start</title>
      </head>
      <body style={bodyStyle}>
        <GlobalErrorFallback reset={reset} />
      </body>
    </html>
  );
}
