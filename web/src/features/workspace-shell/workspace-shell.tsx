"use client";

import {
  AccountIcon,
  CollapseRailIcon,
  DocumentationIcon,
  ExpandRailIcon,
  ExternalLinkIcon,
  RepositoryIcon,
  SignOutIcon,
  MenuIcon,
  SettingsIcon,
  UsageIcon,
} from "@/design-system/icons/semantic-icons";
import {
  motionCssEasings,
  motionDurations,
} from "@/design-system/generated/motion-metadata";
import Link from "next/link";
import type { Route } from "next";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  keyboardFocusRing,
  SearchField,
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
import type { Actor } from "@/features/authentication";
import {
  formatDateOnly,
  SettingsDialog,
  useCurrentBillingUsage,
  useSettingsNavigation,
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
import { useShellVisualViewport } from "./use-shell-visual-viewport";

export type WorkspaceDestination = "ask" | "library" | "projects";

export type MobileViewportState = {
  open: boolean;
  viewportHeight?: number;
  viewportOffsetTop?: number;
};

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

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
  collapsed,
  glyph,
  href,
  label,
}: {
  collapsed: boolean;
  glyph: IconGlyph;
  href: string;
  label: string;
}) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center">
        <Icon glyph={glyph} size={20} tone="primary" />
      </span>
      {!collapsed && (
        <span className="settled-content-enter text-sidebar-label truncate">
          {label}
        </span>
      )}
      <NavigationPendingIndicator href={href} label={label} />
    </>
  );
}

function SidebarControl({
  collapsed,
  label,
  glyph,
  active,
  href,
  disabled,
  disabledHint,
  onSelect,
}: {
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
        "motion-control hover:bg-hover active:bg-pressed relative flex h-10 items-center gap-2 rounded-[var(--radius-lg)] font-medium",
        keyboardFocusRing,
        collapsed ? "w-10 justify-center" : "w-full px-2",
        active && "bg-hover",
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
        "motion-control flex h-10 items-center gap-2 rounded-[var(--radius-lg)] font-medium",
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
        <span className="settled-content-enter text-sidebar-label truncate">
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
  settingsTrigger = false,
  signingOut,
  onOpenAccount,
  onOpenSettings,
  onOpenUsage,
  onSignOut,
}: {
  actor: Actor;
  billingUsage: CurrentBillingUsageSummary;
  collapsed: boolean;
  settingsTrigger?: boolean;
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
          aria-label={
            settingsTrigger ? t("navigation.settings") : t("account.openMenu")
          }
          className={cn(
            "hover:bg-hover flex items-center",
            keyboardFocusRing,
            settingsTrigger
              ? "bg-surface size-12 justify-center rounded-full"
              : "rounded-[var(--radius-lg)]",
            !settingsTrigger && "h-14",
            !settingsTrigger &&
              (collapsed
                ? "ml-auto w-10 justify-center px-2"
                : "w-full gap-3 px-2"),
          )}
          type="button"
        >
          {settingsTrigger ? (
            <Icon glyph={SettingsIcon} size={20} tone="primary" />
          ) : (
            <>
              <span
                className={cn(
                  "bg-pressed grid shrink-0 place-items-center rounded-full font-medium",
                  collapsed ? "text-caption size-8" : "size-10 text-sm",
                )}
                data-account-avatar
              >
                {initial}
              </span>
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
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={collapsed || settingsTrigger ? "end" : "start"}
        className={cn(
          "rounded-[var(--radius-xl)]",
          collapsed || settingsTrigger
            ? "w-72"
            : "w-[max(var(--radix-dropdown-menu-trigger-width),18rem)]",
        )}
        side={collapsed && !settingsTrigger ? "right" : "top"}
        sideOffset={collapsed || settingsTrigger ? 8 : 4}
      >
        <DropdownMenuLabel className="flex items-center gap-3 px-2.5 py-3">
          <span
            className="bg-pressed text-foreground grid size-10 shrink-0 place-items-center rounded-full text-sm font-semibold"
            data-account-avatar
          >
            {initial}
          </span>
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

function MobileActorIdentity({ actor }: { actor: Actor }) {
  const name = actorName(actor);
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <span className="bg-pressed grid size-12 shrink-0 place-items-center rounded-full text-sm font-medium">
        {name.slice(0, 1).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-lg leading-6 font-semibold tracking-[-0.01em]">
          {name}
        </span>
        <span className="text-secondary block truncate text-sm leading-5">
          {actor.email}
        </span>
      </span>
    </div>
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

function MobileNavigation({
  actor,
  billingUsage,
  conversations,
  activeConversationId,
  signingOut,
  onOpenAccount,
  onOpenSettings,
  onOpenUsage,
  onSignOut,
  onSelect,
  controller,
  onDeleteConversation,
  onRequestMobileRename,
}: {
  actor: Actor;
  billingUsage: CurrentBillingUsageSummary;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  signingOut: boolean;
  onOpenAccount: () => void;
  onOpenSettings: () => void;
  onOpenUsage: () => void;
  onSignOut: () => Promise<void>;
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
}) {
  const t = useTranslations("WorkspaceShell");
  const [query, setQuery] = React.useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matching = normalizedQuery
    ? conversations.filter((conversation) =>
        conversation.title.toLocaleLowerCase().includes(normalizedQuery),
      )
    : conversations;
  const pinned = matching.filter((item) => item.pinned_at).slice(0, 3);
  const recent = matching.filter((item) => !item.pinned_at).slice(0, 12);

  return (
    <aside className="flex h-full flex-col overflow-hidden bg-[var(--color-bg-sidebar)] pt-[env(safe-area-inset-top)]">
      <div className="flex min-h-20 shrink-0 items-center px-4 pr-16">
        <MobileActorIdentity actor={actor} />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto px-3 pb-4"
        data-scrollbar-gutter="stable"
      >
        <MobileConversationGroup
          activeConversationId={activeConversationId}
          items={pinned}
          controller={controller}
          onDelete={onDeleteConversation}
          onRequestMobileRename={onRequestMobileRename}
          onSelect={onSelect}
          title={t("sidebar.pinned")}
        />
        <MobileConversationGroup
          activeConversationId={activeConversationId}
          items={recent}
          controller={controller}
          onDelete={onDeleteConversation}
          onRequestMobileRename={onRequestMobileRename}
          onSelect={onSelect}
          title={t("sidebar.conversations")}
        />
        {matching.length === 0 && (
          <p className="text-secondary px-3 py-8 text-center text-sm">
            {normalizedQuery ? t("sidebar.noMatches") : t("sidebar.empty")}
          </p>
        )}
      </div>
      <div
        className="shrink-0 bg-[var(--color-bg-sidebar)] px-3 pt-2 pb-[max(var(--space-3),env(safe-area-inset-bottom))]"
        data-testid="mobile-navigation-tools"
      >
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <SearchField
              aria-label={t("navigation.searchConversations")}
              className="bg-surface h-12 rounded-full border-transparent text-base"
              onChange={(event) => setQuery(event.currentTarget.value)}
              placeholder={t("navigation.searchConversations")}
              value={query}
            />
          </div>
          <AccountMenu
            actor={actor}
            billingUsage={billingUsage}
            collapsed={false}
            onOpenAccount={onOpenAccount}
            onOpenSettings={onOpenSettings}
            onOpenUsage={onOpenUsage}
            onSignOut={onSignOut}
            settingsTrigger
            signingOut={signingOut}
          />
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
      className="grid h-14 shrink-0 grid-cols-3 lg:hidden"
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
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-0 bottom-full left-0 h-5 bg-[linear-gradient(to_top,var(--color-bg-canvas),transparent)]"
      />
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
  actor,
  billingUsage,
  conversations,
  activeConversationId,
  activeDestination,
  collapsed,
  signingOut,
  onCollapsedChange,
  onOpenAccount,
  onOpenSettings,
  onOpenUsage,
  onSignOut,
  onSelect,
  controller,
  onDeleteConversation,
  onRequestMobileRename,
}: {
  actor: Actor;
  billingUsage: CurrentBillingUsageSummary;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  activeDestination: WorkspaceDestination;
  collapsed: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onOpenAccount: () => void;
  onOpenSettings: () => void;
  onOpenUsage: () => void;
  onSignOut: () => Promise<void>;
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
  const pinned = conversations.filter((item) => item.pinned_at).slice(0, 3);
  const recent = conversations.filter((item) => !item.pinned_at).slice(0, 7);

  return (
    <TooltipProvider delayDuration={250}>
      <aside
        aria-label={t("navigation.sidebar")}
        className={cn(
          "flex h-full shrink-0 flex-col overflow-hidden px-3 pt-3 pb-[max(var(--space-1),env(safe-area-inset-bottom))]",
          collapsed ? "w-16" : "w-[var(--layout-sidebar)]",
        )}
      >
        <div className="relative mb-3 flex h-10 shrink-0 items-center justify-end">
          <Link
            aria-hidden={collapsed || undefined}
            className={cn(
              "motion-control text-ui absolute left-1 font-semibold tracking-[-0.003em] whitespace-nowrap",
              collapsed && "pointer-events-none opacity-0",
            )}
            href="/"
            tabIndex={collapsed ? -1 : undefined}
          >
            Scholens
          </Link>
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
        <nav
          className={cn("grid gap-0.5", collapsed && "justify-items-end")}
          aria-label={t("navigation.openMenu")}
        >
          <SidebarControl
            active={activeDestination === "ask" && !activeConversationId}
            collapsed={collapsed}
            glyph={NewConversationIcon}
            href="/"
            label={t("navigation.newChat")}
            onSelect={onSelect}
          />
          <SidebarControl
            active={activeDestination === "library"}
            collapsed={collapsed}
            glyph={LibraryIcon}
            href="/library"
            label={t("navigation.library")}
          />
          <SidebarControl
            active={activeDestination === "projects"}
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
            <ConversationGroup
              activeConversationId={activeConversationId}
              items={pinned}
              controller={controller}
              onDelete={onDeleteConversation}
              onRequestMobileRename={onRequestMobileRename}
              onSelect={onSelect}
              title={t("sidebar.pinned")}
            />
            <div className={pinned.length > 0 ? "mt-2" : undefined}>
              <ConversationGroup
                activeConversationId={activeConversationId}
                items={recent}
                controller={controller}
                onDelete={onDeleteConversation}
                onRequestMobileRename={onRequestMobileRename}
                onSelect={onSelect}
                title={t("sidebar.recent")}
              />
            </div>
            {pinned.length === 0 && recent.length === 0 && (
              <p className="text-secondary px-2 py-1 text-xs leading-5">
                {t("sidebar.empty")}
              </p>
            )}
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
  conversations,
  activeConversationId,
  activeDestination,
  collapsed,
  signingOut,
  onCollapsedChange,
  onSignOut,
  mobileHeaderLeading,
  mobileHeaderCenter,
  mobileHeaderTrailing,
  mobileBottomContent,
  mobileBottomRef,
  mobileViewport,
  showMobileBottomNavigation = true,
  children,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  activeDestination: WorkspaceDestination;
  collapsed: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onSignOut: () => Promise<void>;
  mobileHeaderLeading?: React.ReactNode;
  mobileHeaderCenter?: React.ReactNode;
  mobileHeaderTrailing?: React.ReactNode;
  mobileBottomContent?: React.ReactNode;
  mobileBottomRef?: React.Ref<HTMLDivElement>;
  mobileViewport?: MobileViewportState;
  showMobileBottomNavigation?: boolean;
  children: React.ReactNode;
}) {
  const t = useTranslations("WorkspaceShell");
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [deleteTarget, setDeleteTarget] =
    React.useState<ConversationDialogTarget>();
  const [renameTarget, setRenameTarget] =
    React.useState<ConversationDialogTarget>();
  const billingUsage = useCurrentBillingUsage();
  const conversationController = useConversationListController({
    activeConversationId,
  });
  const { setSection: setSettingsSection } = useSettingsNavigation();
  const {
    ready: motionReady,
    resolved: resolvedMotion,
    skipAnimations,
  } = useMotionPreference();
  const mobileSheetRef = React.useRef<HTMLDivElement>(null);
  const localMobileDockRef = React.useRef<HTMLDivElement>(null);
  const desktopRailChromeRef = React.useRef<HTMLDivElement>(null);
  const desktopContentRef = React.useRef<HTMLDivElement>(null);
  const railFlipSnapshotRef = React.useRef<RailFlipSnapshot | undefined>(
    undefined,
  );
  const railAnimationsRef = React.useRef<Animation[]>([]);
  const isDesktop = useDesktopLayout();
  const shellVisualViewport = useShellVisualViewport(!isDesktop);
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

  return (
    <div
      className="bg-canvas fixed inset-0 flex min-h-0 overflow-hidden"
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
          collapsed ? "w-16" : "w-[var(--layout-sidebar)]",
        )}
        data-motion-rail-frame=""
      >
        <div
          aria-hidden="true"
          className="motion-rail-chrome border-line bg-canvas pointer-events-none absolute inset-y-0 left-0 w-[var(--layout-sidebar)] border-r"
          data-collapsed={collapsed}
          ref={desktopRailChromeRef}
        />
        <div className="relative z-10 h-full">
          <Sidebar
            activeConversationId={activeConversationId}
            activeDestination={activeDestination}
            actor={actor}
            billingUsage={billingUsage}
            collapsed={collapsed}
            conversations={conversations}
            controller={conversationController}
            onCollapsedChange={handleCollapsedChange}
            onDeleteConversation={(conversation, returnFocus) =>
              setDeleteTarget({ conversation, returnFocus })
            }
            onOpenAccount={() => setSettingsSection("account")}
            onOpenSettings={() => setSettingsSection("general")}
            onOpenUsage={() => setSettingsSection("usage")}
            onRequestMobileRename={(conversation, returnFocus) =>
              setRenameTarget({ conversation, returnFocus })
            }
            onSignOut={onSignOut}
            signingOut={signingOut}
          />
        </div>
      </div>
      <Sheet onOpenChange={setMobileOpen} open={mobileOpen}>
        <SheetContent
          className="inset-0 h-dvh w-full max-w-none border-0 bg-[var(--color-bg-sidebar)] p-0 shadow-none focus:outline-none"
          closeGlyph={ExpandRailIcon}
          closeLabel={t("navigation.closeMenu")}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            mobileSheetRef.current?.focus();
          }}
          ref={mobileSheetRef}
          tabIndex={-1}
        >
          <SheetTitle className="sr-only">
            {t("navigation.openMenu")}
          </SheetTitle>
          <MobileNavigation
            activeConversationId={activeConversationId}
            actor={actor}
            billingUsage={billingUsage}
            conversations={conversations}
            controller={conversationController}
            onDeleteConversation={(conversation, returnFocus) =>
              setDeleteTarget({ conversation, returnFocus })
            }
            onOpenAccount={() => {
              setMobileOpen(false);
              setSettingsSection("account");
            }}
            onOpenSettings={() => {
              setMobileOpen(false);
              setSettingsSection("general");
            }}
            onOpenUsage={() => {
              setMobileOpen(false);
              setSettingsSection("usage");
            }}
            onRequestMobileRename={(conversation, returnFocus) =>
              setRenameTarget({ conversation, returnFocus })
            }
            onSelect={() => setMobileOpen(false)}
            onSignOut={onSignOut}
            signingOut={signingOut}
          />
        </SheetContent>
      </Sheet>
      <div
        className="flex min-w-0 flex-1 flex-col"
        data-motion-rail-content=""
        ref={desktopContentRef}
      >
        <header className="border-line shrink-0 border-b pt-[env(safe-area-inset-top)] lg:hidden">
          <div className="flex h-16 items-center px-3">
            {mobileHeaderLeading ?? (
              <IconButton
                label={t("navigation.openMenu")}
                onClick={() => setMobileOpen(true)}
                variant="ghost"
              >
                <Icon glyph={MenuIcon} size={24} />
              </IconButton>
            )}
            <div className="mx-2 min-w-0 flex-1">{mobileHeaderCenter}</div>
            <div className="ml-auto shrink-0">{mobileHeaderTrailing}</div>
          </div>
        </header>
        <main
          className="min-h-0 min-w-0 flex-1 overflow-x-clip overflow-y-auto overscroll-y-contain"
          data-scrollbar-gutter="stable"
          tabIndex={0}
        >
          {children}
        </main>
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
