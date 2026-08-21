"use client";

import { ProductMark } from "@/features/product-identity";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <main className="mx-auto grid min-h-dvh max-w-lg content-center justify-items-start gap-5 px-6 py-12">
          <ProductMark size="display" />
          <div className="grid gap-2">
            <h1 className="text-2xl font-semibold">Scholens could not start</h1>
            <p className="text-secondary text-sm leading-6">
              Try the startup sequence again.
            </p>
          </div>
          <button
            className="bg-primary text-primary-foreground min-h-11 rounded-[var(--radius-md)] px-4 text-sm font-medium"
            onClick={reset}
            type="button"
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
