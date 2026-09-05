"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { IconButton } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { BackIcon } from "@/design-system/icons/semantic-icons";
import { useAuthSession, type Actor } from "@/features/authentication";
import { WorkspaceShell } from "@/features/workspace-shell";
import {
  currentAppLocation,
  useNavigationScrollRestorer,
  useWorkspaceNavigation,
} from "@/features/workspace-navigation";
import { PersonalActivityContainer } from "./containers";
import {
  parsePersonalActivityRange,
  serializePersonalActivityRange,
  type PersonalActivityRange,
} from "./personal-activity-search";

function PersonalActivityWorkspace({ actor }: { actor: Actor }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations("ResearchActivity");
  const accountT = useTranslations("AccountHub.actions");
  const { signOut } = useAuthSession();
  const navigation = useWorkspaceNavigation();
  const updateContextRoute = navigation.updateContextRoute;
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const contentRef = React.useRef<HTMLDivElement>(null);
  useNavigationScrollRestorer("personal-activity", { rootRef: contentRef });
  const range = React.useMemo(
    () =>
      parsePersonalActivityRange(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

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

  function handleRangeChange(nextRange: PersonalActivityRange) {
    const params = serializePersonalActivityRange(nextRange);
    const query = params.toString();
    updateContextRoute(
      (query ? `/me/activity?${query}` : "/me/activity") as Route,
    );
  }

  return (
    <WorkspaceShell
      activeDestination="me"
      actor={actor}
      collapsed={collapsed}
      mobileHeaderCenter={
        <h1 className="truncate text-center text-base font-semibold">
          {t("title")}
        </h1>
      }
      mobileHeaderLeading={
        <IconButton asChild label={accountT("back")} variant="ghost">
          <Link href="/me">
            <Icon glyph={BackIcon} size={24} />
          </Link>
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      signingOut={signingOut}
    >
      <div
        className="mx-auto w-full max-w-6xl px-4 py-6 pb-16 sm:px-8 sm:py-10 lg:px-12"
        ref={contentRef}
      >
        <header className="mb-8 hidden sm:block">
          <h1 className="text-3xl leading-10 font-semibold tracking-[-0.02em]">
            {t("title")}
          </h1>
          <p className="text-secondary mt-2 max-w-2xl text-sm leading-6">
            {t("description")}
          </p>
        </header>
        <PersonalActivityContainer
          onRangeChange={(nextRange) =>
            handleRangeChange(nextRange as PersonalActivityRange)
          }
          range={range}
        />
      </div>
    </WorkspaceShell>
  );
}

export function PersonalActivityPage() {
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("AccountHub.session");
  const session = useAuthSession();

  React.useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(
        `/login?returnTo=${encodeURIComponent(currentAppLocation(pathname))}`,
      );
    }
  }, [pathname, router, session.status]);

  if (session.status === "bootstrapping" || session.status === "anonymous") {
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
  return <PersonalActivityWorkspace actor={session.actor} />;
}
