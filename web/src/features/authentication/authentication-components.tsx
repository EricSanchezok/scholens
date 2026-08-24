import Link from "next/link";
import { useTranslations } from "next-intl";

import { focusSurfaceVariants, Frame, FramePanel } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  DocumentationIcon,
  EmailIcon,
  ExternalLinkIcon,
  RepositoryIcon,
  SuccessIcon,
  WarningIcon,
} from "@/design-system/icons/semantic-icons";
import { ProductLockup } from "@/features/product-identity";
import { DOCUMENTATION_PATH, SOURCE_REPOSITORY_URL } from "@/lib/product";
import { cn } from "@/lib/utilities/cn";
import { AuthViewport } from "./auth-surface";

export function AuthenticationShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const t = useTranslations("Authentication");
  return (
    <AuthViewport className="relative lg:items-center">
      <div className="pointer-events-none fixed top-[max(1.5rem,env(safe-area-inset-top))] left-4 text-lg font-semibold sm:left-8 lg:left-12">
        <ProductLockup size="standard" />
      </div>
      <div className="grid w-full gap-8 pt-20 sm:pt-12">
        {children}
        <nav
          aria-label={t("publicLinks")}
          className="text-secondary mx-auto flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm"
        >
          <Link
            className={cn(
              "hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius-sm)] sm:min-h-9",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
            href={DOCUMENTATION_PATH}
            rel="noopener noreferrer"
            target="_blank"
          >
            <Icon glyph={DocumentationIcon} size={16} tone="secondary" />
            {t("documentation")}
            <Icon glyph={ExternalLinkIcon} size={16} tone="secondary" />
          </Link>
          <a
            className={cn(
              "hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius-sm)] sm:min-h-9",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
            href={SOURCE_REPOSITORY_URL}
            rel="noopener noreferrer"
            target="_blank"
          >
            <Icon glyph={RepositoryIcon} size={16} tone="secondary" />
            {t("repository")}
            <Icon glyph={ExternalLinkIcon} size={16} tone="secondary" />
          </a>
        </nav>
      </div>
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
    <Frame
      asChild
      className={cn("mx-auto w-full max-w-[23.5rem]", className)}
      spacing="compact"
    >
      <section>
        <FramePanel className="grid gap-5" spacing="roomy">
          {children}
        </FramePanel>
      </section>
    </Frame>
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
