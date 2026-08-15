import type { ReactNode } from "react";

import { cn } from "@/lib/utilities/cn";

export function SettingsPanelHeader({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <header className="mb-7 max-w-2xl">
      <h2 className="text-2xl leading-8 font-semibold tracking-[-0.015em]">
        {title}
      </h2>
      <p className="text-secondary mt-1.5 text-sm leading-6">{description}</p>
    </header>
  );
}

export function SettingsCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "bg-subtle overflow-hidden rounded-[var(--radius-xl)]",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function SettingsCardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-16 items-start justify-between gap-4 px-4 pt-4 pb-2 sm:px-5 sm:pt-5">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">{title}</h3>
        {description ? (
          <p className="text-secondary mt-1 text-sm leading-5">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function SettingsCardBody({ children }: { children: ReactNode }) {
  return <div className="p-4 sm:p-5">{children}</div>;
}

export function SettingsStatus({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center rounded-full px-2 text-xs font-medium",
        tone === "neutral" && "bg-subtle text-secondary",
        tone === "success" && "bg-state-success-bg text-success",
        tone === "warning" && "bg-state-warning-bg text-warning",
        tone === "danger" && "bg-state-danger-bg text-danger",
      )}
    >
      {children}
    </span>
  );
}
