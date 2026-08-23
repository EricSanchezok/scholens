"use client";

import {
  AccountIcon,
  CollapseRailIcon,
  DismissIcon,
  DocumentationIcon,
  ExpandRailIcon,
  ExternalLinkIcon,
  InstallAppIcon,
  RepositoryIcon,
  SignOutIcon,
  MenuIcon,
  NextIcon,
  SearchIcon,
  SettingsIcon,
  UsageIcon,
} from "@/design-system/icons/semantic-icons";
import {
  motionCssEasings,
  motionDurations,
} from "@/design-system/generated/motion-metadata";
import Link from "next/link";
import type { Route } from "next";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Button,
  IconButton,
  keyboardFocusRing,
  Sheet,
  SheetContent,
  SheetTitle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import { useMotionPreference } from "@/design-system/motion/motion-provider";
import { CurrentUserAvatar, type Actor } from "@/features/authentication";
import { conversationQueries } from "@/features/conversation";
import { GlobalSearch } from "@/features/paper-search";
import { ProductLockup } from "@/features/product-identity";
import {
  InstallInstructionsDialog,
  InstallPromotion,
  useInstallExperience,
} from "@/features/install-experience";
import {
  formatDateOnly,
  SettingsDialog,
  useCurrentBillingUsage,
  useSettingsLauncher,
  type CurrentBillingUsageSummary,
} from "@/features/settings";
import type { components } from "@/lib/api/generated/schema";
import { DOCUMENTATION_PATH, SOURCE_REPOSITORY_URL } from "@/lib/product";
import { cn } from "@/lib/utilities/cn";
import {
  beginRouteNavigation,
  reportRouteNavigationFeedback,
  useRouteNavigationPending,
} from "@/lib/observability/web-performance";
import {
  AskIcon,
  LibraryIcon,
  NewConversationIcon,
  ProjectIcon,
} from "./icons";
import {
  ConversationActionDialogs,
  type ConversationDialogTarget,
} from "./conversation-action-dialogs";
import { ConversationListItem } from "./conversation-list-item";
import {
  useConversationListController,
  type ConversationListController,
} from "./use-conversation-list-controller";
import { useDesktopLayout } from "@/lib/utilities/use-desktop-layout";
import { useVisualViewport } from "@/lib/utilities/use-visual-viewport";

export type WorkspaceDestination = "ask" | "library" | "projects" | "me";

export type MobileViewportState = {
  open: boolean;
  viewportHeight?: number;
  viewportOffsetTop?: number;
};

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];
type ConversationListResponse =
  components["schemas"]["ConversationListResponse"];

type ConversationHistoryGroup = {
  key: string;
  title: string;
  items: ConversationSummary[];
};

type RailFlipSnapshot = {
  chromeClipPath: string;
  contentLeft: number;
};

function actorName(actor: Actor) {
  return actor.display_name?.trim() || actor.email.split("@")[0] || actor.email;
}

function isPrimaryNavigationClick(event: React.MouseEvent<HTMLAnchorElement>) {
  return (
    event.button === 0 &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey &&
    !event.defaultPrevented
  );
}

function startOfLocalDay(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

export function groupConversationHistory(
  conversations: ConversationSummary[],
  locale: string,
  labels: {
    today: string;
    yesterday: string;
    previous7Days: string;
    previous30Days: string;
  },
  now = new Date(),
): ConversationHistoryGroup[] {
  const today = startOfLocalDay(now);
  const monthFormat = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
  });
  const groups = new Map<string, ConversationHistoryGroup>();

  for (const conversation of conversations) {
    const updatedAt = new Date(conversation.updated_at);
    const ageInDays = Math.floor(
      (today.getTime() - startOfLocalDay(updatedAt).getTime()) / 86_400_000,
    );
    let key: string;
    let title: string;
    if (ageInDays <= 0) {
      key = "today";
      title = labels.today;
    } else if (ageInDays === 1) {
      key = "yesterday";
      title = labels.yesterday;
    } else if (ageInDays < 7) {
      key = "previous-7-days";
      title = labels.previous7Days;
    } else if (ageInDays < 30) {
      key = "previous-30-days";
      title = labels.previous30Days;
    } else {
      key = `${updatedAt.getFullYear()}-${updatedAt.getMonth()}`;
      title = monthFormat.format(updatedAt);
    }
    const group = groups.get(key) ?? { key, title, items: [] };
    group.items.push(conversation);
    groups.set(key, group);
  }
  return [...groups.values()];
}

export function flattenConversationPages(pages: ConversationListResponse[]) {
  const seen = new Set<string>();
  return pages
    .flatMap((page) => page.items)
    .filter((conversation) => {
      if (seen.has(conversation.id)) return false;
      seen.add(conversation.id);
      return true;
    });
}

function NavigationPendingIndicator({
  href,
  label,
}: {
  href: string;
  label: string;
}) {
  const pending = useRouteNavigationPending(href);
  React.useEffect(() => {
    if (pending) reportRouteNavigationFeedback();
  }, [pending]);
  return (
    <>
      <span aria-live="polite" className="sr-only">
        {pending ? label : ""}
      </span>
      <span
        aria-hidden="true"
        className={cn(
          "bg-primary pointer-events-none absolute top-1.5 right-1.5 size-1.5 rounded-full opacity-0",
          pending && "opacity-100",
        )}
        data-navigation-pending={pending || undefined}
      />
    </>
  );
}

function SidebarLinkContent({
  animateLabel,
  active,
  collapsed,
  glyph,
  href,
  label,
}: {
  animateLabel: boolean;
  active: boolean;
  collapsed: boolean;
  glyph: IconGlyph;
  href: string;
  label: string;
}) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center">
        <Icon glyph={glyph} size={20} tone={active ? "primary" : "secondary"} />
      </span>
      {!collapsed && (
        <span
          className={cn(
            "text-sidebar-label truncate",
            animateLabel && "settled-content-enter",
          )}
        >
          {label}
        </span>
      )}
      <NavigationPendingIndicator href={href} label={label} />
    </>
  );
}

function SidebarControl({
  animateLabel = false,
  collapsed,
  label,
  glyph,
  active,
  href,
  disabled,
  disabledHint,
  onSelect,
}: {
  animateLabel?: boolean;
  collapsed: boolean;
  label: string;
  glyph: IconGlyph;
  active?: boolean;
  href?: string;
  disabled?: boolean;
  disabledHint?: string;
  onSelect?: () => void;
}) {
  const accessibleLabel =
    disabled && disabledHint ? `${label}. ${disabledHint}` : label;
  const control = href ? (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={accessibleLabel}
      className={cn(
        "motion-control active:bg-pressed relative flex h-10 items-center gap-2 rounded-[var(--radius-lg)] border font-medium",
        keyboardFocusRing,
        collapsed ? "w-10 justify-center" : "w-full px-2",
        active
          ? "border-line bg-surface shadow-raised"
          : "hover:bg-hover border-transparent",
      )}
      href={href as Route}
      onClick={(event) => {
        if (!isPrimaryNavigationClick(event)) return;
        beginRouteNavigation(href);
        onSelect?.();
      }}
      prefetch
    >
      <SidebarLinkContent
        animateLabel={animateLabel}
        active={Boolean(active)}
        collapsed={collapsed}
        glyph={glyph}
        href={href}
        label={label}
      />
    </Link>
  ) : (
    <button
      aria-disabled={disabled || undefined}
      aria-label={disabled || collapsed ? accessibleLabel : undefined}
      className={cn(
        "motion-control flex h-10 items-center gap-2 rounded-[var(--radius-lg)] border border-transparent font-medium",
        keyboardFocusRing,
        collapsed ? "w-10 justify-center" : "w-full px-2",
        disabled ? "text-secondary cursor-not-allowed" : "hover:bg-hover",
      )}
      onClick={disabled ? undefined : onSelect}
      type="button"
    >
      <span className="grid size-6 shrink-0 place-items-center">
        <Icon glyph={glyph} size={20} tone="secondary" />
      </span>
      {!collapsed && (
        <span
          className={cn(
            "text-sidebar-label truncate",
            animateLabel && "settled-content-enter",
          )}
        >
          {label}
        </span>
      )}
    </button>
  );

  if (!collapsed && !disabled) return control;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{control}</TooltipTrigger>
      <TooltipContent side="right">
        {disabled && disabledHint ? `${label} · ${disabledHint}` : label}
      </TooltipContent>
    </Tooltip>
  );
}

function ConversationGroup({
  title,
  items,
  activeConversationId,
  onSelect,
  controller,
  onDelete,
  onRequestMobileRename,
}: {
  title: string;
  items: ConversationSummary[];
  activeConversationId?: string;
  onSelect?: () => void;
  controller: ConversationListController;
  onDelete: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onRequestMobileRename: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="grid gap-0.5">
      <div className="text-secondary flex h-6 items-center px-2 text-xs font-medium">
        {title}
      </div>
      {items.map((conversation) => {
        const href = `/?conversation=${conversation.id}`;
        return (
          <ConversationListItem
            conversation={conversation}
            current={activeConversationId === conversation.id}
            href={href}
            key={conversation.id}
            onDelete={(returnFocus) => onDelete(conversation, returnFocus)}
            onNavigate={onSelect}
            onRename={(title) =>
              controller.renameConversation(conversation, title)
            }
            onRequestMobileRename={(returnFocus) =>
              onRequestMobileRename(conversation, returnFocus)
            }
            onTogglePinned={() =>
              controller.toggleConversationPinned(conversation)
            }
            pending={
              controller.updatingConversationId === conversation.id ||
              controller.deletingConversationId === conversation.id
            }
          />
        );
      })}
    </section>
  );
}

function AccountMenu({
  actor,
  billingUsage,
  collapsed,
  signingOut,
  onOpenAccount,
  onOpenSettings,
  onOpenUsage,
  onSignOut,
}: {
  actor: Actor;
  billingUsage: CurrentBillingUsageSummary;
  collapsed: boolean;
  signingOut: boolean;
  onOpenAccount: () => void;
  onOpenSettings: () => void;
  onOpenUsage: () => void;
  onSignOut: () => Promise<void>;
}) {
  const t = useTranslations("WorkspaceShell");
  const format = useFormatter();
  const name = actorName(actor);
  const initial = name.slice(0, 1).toUpperCase();

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={t("account.openMenu")}
          className={cn(
            "border-line bg-surface shadow-raised hover:bg-hover flex h-14 items-center rounded-[var(--radius-xl)] border",
            keyboardFocusRing,
            collapsed
              ? "ml-auto w-10 justify-center px-2"
              : "w-full gap-3 px-2",
          )}
          type="button"
        >
          <CurrentUserAvatar
            className={cn(
              collapsed ? "text-caption size-8" : "size-10 text-sm",
            )}
            data-account-avatar
            fallback={initial}
            sizes={collapsed ? "32px" : "40px"}
          />
          {!collapsed && (
            <span className="min-w-0 flex-1 text-left">
              <span className="text-sidebar-label block truncate leading-5 font-normal">
                {name}
              </span>
              <span className="text-caption text-secondary block truncate leading-4">
                {actor.email}
              </span>
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={collapsed ? "end" : "start"}
        className={cn(
          "rounded-[var(--radius-xl)]",
          collapsed
            ? "w-72"
            : "w-[max(var(--radix-dropdown-menu-trigger-width),18rem)]",
        )}
        side={collapsed ? "right" : "top"}
        sideOffset={collapsed ? 8 : 4}
      >
        <DropdownMenuLabel className="flex items-center gap-3 px-2.5 py-3">
          <CurrentUserAvatar
            className="text-foreground size-10 text-sm font-semibold"
            data-account-avatar
            fallback={initial}
            sizes="40px"
          />
          <span className="min-w-0">
            <span className="text-foreground block truncate text-sm leading-5">
              {name}
            </span>
            <span className="text-caption text-secondary block truncate leading-4 font-normal">
              {actor.email}
            </span>
          </span>
        </DropdownMenuLabel>
        {billingUsage.status === "success" ? (
          <DropdownMenuLabel className="bg-subtle mx-0.5 mb-1.5 grid gap-1.5 rounded-[var(--radius-lg)] px-3 py-2.5">
            <span className="sr-only">{t("account.usageSummary")}</span>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-secondary">{t("account.plan")}</span>
              <span className="font-medium">
                {billingUsage.plan === "researcher"
                  ? t("account.planResearcher")
                  : billingUsage.plan === "basic"
                    ? t("account.planBasic")
                    : billingUsage.plan}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-secondary">
                {t("account.tokenCredits")}
              </span>
              <span className="tabular-nums">
                {format.number(billingUsage.tokenCreditsUsed, "compact")}
                {" / "}
                {format.number(billingUsage.tokenCreditsLimit, "compact")}
              </span>
            </div>
            <p className="text-caption text-secondary leading-4">
              {t("account.creditsReset", {
                date: formatDateOnly(billingUsage.resetDate, format.dateTime),
              })}
            </p>
          </DropdownMenuLabel>
        ) : billingUsage.status === "loading" ? (
          <DropdownMenuLabel className="text-secondary mx-1 mb-1 px-2.5 py-2 text-xs">
            {t("account.usageLoading")}
          </DropdownMenuLabel>
        ) : (
          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              billingUsage.retry();
            }}
          >
            <Icon glyph={UsageIcon} size={16} tone="secondary" />
            {t("account.usageUnavailable")}
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="rounded-[var(--radius-lg)] px-2.5"
          onSelect={onOpenSettings}
        >
          <Icon glyph={SettingsIcon} size={16} tone="secondary" />
          {t("account.settings")}
        </DropdownMenuItem>
        <DropdownMenuItem
          className="rounded-[var(--radius-lg)] px-2.5"
          onSelect={onOpenAccount}
        >
          <Icon glyph={AccountIcon} size={16} tone="secondary" />
          {t("account.accountSettings")}
        </DropdownMenuItem>
        <DropdownMenuItem
          className="rounded-[var(--radius-lg)] px-2.5"
          onSelect={onOpenUsage}
        >
          <Icon glyph={UsageIcon} size={16} tone="secondary" />
          {t("account.usageSettings")}
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link
            className="rounded-[var(--radius-lg)] px-2.5"
            href={DOCUMENTATION_PATH}
            rel="noopener noreferrer"
            target="_blank"
          >
            <Icon glyph={DocumentationIcon} size={16} tone="secondary" />
            <span className="min-w-0 flex-1">{t("account.documentation")}</span>
            <Icon glyph={ExternalLinkIcon} size={16} tone="secondary" />
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <a
            className="rounded-[var(--radius-lg)] px-2.5"
            href={SOURCE_REPOSITORY_URL}
            rel="noopener noreferrer"
            target="_blank"
          >
            <Icon glyph={RepositoryIcon} size={16} tone="secondary" />
            <span className="min-w-0 flex-1">{t("account.repository")}</span>
            <Icon glyph={ExternalLinkIcon} size={16} tone="secondary" />
          </a>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="rounded-[var(--radius-lg)] px-2.5"
          disabled={signingOut}
          onSelect={() => void onSignOut()}
        >
          <Icon glyph={SignOutIcon} size={16} tone="secondary" />
          {signingOut ? t("account.signingOut") : t("account.signOut")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MobileActorIdentity({
  actor,
  onSelect,
}: {
  actor: Actor;
  onSelect: () => void;
}) {
  const name = actorName(actor);
  return (
    <Link
      aria-label={name}
      className={cn(
        "hover:bg-hover active:bg-pressed -ml-2 flex min-w-0 flex-1 items-center gap-3 rounded-[var(--radius-xl)] px-2 py-2",
        keyboardFocusRing,
      )}
      href={"/me" as Route}
      onClick={onSelect}
    >
      <CurrentUserAvatar
        className="size-12 text-sm"
        fallback={name.slice(0, 1).toUpperCase()}
        sizes="48px"
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-lg leading-6 font-semibold tracking-[-0.01em]">
          {name}
        </span>
        <span className="text-secondary block truncate text-sm leading-5">
          {actor.email}
        </span>
      </span>
      <Icon glyph={NextIcon} size={20} tone="secondary" />
    </Link>
  );
}

function MobileConversationGroup({
  activeConversationId,
  items,
  onSelect,
  title,
  controller,
  onDelete,
  onRequestMobileRename,
}: {
  activeConversationId?: string;
  items: ConversationSummary[];
  onSelect: () => void;
  title: string;
  controller: ConversationListController;
  onDelete: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onRequestMobileRename: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="grid gap-1">
      <h2 className="text-secondary px-3 pt-4 pb-1 text-sm font-medium">
        {title}
      </h2>
      {items.map((conversation) => {
        const href = `/?conversation=${conversation.id}`;
        return (
          <ConversationListItem
            conversation={conversation}
            current={activeConversationId === conversation.id}
            href={href}
            key={conversation.id}
            mobile
            onDelete={(returnFocus) => onDelete(conversation, returnFocus)}
            onNavigate={onSelect}
            onRename={(nextTitle) =>
              controller.renameConversation(conversation, nextTitle)
            }
            onRequestMobileRename={(returnFocus) =>
              onRequestMobileRename(conversation, returnFocus)
            }
            onTogglePinned={() =>
              controller.toggleConversationPinned(conversation)
            }
            pending={
              controller.updatingConversationId === conversation.id ||
              controller.deletingConversationId === conversation.id
            }
          />
        );
      })}
    </section>
  );
}

function ConversationHistoryPagination({
  hasNextPage,
  isFetchingNextPage,
  isError,
  onLoadMore,
  onRetry,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isError: boolean;
  onLoadMore: () => void;
  onRetry: () => void;
}) {
  const t = useTranslations("WorkspaceShell.sidebar");
  const sentinelRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !hasNextPage || isFetchingNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
      },
      { rootMargin: "160px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, onLoadMore]);

  if (isError) {
    return (
      <button
        className={cn(
          "text-secondary hover:bg-hover mt-2 w-full rounded-[var(--radius-lg)] px-3 py-2 text-left text-xs",
          keyboardFocusRing,
        )}
        onClick={onRetry}
        type="button"
      >
        {t("historyError")} · {t("retry")}
      </button>
    );
  }
  if (!hasNextPage && !isFetchingNextPage) return null;
  return (
    <div className="py-2" ref={sentinelRef}>
      <button
        className={cn(
          "text-secondary hover:bg-hover w-full rounded-[var(--radius-lg)] px-3 py-2 text-xs",
          keyboardFocusRing,
        )}
        disabled={isFetchingNextPage}
        onClick={onLoadMore}
        type="button"
      >
        {isFetchingNextPage ? t("loadingMore") : t("loadMore")}
      </button>
    </div>
  );
}

function ConversationHistory({
  activeConversationId,
  conversations,
  currentConversation,
  controller,
  hasNextPage,
  isError,
  isFetchingNextPage,
  mobile = false,
  onDeleteConversation,
  onLoadMore,
  onRequestMobileRename,
  onRetry,
  onSelect,
}: {
  activeConversationId?: string;
  conversations: ConversationSummary[];
  currentConversation?: ConversationSummary;
  controller: ConversationListController;
  hasNextPage: boolean;
  isError: boolean;
  isFetchingNextPage: boolean;
  mobile?: boolean;
  onDeleteConversation: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onLoadMore: () => void;
  onRequestMobileRename: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onRetry: () => void;
  onSelect?: () => void;
}) {
  const t = useTranslations("WorkspaceShell.sidebar");
  const locale = useLocale();
  const pinned = conversations.filter((item) => item.pinned_at);
  const historyGroups = groupConversationHistory(
    conversations.filter((item) => !item.pinned_at),
    locale,
    {
      today: t("today"),
      yesterday: t("yesterday"),
      previous7Days: t("previous7Days"),
      previous30Days: t("previous30Days"),
    },
  );
  const Group = mobile ? MobileConversationGroup : ConversationGroup;
  const shared = {
    activeConversationId,
    controller,
    onDelete: onDeleteConversation,
    onRequestMobileRename,
    onSelect: onSelect ?? (() => undefined),
  };

  return (
    <>
      {currentConversation && (
        <Group {...shared} items={[currentConversation]} title={t("current")} />
      )}
      <Group {...shared} items={pinned} title={t("pinned")} />
      {historyGroups.map((group) => (
        <Group
          {...shared}
          items={group.items}
          key={group.key}
          title={group.title}
        />
      ))}
      {conversations.length === 0 && !currentConversation && !isError && (
        <p className="text-secondary px-2 py-4 text-xs leading-5">
          {t("empty")}
        </p>
      )}
      <ConversationHistoryPagination
        hasNextPage={hasNextPage}
        isError={isError}
        isFetchingNextPage={isFetchingNextPage}
        onLoadMore={onLoadMore}
        onRetry={onRetry}
      />
    </>
  );
}

function MobileNavigation({
  actor,
  conversations,
  currentConversation,
  activeConversationId,
  hasNextPage,
  isError,
  isFetchingNextPage,
  onLoadMore,
  onRetry,
  onSearch,
  onSelect,
  controller,
  onDeleteConversation,
  onRequestMobileRename,
  onInstall,
  showInstall,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  currentConversation?: ConversationSummary;
  activeConversationId?: string;
  hasNextPage: boolean;
  isError: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
  onRetry: () => void;
  onSearch: () => void;
  onSelect: () => void;
  controller: ConversationListController;
  onDeleteConversation: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onRequestMobileRename: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onInstall: () => void;
  showInstall: boolean;
}) {
  const t = useTranslations("WorkspaceShell");

  return (
    <aside className="flex h-full flex-col overflow-hidden bg-[var(--color-bg-sidebar)] pt-[env(safe-area-inset-top)]">
      <div className="flex min-h-20 shrink-0 items-center px-4 pr-16">
        <div className="min-w-0 flex-1">
          <MobileActorIdentity actor={actor} onSelect={onSelect} />
        </div>
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto px-3 pb-4"
        data-scrollbar-gutter="stable"
      >
        <ConversationHistory
          activeConversationId={activeConversationId}
          conversations={conversations}
          controller={controller}
          currentConversation={currentConversation}
          hasNextPage={hasNextPage}
          isError={isError}
          isFetchingNextPage={isFetchingNextPage}
          mobile
          onDeleteConversation={onDeleteConversation}
          onLoadMore={onLoadMore}
          onRequestMobileRename={onRequestMobileRename}
          onRetry={onRetry}
          onSelect={onSelect}
        />
      </div>
      <div
        className="shrink-0 bg-[var(--color-bg-sidebar)] px-3 pt-2 pb-[max(var(--space-3),env(safe-area-inset-bottom))]"
        data-testid="mobile-navigation-tools"
      >
        {showInstall && (
          <Button
            className="mb-2 w-full justify-start"
            onClick={onInstall}
            variant="ghost"
          >
            <Icon glyph={InstallAppIcon} size={20} tone="secondary" />
            {t("navigation.install")}
          </Button>
        )}
        <div className="flex items-center gap-2">
          <button
            aria-label={t("navigation.search")}
            className={cn(
              "bg-surface text-secondary hover:bg-hover flex h-12 min-w-0 flex-1 items-center gap-3 rounded-full px-4 text-left text-base",
              keyboardFocusRing,
            )}
            onClick={onSearch}
            type="button"
          >
            <Icon glyph={SearchIcon} size={20} tone="secondary" />
            <span className="truncate">{t("navigation.searchShort")}</span>
          </button>
          <Link
            aria-label={t("navigation.newChat")}
            className={cn(
              "bg-surface hover:bg-hover grid size-12 shrink-0 place-items-center rounded-full",
              keyboardFocusRing,
            )}
            href="/"
            onClick={onSelect}
          >
            <Icon glyph={NewConversationIcon} size={20} tone="primary" />
          </Link>
        </div>
      </div>
    </aside>
  );
}

function MobileDestinationContent({
  active,
  glyph,
  href,
  label,
}: {
  active: boolean;
  glyph: IconGlyph;
  href: string;
  label: string;
}) {
  const pending = useRouteNavigationPending(href);
  const selected = active || pending;
  React.useEffect(() => {
    if (pending) reportRouteNavigationFeedback();
  }, [pending]);
  return (
    <>
      <span
        className={cn(
          "relative grid size-8 place-items-center rounded-full",
          selected && "bg-primary",
        )}
        data-selected-indicator={selected || undefined}
      >
        <Icon
          glyph={glyph}
          size={20}
          tone={selected ? "inverse" : "secondary"}
        />
        {pending && (
          <span
            aria-hidden="true"
            className="bg-canvas absolute -top-0.5 -right-0.5 size-2 rounded-full border border-current"
            data-navigation-pending
          />
        )}
      </span>
      <span className={selected ? "text-foreground font-semibold" : ""}>
        {label}
      </span>
      <span aria-live="polite" className="sr-only">
        {pending ? label : ""}
      </span>
    </>
  );
}

function MobileDestinationLink({
  active,
  glyph,
  href,
  label,
}: {
  active: boolean;
  glyph: IconGlyph;
  href: string;
  label: string;
}) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={label}
      className={cn(
        "active:bg-pressed flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[var(--radius-md)] px-1 text-xs font-medium",
        keyboardFocusRing,
        active ? "text-foreground" : "text-secondary",
      )}
      href={href as Route}
      onClick={(event) => {
        if (isPrimaryNavigationClick(event)) beginRouteNavigation(href);
      }}
      prefetch
    >
      <MobileDestinationContent
        active={active}
        glyph={glyph}
        href={href}
        label={label}
      />
    </Link>
  );
}

function MobileTabBar({
  activeDestination,
}: {
  activeDestination: WorkspaceDestination;
}) {
  const t = useTranslations("WorkspaceShell.navigation");
  return (
    <nav
      aria-label={t("primary")}
      className="bg-canvas grid h-16 shrink-0 grid-cols-4 px-1 lg:hidden"
      data-testid="mobile-tab-bar"
    >
      <MobileDestinationLink
        active={activeDestination === "ask"}
        glyph={AskIcon}
        href="/"
        label={t("ask")}
      />
      <MobileDestinationLink
        active={activeDestination === "library"}
        glyph={LibraryIcon}
        href="/library"
        label={t("library")}
      />
      <MobileDestinationLink
        active={activeDestination === "projects"}
        glyph={ProjectIcon}
        href="/projects"
        label={t("projects")}
      />
      <MobileDestinationLink
        active={activeDestination === "me"}
        glyph={AccountIcon}
        href="/me"
        label={t("me")}
      />
    </nav>
  );
}

function MobileBottomDock({
  activeDestination,
  content,
  keyboardOpen,
  showNavigation,
  ref,
}: {
  activeDestination: WorkspaceDestination;
  content?: React.ReactNode;
  keyboardOpen: boolean;
  showNavigation: boolean;
  ref: React.Ref<HTMLDivElement>;
}) {
  return (
    <div
      className={cn(
        "bg-canvas relative z-30 grid shrink-0 gap-1 pr-[calc(var(--space-2)+env(safe-area-inset-right))] pl-[calc(var(--space-2)+env(safe-area-inset-left))] lg:hidden",
        !keyboardOpen && "pb-[max(0.5rem,env(safe-area-inset-bottom))]",
      )}
      data-keyboard-open={keyboardOpen || undefined}
      data-testid="mobile-bottom-dock"
      ref={ref}
    >
      {content ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-0 bottom-full left-0 h-5 bg-[linear-gradient(to_top,var(--color-bg-canvas),transparent)]"
        />
      ) : null}
      {content && <div className="min-w-0">{content}</div>}
      {!keyboardOpen && showNavigation && (
        <MobileTabBar activeDestination={activeDestination} />
      )}
    </div>
  );
}

export function WorkspaceNewChatAction() {
  const t = useTranslations("WorkspaceShell.navigation");
  return (
    <Link
      aria-label={t("newChat")}
      className={cn(
        "hover:bg-hover active:bg-pressed grid size-11 place-items-center rounded-[var(--radius-md)]",
        keyboardFocusRing,
      )}
      href="/"
    >
      <Icon glyph={NewConversationIcon} size={24} />
    </Link>
  );
}

function Sidebar({
  animateLabels,
  actor,
  billingUsage,
  conversations,
  currentConversation,
  activeConversationId,
  activeDestination,
  collapsed,
  hasNextPage,
  isError,
  isFetchingNextPage,
  signingOut,
  onCollapsedChange,
  onOpenAccount,
  onOpenSettings,
  onOpenUsage,
  onSignOut,
  onLoadMore,
  onRetry,
  onSearch,
  onSelect,
  controller,
  onDeleteConversation,
  onRequestMobileRename,
}: {
  animateLabels: boolean;
  actor: Actor;
  billingUsage: CurrentBillingUsageSummary;
  conversations: ConversationSummary[];
  currentConversation?: ConversationSummary;
  activeConversationId?: string;
  activeDestination: WorkspaceDestination;
  collapsed: boolean;
  hasNextPage: boolean;
  isError: boolean;
  isFetchingNextPage: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onOpenAccount: () => void;
  onOpenSettings: () => void;
  onOpenUsage: () => void;
  onSignOut: () => Promise<void>;
  onLoadMore: () => void;
  onRetry: () => void;
  onSearch: () => void;
  onSelect?: () => void;
  controller: ConversationListController;
  onDeleteConversation: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
  onRequestMobileRename: (
    conversation: ConversationSummary,
    returnFocus: HTMLButtonElement | null,
  ) => void;
}) {
  const t = useTranslations("WorkspaceShell");

  return (
    <TooltipProvider delayDuration={250}>
      <aside
        aria-label={t("navigation.sidebar")}
        className={cn(
          "flex h-full shrink-0 flex-col overflow-hidden px-3 pt-3 pb-[max(var(--space-1),env(safe-area-inset-bottom))]",
          collapsed ? "w-16" : "w-[var(--workspace-sidebar-width)]",
        )}
      >
        <div className="relative mb-3 flex h-10 shrink-0 items-center justify-end">
          {!collapsed && (
            <Link
              className="motion-control text-ui absolute left-1 font-semibold tracking-[-0.003em] whitespace-nowrap"
              href="/"
            >
              <ProductLockup />
            </Link>
          )}
          <div className="flex items-center gap-1">
            {!collapsed && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <IconButton
                    className="hover:bg-hover size-8 min-h-8 bg-transparent"
                    label={t("navigation.search")}
                    onClick={onSearch}
                    variant="ghost"
                  >
                    <Icon glyph={SearchIcon} size={20} tone="secondary" />
                  </IconButton>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  {t("navigation.search")}
                </TooltipContent>
              </Tooltip>
            )}
            <IconButton
              className="hover:bg-hover size-8 min-h-8 bg-transparent"
              label={
                collapsed ? t("navigation.expand") : t("navigation.collapse")
              }
              onClick={() => onCollapsedChange(!collapsed)}
              variant="ghost"
            >
              <Icon
                glyph={collapsed ? ExpandRailIcon : CollapseRailIcon}
                size={16}
                tone="secondary"
              />
            </IconButton>
          </div>
        </div>
        <nav
          className={cn("grid gap-0.5", collapsed && "justify-items-end")}
          aria-label={t("navigation.openMenu")}
        >
          <SidebarControl
            active={activeDestination === "ask" && !activeConversationId}
            animateLabel={animateLabels}
            collapsed={collapsed}
            glyph={NewConversationIcon}
            href="/"
            label={t("navigation.newChat")}
            onSelect={onSelect}
          />
          {collapsed && (
            <SidebarControl
              collapsed
              glyph={SearchIcon}
              label={t("navigation.search")}
              onSelect={onSearch}
            />
          )}
          <SidebarControl
            active={activeDestination === "library"}
            animateLabel={animateLabels}
            collapsed={collapsed}
            glyph={LibraryIcon}
            href="/library"
            label={t("navigation.library")}
          />
          <SidebarControl
            active={activeDestination === "projects"}
            animateLabel={animateLabels}
            collapsed={collapsed}
            glyph={ProjectIcon}
            href="/projects"
            label={t("navigation.projects")}
          />
        </nav>
        {!collapsed && (
          <div
            className="mt-3 min-h-0 flex-1 overflow-y-auto"
            data-scrollbar-gutter="stable"
          >
            <ConversationHistory
              activeConversationId={activeConversationId}
              conversations={conversations}
              controller={controller}
              currentConversation={currentConversation}
              hasNextPage={hasNextPage}
              isError={isError}
              isFetchingNextPage={isFetchingNextPage}
              onDeleteConversation={onDeleteConversation}
              onLoadMore={onLoadMore}
              onRequestMobileRename={onRequestMobileRename}
              onRetry={onRetry}
              onSelect={onSelect}
            />
          </div>
        )}
        {collapsed && <div className="flex-1" />}
        <AccountMenu
          actor={actor}
          billingUsage={billingUsage}
          collapsed={collapsed}
          onOpenAccount={onOpenAccount}
          onOpenSettings={onOpenSettings}
          onOpenUsage={onOpenUsage}
          onSignOut={onSignOut}
          signingOut={signingOut}
        />
      </aside>
    </TooltipProvider>
  );
}

export function WorkspaceShell({
  actor,
  activeConversationId,
  activeDestination,
  collapsed,
  signingOut,
  onCollapsedChange,
  onSignOut,
  mobileHeaderLeading,
  mobileHeaderCenter,
  mobileHeaderTrailing,
  mobileHeaderDivider = true,
  showMobileHeader = true,
  mobileBottomContent,
  mobileBottomRef,
  mobileViewport,
  showMobileBottomNavigation = true,
  suppressInstallPromotion = false,
  children,
}: {
  actor: Actor;
  activeConversationId?: string;
  activeDestination: WorkspaceDestination;
  collapsed: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onSignOut: () => Promise<void>;
  mobileHeaderLeading?: React.ReactNode;
  mobileHeaderCenter?: React.ReactNode;
  mobileHeaderTrailing?: React.ReactNode;
  mobileHeaderDivider?: boolean;
  showMobileHeader?: boolean;
  mobileBottomContent?: React.ReactNode;
  mobileBottomRef?: React.Ref<HTMLDivElement>;
  mobileViewport?: MobileViewportState;
  showMobileBottomNavigation?: boolean;
  suppressInstallPromotion?: boolean;
  children: React.ReactNode;
}) {
  const t = useTranslations("WorkspaceShell");
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [animateSidebarLabels, setAnimateSidebarLabels] = React.useState(false);
  const searchReturnFocusRef = React.useRef<HTMLElement | null>(null);
  const [deleteTarget, setDeleteTarget] =
    React.useState<ConversationDialogTarget>();
  const [renameTarget, setRenameTarget] =
    React.useState<ConversationDialogTarget>();
  const installExperience = useInstallExperience();
  const billingUsage = useCurrentBillingUsage();
  const conversationController = useConversationListController({
    activeConversationId,
  });
  const conversationListQuery = useInfiniteQuery(
    conversationQueries.infiniteList(),
  );
  const conversations = React.useMemo(() => {
    return flattenConversationPages(conversationListQuery.data?.pages ?? []);
  }, [conversationListQuery.data?.pages]);
  const activeConversationLoaded =
    !activeConversationId ||
    conversations.some(
      (conversation) => conversation.id === activeConversationId,
    );
  const activeConversationQuery = useQuery({
    ...conversationQueries.detail(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId && !activeConversationLoaded),
  });
  const currentConversation = activeConversationLoaded
    ? undefined
    : activeConversationQuery.data;
  const loadMoreConversations = React.useCallback(() => {
    if (
      conversationListQuery.hasNextPage &&
      !conversationListQuery.isFetchingNextPage
    ) {
      void conversationListQuery.fetchNextPage();
    }
  }, [conversationListQuery]);
  const retryConversations = React.useCallback(() => {
    void conversationListQuery.refetch();
  }, [conversationListQuery]);
  const { openSection: openSettingsSection } = useSettingsLauncher();
  const {
    ready: motionReady,
    resolved: resolvedMotion,
    skipAnimations,
  } = useMotionPreference();
  const mobileSheetRef = React.useRef<HTMLDivElement>(null);
  const mobileMenuTriggerRef = React.useRef<HTMLButtonElement>(null);
  const localMobileDockRef = React.useRef<HTMLDivElement>(null);
  const desktopRailChromeRef = React.useRef<HTMLDivElement>(null);
  const desktopContentRef = React.useRef<HTMLDivElement>(null);
  const railFlipSnapshotRef = React.useRef<RailFlipSnapshot | undefined>(
    undefined,
  );
  const railAnimationsRef = React.useRef<Animation[]>([]);
  const isDesktop = useDesktopLayout();
  const shellVisualViewport = useVisualViewport(!isDesktop);
  const effectiveMobileViewport = mobileViewport ?? { open: false };
  const shellViewportHeight = effectiveMobileViewport.open
    ? (effectiveMobileViewport.viewportHeight ?? shellVisualViewport?.height)
    : shellVisualViewport?.height;
  const shellViewportOffsetTop = effectiveMobileViewport.open
    ? (effectiveMobileViewport.viewportOffsetTop ??
      shellVisualViewport?.offsetTop ??
      0)
    : (shellVisualViewport?.offsetTop ?? 0);

  const stopRailAnimations = React.useCallback(() => {
    for (const animation of railAnimationsRef.current) animation.cancel();
    railAnimationsRef.current = [];
  }, []);

  const handleCollapsedChange = React.useCallback(
    (nextCollapsed: boolean) => {
      const chrome = desktopRailChromeRef.current;
      const content = desktopContentRef.current;
      if (chrome && content) {
        railFlipSnapshotRef.current = {
          chromeClipPath: getComputedStyle(chrome).clipPath,
          contentLeft: content.getBoundingClientRect().left,
        };
      }
      stopRailAnimations();
      setAnimateSidebarLabels(!nextCollapsed);
      onCollapsedChange(nextCollapsed);
    },
    [onCollapsedChange, stopRailAnimations],
  );

  React.useLayoutEffect(() => {
    const snapshot = railFlipSnapshotRef.current;
    railFlipSnapshotRef.current = undefined;
    if (!motionReady || resolvedMotion === "reduced" || skipAnimations) {
      stopRailAnimations();
      return;
    }

    const chrome = desktopRailChromeRef.current;
    const content = desktopContentRef.current;
    if (!snapshot || !chrome || !content) return;

    const options: KeyframeAnimationOptions = {
      duration: motionDurations.slow,
      easing: motionCssEasings.enter,
    };
    const animations: Animation[] = [];
    const contentDelta =
      snapshot.contentLeft - content.getBoundingClientRect().left;
    if (Math.abs(contentDelta) > 0.5) {
      animations.push(
        content.animate(
          [
            { transform: `translateX(${contentDelta}px)` },
            { transform: "translateX(0)" },
          ],
          options,
        ),
      );
    }

    const finalClipPath = getComputedStyle(chrome).clipPath;
    if (snapshot.chromeClipPath !== finalClipPath) {
      animations.push(
        chrome.animate(
          [{ clipPath: snapshot.chromeClipPath }, { clipPath: finalClipPath }],
          options,
        ),
      );
    }
    railAnimationsRef.current = animations;
    void Promise.allSettled(
      animations.map((animation) => animation.finished),
    ).then(() => {
      if (railAnimationsRef.current === animations) {
        railAnimationsRef.current = [];
      }
    });
  }, [
    collapsed,
    motionReady,
    resolvedMotion,
    skipAnimations,
    stopRailAnimations,
  ]);

  React.useEffect(() => stopRailAnimations, [stopRailAnimations]);

  const openSearch = React.useCallback(() => {
    if (document.activeElement instanceof HTMLElement) {
      searchReturnFocusRef.current = document.activeElement;
    }
    setSearchOpen(true);
  }, []);

  const handleSearchOpenChange = React.useCallback((nextOpen: boolean) => {
    setSearchOpen(nextOpen);
    if (nextOpen) return;
    const returnTarget = searchReturnFocusRef.current;
    searchReturnFocusRef.current = null;
    window.requestAnimationFrame(() => {
      if (returnTarget?.isConnected) returnTarget.focus();
      else mobileMenuTriggerRef.current?.focus();
    });
  }, []);

  React.useEffect(() => {
    function openSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (document.activeElement instanceof HTMLElement) {
          searchReturnFocusRef.current = document.activeElement;
        }
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", openSearch);
    return () => window.removeEventListener("keydown", openSearch);
  }, []);

  return (
    <div
      className="bg-canvas fixed inset-0 flex min-h-0 overflow-hidden [--workspace-sidebar-width:var(--layout-sidebar)] 2xl:[--workspace-sidebar-width:var(--layout-sidebar-wide)]"
      data-workspace-shell=""
      style={
        shellViewportHeight
          ? {
              height: `${shellViewportHeight}px`,
              top: 0,
              bottom: "auto",
              transform: `translateY(${shellViewportOffsetTop}px)`,
            }
          : undefined
      }
    >
      <div
        className={cn(
          "relative z-10 hidden shrink-0 lg:block",
          collapsed ? "w-16" : "w-[var(--workspace-sidebar-width)]",
        )}
        data-motion-rail-frame=""
      >
        <div
          aria-hidden="true"
          className="motion-rail-chrome border-line bg-sidebar pointer-events-none absolute inset-y-0 left-0 w-[var(--workspace-sidebar-width)] border-r"
          data-collapsed={collapsed}
          ref={desktopRailChromeRef}
        />
        <div className="relative z-10 h-full">
          <Sidebar
            activeConversationId={activeConversationId}
            activeDestination={activeDestination}
            actor={actor}
            animateLabels={animateSidebarLabels}
            billingUsage={billingUsage}
            collapsed={collapsed}
            conversations={conversations}
            controller={conversationController}
            currentConversation={currentConversation}
            hasNextPage={Boolean(conversationListQuery.hasNextPage)}
            isError={conversationListQuery.isError}
            isFetchingNextPage={conversationListQuery.isFetchingNextPage}
            onCollapsedChange={handleCollapsedChange}
            onDeleteConversation={(conversation, returnFocus) =>
              setDeleteTarget({ conversation, returnFocus })
            }
            onOpenAccount={() => openSettingsSection("account")}
            onOpenSettings={() => openSettingsSection("general")}
            onOpenUsage={() => openSettingsSection("usage")}
            onLoadMore={loadMoreConversations}
            onRequestMobileRename={(conversation, returnFocus) =>
              setRenameTarget({ conversation, returnFocus })
            }
            onRetry={retryConversations}
            onSearch={openSearch}
            onSignOut={onSignOut}
            signingOut={signingOut}
          />
        </div>
      </div>
      <Sheet onOpenChange={setMobileOpen} open={mobileOpen}>
        <SheetContent
          className="inset-0 h-dvh w-full max-w-none border-0 bg-[var(--color-bg-sidebar)] p-0 shadow-none focus:outline-none"
          closeGlyph={DismissIcon}
          closeLabel={t("navigation.closeMenu")}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            mobileSheetRef.current?.focus();
          }}
          ref={mobileSheetRef}
          side="left"
          tabIndex={-1}
        >
          <SheetTitle className="sr-only">
            {t("navigation.openMenu")}
          </SheetTitle>
          <MobileNavigation
            activeConversationId={activeConversationId}
            actor={actor}
            conversations={conversations}
            controller={conversationController}
            currentConversation={currentConversation}
            hasNextPage={Boolean(conversationListQuery.hasNextPage)}
            isError={conversationListQuery.isError}
            isFetchingNextPage={conversationListQuery.isFetchingNextPage}
            onDeleteConversation={(conversation, returnFocus) =>
              setDeleteTarget({ conversation, returnFocus })
            }
            onLoadMore={loadMoreConversations}
            onRequestMobileRename={(conversation, returnFocus) =>
              setRenameTarget({ conversation, returnFocus })
            }
            onInstall={() => {
              setMobileOpen(false);
              void installExperience.openInstallExperience();
            }}
            onSelect={() => setMobileOpen(false)}
            onRetry={retryConversations}
            onSearch={() => {
              setMobileOpen(false);
              openSearch();
            }}
            showInstall={installExperience.showInstallEntry}
          />
        </SheetContent>
      </Sheet>
      <div
        className="flex min-w-0 flex-1 flex-col"
        data-motion-rail-content=""
        ref={desktopContentRef}
      >
        {showMobileHeader ? (
          <header
            className={cn(
              "shrink-0 pt-[env(safe-area-inset-top)] lg:hidden",
              mobileHeaderDivider && "border-line border-b",
            )}
          >
            <div className="flex h-16 items-center px-3">
              {mobileHeaderLeading ?? (
                <IconButton
                  label={t("navigation.openMenu")}
                  onClick={() => setMobileOpen(true)}
                  ref={mobileMenuTriggerRef}
                  variant="ghost"
                >
                  <Icon glyph={MenuIcon} size={24} />
                </IconButton>
              )}
              <div className="mx-2 min-w-0 flex-1">{mobileHeaderCenter}</div>
              <div className="ml-auto shrink-0">{mobileHeaderTrailing}</div>
            </div>
          </header>
        ) : null}
        <main
          className="min-h-0 min-w-0 flex-1 overflow-x-clip overflow-y-auto overscroll-y-contain"
          data-scrollbar-gutter="stable"
          tabIndex={0}
        >
          {children}
        </main>
        {!suppressInstallPromotion && <InstallPromotion />}
        {(mobileBottomContent || showMobileBottomNavigation) && (
          <MobileBottomDock
            activeDestination={activeDestination}
            content={mobileBottomContent}
            keyboardOpen={effectiveMobileViewport.open}
            ref={mobileBottomRef ?? localMobileDockRef}
            showNavigation={showMobileBottomNavigation}
          />
        )}
      </div>
      <SettingsDialog />
      <InstallInstructionsDialog />
      <GlobalSearch
        conversations={conversations}
        onOpenChange={handleSearchOpenChange}
        open={searchOpen}
      />
      <ConversationActionDialogs
        controller={conversationController}
        deleteTarget={deleteTarget}
        onDeleteTargetChange={setDeleteTarget}
        onRenameTargetChange={setRenameTarget}
        renameTarget={renameTarget}
      />
    </div>
  );
}
