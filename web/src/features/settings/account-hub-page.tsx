"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { Button, IconButton, keyboardFocusRing } from "@/components/ui";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import {
  AppearanceIcon,
  BackIcon,
  DocumentationIcon,
  ExternalLinkIcon,
  InstallAppIcon,
  IntegrationIcon,
  KeyIcon,
  LanguageIcon,
  NextIcon,
  RepositoryIcon,
  SettingsIcon,
} from "@/design-system/icons/semantic-icons";
import {
  CurrentUserAvatar,
  useAuthSession,
  type Actor,
} from "@/features/authentication";
import { useInstallExperience } from "@/features/install-experience";
import { WorkspaceShell } from "@/features/workspace-shell";
import { DOCUMENTATION_PATH, SOURCE_REPOSITORY_URL } from "@/lib/product";
import { cn } from "@/lib/utilities/cn";
import { useDesktopLayout } from "@/lib/utilities/use-desktop-layout";
import { AccessKeysPanel } from "./access-keys-panel";
import { AccountPanel } from "./account-panel";
import {
  accountHubBackHref,
  accountHubPaths,
  desktopSettingsHref,
  type AccountHubView,
} from "./account-hub-routes";
import { ConnectionsPanel } from "./connections-panel";
import { useCurrentBillingUsage } from "./current-billing-usage";
import { formatDateOnly } from "./formatters";
import { GeneralPanel } from "./general-panel";
import { TranslationPanel } from "./translation-panel";
import { UsagePanel } from "./usage-panel";

function actorName(actor: Actor) {
  return actor.display_name?.trim() || actor.email.split("@")[0] || actor.email;
}

function AccountHubRow({
  description,
  external = false,
  glyph,
  href,
  label,
  onClick,
}: {
  description?: string;
  external?: boolean;
  glyph: IconGlyph;
  href?: string;
  label: string;
  onClick?: () => void;
}) {
  const classes = cn(
    "hover:bg-hover active:bg-pressed flex min-h-16 w-full min-w-0 items-center gap-3 px-4 py-3 text-left",
    keyboardFocusRing,
  );
  const content = (
    <>
      <span className="grid size-7 shrink-0 place-items-center">
        <Icon glyph={glyph} size={20} tone="secondary" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{label}</span>
        {description ? (
          <span className="text-secondary mt-0.5 block text-xs leading-5">
            {description}
          </span>
        ) : null}
      </span>
      <Icon
        glyph={external ? ExternalLinkIcon : NextIcon}
        size={20}
        tone="secondary"
      />
    </>
  );

  if (href && external) {
    return (
      <a
        className={classes}
        href={href}
        rel="noopener noreferrer"
        target="_blank"
      >
        {content}
      </a>
    );
  }
  if (href) {
    return (
      <Link className={classes} href={href as Route}>
        {content}
      </Link>
    );
  }
  return (
    <button className={classes} onClick={onClick} type="button">
      {content}
    </button>
  );
}

function AccountHubGroup({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-subtle divide-line-subtle divide-y overflow-hidden rounded-[var(--radius-xl)]">
      {children}
    </div>
  );
}

function BillingSummary() {
  const t = useTranslations("AccountHub");
  const settingsT = useTranslations("Settings");
  const format = useFormatter();
  const usage = useCurrentBillingUsage();

  if (usage.status === "error") {
    return (
      <div className="bg-subtle flex min-h-24 items-center justify-between gap-4 rounded-[var(--radius-xl)] px-4 py-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{t("usage.title")}</p>
          <p className="text-secondary mt-1 text-xs leading-5">
            {t("usage.unavailable")}
          </p>
        </div>
        <Button onClick={usage.retry} size="sm" variant="ghost">
          {t("actions.retry")}
        </Button>
      </div>
    );
  }

  return (
    <Link
      aria-label={t("usage.open")}
      className={cn(
        "bg-subtle hover:bg-hover active:bg-pressed flex min-h-24 items-center gap-4 rounded-[var(--radius-xl)] px-4 py-4",
        keyboardFocusRing,
      )}
      href={accountHubPaths.usage as Route}
    >
      {usage.status === "loading" ? (
        <span className="text-secondary min-w-0 flex-1 text-sm">
          {t("usage.loading")}
        </span>
      ) : (
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-3">
            <span className="text-sm font-semibold">{t("usage.title")}</span>
            <span className="text-secondary text-xs font-medium">
              {usage.plan === "researcher"
                ? settingsT("plan.researcher")
                : usage.plan === "basic"
                  ? settingsT("plan.basic")
                  : usage.plan}
            </span>
          </span>
          <span className="mt-1 flex items-center justify-between gap-3 text-xs">
            <span className="text-secondary">{t("usage.tokenCredits")}</span>
            <span className="tabular-nums">
              {format.number(usage.tokenCreditsUsed, "compact")}
              {" / "}
              {format.number(usage.tokenCreditsLimit, "compact")}
            </span>
          </span>
          <span className="text-secondary mt-1 block text-xs leading-4">
            {t("usage.reset", {
              date: formatDateOnly(usage.resetDate, format.dateTime),
            })}
          </span>
        </span>
      )}
      <Icon glyph={NextIcon} size={20} tone="secondary" />
    </Link>
  );
}

function AccountHubHome({ actor }: { actor: Actor }) {
  const t = useTranslations("AccountHub");
  const installExperience = useInstallExperience();
  const name = actorName(actor);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pt-[max(var(--space-6),env(safe-area-inset-top))] pb-8 sm:px-6">
      <Link
        aria-label={t("account.open")}
        className={cn(
          "hover:bg-hover active:bg-pressed -mx-2 flex min-h-20 items-center gap-4 rounded-[var(--radius-xl)] px-2 py-2",
          keyboardFocusRing,
        )}
        href={accountHubPaths.account as Route}
      >
        <CurrentUserAvatar
          className="size-16 shrink-0 text-xl font-semibold"
          fallback={name.slice(0, 1).toUpperCase()}
          sizes="64px"
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xl leading-7 font-semibold tracking-[-0.015em]">
            {name}
          </span>
          <span className="text-secondary mt-0.5 block truncate text-sm">
            {actor.email}
          </span>
        </span>
        <Icon glyph={NextIcon} size={20} tone="secondary" />
      </Link>

      <div className="mt-6">
        <BillingSummary />
      </div>

      <section aria-labelledby="account-hub-features" className="mt-8">
        <h2
          className="text-secondary mb-2 px-1 text-xs font-medium"
          id="account-hub-features"
        >
          {t("groups.account")}
        </h2>
        <AccountHubGroup>
          <AccountHubRow
            description={t("settings.description")}
            glyph={SettingsIcon}
            href={accountHubPaths.settings}
            label={t("settings.title")}
          />
          <AccountHubRow
            description={t("connections.description")}
            glyph={IntegrationIcon}
            href={accountHubPaths.connections}
            label={t("connections.title")}
          />
          <AccountHubRow
            description={t("accessKeys.description")}
            glyph={KeyIcon}
            href={accountHubPaths.accessKeys}
            label={t("accessKeys.title")}
          />
        </AccountHubGroup>
      </section>

      <section aria-labelledby="account-hub-help" className="mt-7">
        <h2
          className="text-secondary mb-2 px-1 text-xs font-medium"
          id="account-hub-help"
        >
          {t("groups.help")}
        </h2>
        <AccountHubGroup>
          <AccountHubRow
            external
            glyph={DocumentationIcon}
            href={DOCUMENTATION_PATH}
            label={t("help.documentation")}
          />
          <AccountHubRow
            external
            glyph={RepositoryIcon}
            href={SOURCE_REPOSITORY_URL}
            label={t("help.repository")}
          />
          {installExperience.showInstallEntry ? (
            <AccountHubRow
              glyph={InstallAppIcon}
              label={t("help.install")}
              onClick={() => void installExperience.openInstallExperience()}
            />
          ) : null}
        </AccountHubGroup>
      </section>
    </div>
  );
}

function SettingsOverview() {
  const t = useTranslations("AccountHub");
  return (
    <AccountHubGroup>
      <AccountHubRow
        description={t("display.description")}
        glyph={AppearanceIcon}
        href={accountHubPaths.display}
        label={t("display.title")}
      />
      <AccountHubRow
        description={t("translation.description")}
        glyph={LanguageIcon}
        href={accountHubPaths.translation}
        label={t("translation.title")}
      />
    </AccountHubGroup>
  );
}

function AccountHubContent({ view }: { view: AccountHubView }) {
  if (view === "account") {
    return <AccountPanel showHeader={false} />;
  }
  if (view === "usage") return <UsagePanel showHeader={false} />;
  if (view === "settings") return <SettingsOverview />;
  if (view === "display") return <GeneralPanel showHeader={false} />;
  if (view === "translation") return <TranslationPanel showHeader={false} />;
  if (view === "connections") return <ConnectionsPanel showHeader={false} />;
  if (view === "accessKeys") return <AccessKeysPanel showHeader={false} />;
  return null;
}

function accountHubTitleKey(view: Exclude<AccountHubView, "home">) {
  if (view === "accessKeys") return "accessKeys.title" as const;
  return `${view}.title` as
    | "account.title"
    | "usage.title"
    | "settings.title"
    | "display.title"
    | "translation.title"
    | "connections.title";
}

export function AccountHubWorkspace({
  actor,
  view,
}: {
  actor: Actor;
  view: AccountHubView;
}) {
  const t = useTranslations("AccountHub");
  const router = useRouter();
  const { signOut } = useAuthSession();
  const searchParams = useSearchParams();
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const root = view === "home";
  const childTitle = root ? undefined : t(accountHubTitleKey(view));
  const returnTo = searchParams.get("returnTo");
  const backHref = root ? "/" : accountHubBackHref(view, returnTo);

  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <WorkspaceShell
      activeDestination="me"
      actor={actor}
      collapsed={collapsed}
      mobileHeaderCenter={
        root ? undefined : (
          <h1 className="truncate text-center text-base font-semibold">
            {childTitle}
          </h1>
        )
      }
      mobileHeaderDivider={!root}
      mobileHeaderLeading={
        root ? undefined : (
          <IconButton asChild label={t("actions.back")} variant="ghost">
            <Link href={backHref as Route}>
              <Icon glyph={BackIcon} size={24} />
            </Link>
          </IconButton>
        )
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      showMobileBottomNavigation={root}
      showMobileHeader={!root}
      signingOut={signingOut}
      suppressInstallPromotion
    >
      {root ? (
        <AccountHubHome actor={actor} />
      ) : (
        <div className="mx-auto w-full max-w-2xl px-4 py-6 pb-10 sm:px-6 sm:py-8">
          <h2 className="sr-only">
            {t("sectionContent", { title: childTitle ?? "" })}
          </h2>
          <AccountHubContent view={view} />
        </div>
      )}
    </WorkspaceShell>
  );
}

export function AccountHubPage({ view }: { view: AccountHubView }) {
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("AccountHub.session");
  const session = useAuthSession();
  const isDesktop = useDesktopLayout();

  React.useEffect(() => {
    if (isDesktop) {
      router.replace(desktopSettingsHref(view) as Route, { scroll: false });
    }
  }, [isDesktop, router, view]);

  React.useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(`/login?returnTo=${encodeURIComponent(pathname)}`);
    }
  }, [pathname, router, session.status]);

  if (
    isDesktop ||
    session.status === "bootstrapping" ||
    session.status === "anonymous"
  ) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="w-full max-w-sm">
          <LoadingState label={t("checking")} />
        </div>
      </main>
    );
  }
  if (session.status === "unavailable") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <AsyncFeedback
          action={{ label: t("retry"), onClick: session.retryBootstrap }}
          description={t("unavailableDescription")}
          state="offline"
          title={t("unavailableTitle")}
        />
      </main>
    );
  }
  if (!session.actor) return null;
  return <AccountHubWorkspace actor={session.actor} view={view} />;
}
