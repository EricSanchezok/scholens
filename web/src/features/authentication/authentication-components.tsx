import {
  SuccessIcon,
  EmailIcon,
  WarningIcon,
} from "@/design-system/icons/semantic-icons";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { AuthViewport } from "./auth-surface";

export function AuthenticationShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthViewport className="relative lg:items-center">
      <div className="pointer-events-none fixed top-[max(1.5rem,env(safe-area-inset-top))] left-4 text-lg font-semibold sm:left-8 lg:left-12">
        Scholens
      </div>
      <div className="w-full pt-20 sm:pt-12">{children}</div>
    </AuthViewport>
  );
}

export function AuthenticationPanel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn("mx-auto grid w-full max-w-[22.5rem] gap-5", className)}
    >
      {children}
    </section>
  );
}

export function AuthenticationHeader({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <header className="grid gap-2">
      <h1 className="text-3xl font-semibold tracking-[-0.03em]">{title}</h1>
      <p className="text-secondary text-sm leading-6">{description}</p>
    </header>
  );
}

export function AuthenticationResult({
  children,
  description,
  title,
  tone = "success",
}: {
  children?: React.ReactNode;
  description: string;
  title: string;
  tone?: "mail" | "success" | "danger";
}) {
  const glyph =
    tone === "mail" ? EmailIcon : tone === "danger" ? WarningIcon : SuccessIcon;
  return (
    <div className="settled-content-enter grid gap-5">
      <div className="border-line bg-subtle grid gap-3 rounded-[var(--radius-lg)] border p-4">
        <Icon
          glyph={glyph}
          size={24}
          tone={tone === "danger" ? "primary" : "secondary"}
        />
        <div className="grid gap-1">
          <h2 className="font-medium">{title}</h2>
          <p className="text-secondary text-sm leading-6">{description}</p>
        </div>
      </div>
      {children}
    </div>
  );
}
