"use client";

import {
  FastArrowLeft,
  FastArrowRight,
  LogOut,
  Menu,
  Settings,
} from "iconoir-react";
import Link from "next/link";
import type { Route } from "next";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
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
import { useTheme } from "@/design-system/theme/theme-provider";
import type { Actor } from "@/features/authentication";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import {
  AskIcon,
  LibraryIcon,
  NewConversationIcon,
  ProjectIcon,
} from "./icons";

export type WorkspaceDestination = "ask" | "library" | "projects";

export type MobileViewportState = {
  open: boolean;
  viewportHeight?: number;
  viewportOffsetTop?: number;
};

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

function actorName(actor: Actor) {
  return actor.display_name?.trim() || actor.email.split("@")[0] || actor.email;
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
      aria-label={collapsed ? accessibleLabel : undefined}
      className={cn(
        "hover:bg-hover flex h-10 items-center gap-2 rounded-[var(--radius-md)] font-medium transition-colors",
        keyboardFocusRing,
        collapsed ? "w-10 justify-center" : "w-full px-2",
        active && "bg-hover",
      )}
      href={href as Route}
      onClick={onSelect}
    >
      <span className="grid size-5 shrink-0 place-items-center">
        <Icon glyph={glyph} size={16} tone="primary" />
      </span>
      {!collapsed && (
        <span className="text-sidebar-label truncate">{label}</span>
      )}
    </Link>
  ) : (
    <button
      aria-disabled={disabled || undefined}
      aria-label={disabled || collapsed ? accessibleLabel : undefined}
      className={cn(
        "flex h-10 items-center gap-2 rounded-[var(--radius-md)] font-medium",
        keyboardFocusRing,
        collapsed ? "w-10 justify-center" : "w-full px-2",
        disabled ? "text-secondary cursor-not-allowed" : "hover:bg-hover",
      )}
      onClick={disabled ? undefined : onSelect}
      type="button"
    >
      <span className="grid size-5 shrink-0 place-items-center">
        <Icon glyph={glyph} size={16} tone="secondary" />
      </span>
      {!collapsed && (
        <span className="text-sidebar-label truncate">{label}</span>
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
}: {
  title: string;
  items: ConversationSummary[];
  activeConversationId?: string;
  onSelect?: () => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="grid gap-0.5">
      <div className="text-secondary flex h-6 items-center px-2 text-xs font-medium">
        {title}
      </div>
      {items.map((conversation) => (
        <Link
          aria-current={
            activeConversationId === conversation.id ? "page" : undefined
          }
          className={cn(
            "text-sidebar-label hover:bg-hover flex h-8 min-w-0 items-center gap-2 rounded-[var(--radius-md)] px-2",
            keyboardFocusRing,
            activeConversationId === conversation.id && "bg-hover",
          )}
          href={`/?conversation=${conversation.id}`}
          key={conversation.id}
          onClick={onSelect}
        >
          {conversation.pinned_at && (
            <Icon glyph={AskIcon} size={20} tone="secondary" />
          )}
          <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
          {conversation.scope_label && (
            <span className="text-caption text-secondary max-w-[4.5rem] truncate">
              {conversation.scope_label}
            </span>
          )}
        </Link>
      ))}
    </section>
  );
}

function AccountMenu({
  actor,
  collapsed,
  settingsTrigger = false,
  signingOut,
  onSignOut,
}: {
  actor: Actor;
  collapsed: boolean;
  settingsTrigger?: boolean;
  signingOut: boolean;
  onSignOut: () => Promise<void>;
}) {
  const t = useTranslations("WorkspaceShell");
  const { preference, setColorSchemePreference } = useTheme();
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
              : "rounded-[var(--radius-md)]",
            !settingsTrigger && "h-12",
            !settingsTrigger &&
              (collapsed
                ? "ml-auto w-10 justify-center px-2"
                : "w-full gap-2 px-1"),
          )}
          type="button"
        >
          {settingsTrigger ? (
            <Icon glyph={Settings} size={20} tone="primary" />
          ) : (
            <>
              <span
                className={cn(
                  "bg-pressed text-caption grid shrink-0 place-items-center rounded-full font-medium",
                  collapsed ? "size-6" : "size-5",
                )}
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
          "shadow-overlay",
          collapsed || settingsTrigger
            ? "w-64"
            : "w-[var(--radix-dropdown-menu-trigger-width)]",
        )}
        side={collapsed && !settingsTrigger ? "right" : "top"}
        sideOffset={collapsed || settingsTrigger ? 8 : 4}
      >
        <DropdownMenuLabel className="flex items-center gap-2.5 px-2 py-2.5">
          <span className="bg-pressed text-foreground grid size-8 shrink-0 place-items-center rounded-full text-xs font-medium">
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
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <Icon glyph={Settings} size={16} tone="secondary" />
          {t("account.settings")}
        </DropdownMenuItem>
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("account.appearance")}</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            onValueChange={(value) =>
              setColorSchemePreference(value as "light" | "dark" | "system")
            }
            value={preference}
          >
            <DropdownMenuRadioItem value="light">
              {t("account.light")}
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark">
              {t("account.dark")}
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system">
              {t("account.system")}
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={signingOut}
          onSelect={() => void onSignOut()}
        >
          <Icon glyph={LogOut} size={16} tone="secondary" />
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
}: {
  activeConversationId?: string;
  items: ConversationSummary[];
  onSelect: () => void;
  title: string;
}) {
  const format = useFormatter();
  if (items.length === 0) return null;
  return (
    <section className="grid gap-1">
      <h2 className="text-secondary px-3 pt-4 pb-1 text-sm font-medium">
        {title}
      </h2>
      {items.map((conversation) => (
        <Link
          aria-current={
            activeConversationId === conversation.id ? "page" : undefined
          }
          className={cn(
            "hover:bg-hover flex min-h-16 min-w-0 items-center rounded-[var(--radius-lg)] px-3 py-2",
            keyboardFocusRing,
            activeConversationId === conversation.id && "bg-surface",
          )}
          href={`/?conversation=${conversation.id}`}
          key={conversation.id}
          onClick={onSelect}
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-base leading-6">
              {conversation.title}
            </span>
            <span className="text-secondary block truncate text-xs leading-5">
              {format.relativeTime(new Date(conversation.updated_at))}
              {conversation.scope_label && ` · ${conversation.scope_label}`}
            </span>
          </span>
        </Link>
      ))}
    </section>
  );
}

function MobileNavigation({
  actor,
  conversations,
  activeConversationId,
  signingOut,
  onSignOut,
  onSelect,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  signingOut: boolean;
  onSignOut: () => Promise<void>;
  onSelect: () => void;
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
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        <MobileConversationGroup
          activeConversationId={activeConversationId}
          items={pinned}
          onSelect={onSelect}
          title={t("sidebar.pinned")}
        />
        <MobileConversationGroup
          activeConversationId={activeConversationId}
          items={recent}
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
            collapsed={false}
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

function MobileTabBar({
  activeDestination,
}: {
  activeDestination: WorkspaceDestination;
}) {
  const t = useTranslations("WorkspaceShell.navigation");
  const itemClassName = cn(
    "flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[var(--radius-md)] px-1 text-xs font-medium",
    keyboardFocusRing,
  );

  return (
    <nav
      aria-label={t("primary")}
      className="grid h-14 shrink-0 grid-cols-3 lg:hidden"
      data-testid="mobile-tab-bar"
    >
      <Link
        aria-current={activeDestination === "ask" ? "page" : undefined}
        className={cn(
          itemClassName,
          activeDestination === "ask" ? "text-foreground" : "text-secondary",
        )}
        href="/"
      >
        <span
          className={cn(
            "grid size-8 place-items-center rounded-full",
            activeDestination === "ask" && "bg-primary",
          )}
          data-selected-indicator={
            activeDestination === "ask" ? true : undefined
          }
        >
          <Icon
            glyph={AskIcon}
            size={20}
            tone={activeDestination === "ask" ? "inverse" : "secondary"}
          />
        </span>
        <span className={activeDestination === "ask" ? "font-semibold" : ""}>
          {t("ask")}
        </span>
      </Link>
      <Link
        aria-current={activeDestination === "library" ? "page" : undefined}
        className={cn(
          itemClassName,
          activeDestination === "library"
            ? "text-foreground"
            : "text-secondary",
        )}
        href={"/library" as Route}
      >
        <span
          className={cn(
            "grid size-8 place-items-center rounded-full",
            activeDestination === "library" && "bg-primary",
          )}
          data-selected-indicator={
            activeDestination === "library" ? true : undefined
          }
        >
          <Icon
            glyph={LibraryIcon}
            size={20}
            tone={activeDestination === "library" ? "inverse" : "secondary"}
          />
        </span>
        <span
          className={activeDestination === "library" ? "font-semibold" : ""}
        >
          {t("library")}
        </span>
      </Link>
      <button
        aria-label={`${t("projects")}. ${t("comingSoon")}`}
        className={cn(itemClassName, "text-muted")}
        disabled
        type="button"
      >
        <span className="grid size-8 place-items-center">
          <Icon glyph={ProjectIcon} size={20} tone="secondary" />
        </span>
        <span>{t("projects")}</span>
      </button>
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
        !keyboardOpen && "pb-[env(safe-area-inset-bottom)]",
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
  conversations,
  activeConversationId,
  activeDestination,
  collapsed,
  signingOut,
  onCollapsedChange,
  onSignOut,
  onSelect,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  activeDestination: WorkspaceDestination;
  collapsed: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onSignOut: () => Promise<void>;
  onSelect?: () => void;
}) {
  const t = useTranslations("WorkspaceShell");
  const pinned = conversations.filter((item) => item.pinned_at).slice(0, 3);
  const recent = conversations.filter((item) => !item.pinned_at).slice(0, 7);

  return (
    <TooltipProvider delayDuration={250}>
      <aside
        className={cn(
          "border-line bg-sidebar flex h-full shrink-0 flex-col overflow-hidden border-r px-3 pt-3 pb-[max(var(--space-1),env(safe-area-inset-bottom))] transition-[width] duration-200 ease-out motion-reduce:transition-none",
          collapsed ? "w-16" : "w-[var(--layout-sidebar)]",
        )}
      >
        <div className="relative mb-3 flex h-10 shrink-0 items-center justify-end">
          <Link
            aria-hidden={collapsed || undefined}
            className={cn(
              "text-ui absolute left-1 font-semibold tracking-[-0.003em] whitespace-nowrap transition-opacity duration-150 motion-reduce:transition-none",
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
              glyph={collapsed ? FastArrowRight : FastArrowLeft}
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
            collapsed={collapsed}
            disabled
            disabledHint={t("navigation.comingSoon")}
            glyph={ProjectIcon}
            label={t("navigation.projects")}
          />
        </nav>
        {!collapsed && (
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
            <ConversationGroup
              activeConversationId={activeConversationId}
              items={pinned}
              onSelect={onSelect}
              title={t("sidebar.pinned")}
            />
            <div className={pinned.length > 0 ? "mt-2" : undefined}>
              <ConversationGroup
                activeConversationId={activeConversationId}
                items={recent}
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
          collapsed={collapsed}
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
  const mobileSheetRef = React.useRef<HTMLDivElement>(null);
  const localMobileDockRef = React.useRef<HTMLDivElement>(null);
  const effectiveMobileViewport = mobileViewport ?? { open: false };

  return (
    <div
      className="bg-canvas fixed inset-0 flex min-h-0 overflow-hidden"
      style={
        effectiveMobileViewport.viewportHeight
          ? {
              height: `${effectiveMobileViewport.viewportHeight}px`,
              transform: `translateY(${effectiveMobileViewport.viewportOffsetTop ?? 0}px)`,
            }
          : undefined
      }
    >
      <div className="hidden lg:block">
        <Sidebar
          activeConversationId={activeConversationId}
          activeDestination={activeDestination}
          actor={actor}
          collapsed={collapsed}
          conversations={conversations}
          onCollapsedChange={onCollapsedChange}
          onSignOut={onSignOut}
          signingOut={signingOut}
        />
      </div>
      <Sheet onOpenChange={setMobileOpen} open={mobileOpen}>
        <SheetContent
          className="inset-0 h-dvh w-full max-w-none border-0 bg-[var(--color-bg-sidebar)] p-0 shadow-none focus:outline-none"
          closeGlyph={FastArrowRight}
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
            conversations={conversations}
            onSelect={() => setMobileOpen(false)}
            onSignOut={onSignOut}
            signingOut={signingOut}
          />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-line shrink-0 border-b pt-[env(safe-area-inset-top)] lg:hidden">
          <div className="flex h-16 items-center px-3">
            {mobileHeaderLeading ?? (
              <IconButton
                label={t("navigation.openMenu")}
                onClick={() => setMobileOpen(true)}
                variant="ghost"
              >
                <Icon glyph={Menu} size={24} />
              </IconButton>
            )}
            <div className="mx-2 min-w-0 flex-1">{mobileHeaderCenter}</div>
            <div className="ml-auto shrink-0">{mobileHeaderTrailing}</div>
          </div>
        </header>
        <main
          className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain"
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
    </div>
  );
}
