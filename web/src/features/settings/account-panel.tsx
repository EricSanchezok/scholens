"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback } from "@/components/feedback";
import { Button, LinkButton } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { LinkIcon, SignOutIcon } from "@/design-system/icons/semantic-icons";
import { useAuthSession } from "@/features/authentication";
import { SettingsPanelHeader } from "./settings-layout";

function actorName(displayName: string | null | undefined, email: string) {
  return displayName?.trim() || email.split("@")[0] || email;
}

export function AccountPanel({
  accountCenterUrl,
}: {
  accountCenterUrl?: string;
}) {
  const t = useTranslations("Settings");
  const router = useRouter();
  const { actor, signOut } = useAuthSession();
  const [signingOut, setSigningOut] = React.useState(false);
  const destination = accountCenterUrl || "https://myaccount.sanchezcloud.net";

  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
    } catch {
      // AuthSession clears local credentials even if remote logout is unavailable.
    } finally {
      router.replace("/login");
      setSigningOut(false);
    }
  }

  return (
    <div>
      <SettingsPanelHeader
        description={t("account.description")}
        title={t("account.title")}
      />
      {actor ? (
        <div className="max-w-2xl">
          <section className="py-2" aria-labelledby="account-profile-title">
            <h3 className="sr-only" id="account-profile-title">
              {t("account.profile")}
            </h3>
            <div className="flex flex-col items-start gap-5 sm:flex-row sm:items-center">
              <span className="bg-primary text-primary-foreground grid size-16 shrink-0 place-items-center rounded-full text-xl font-semibold">
                {actorName(actor.display_name, actor.email)
                  .slice(0, 1)
                  .toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xl font-semibold tracking-[-0.015em]">
                  {actorName(actor.display_name, actor.email)}
                </p>
                <p className="text-secondary mt-1 truncate text-sm">
                  {actor.email}
                </p>
              </div>
            </div>
            <div className="bg-subtle mt-7 rounded-[var(--radius-xl)] px-5 py-5">
              <p className="text-secondary max-w-xl text-sm leading-6">
                {t("account.profileDescription")}
              </p>
              <LinkButton
                className="mt-4"
                href={destination}
                rel="noopener noreferrer"
                target="_blank"
                variant="secondary"
              >
                {t("account.openAccountCenter")}
                <Icon glyph={LinkIcon} size={16} />
              </LinkButton>
            </div>
          </section>

          <section className="border-line-subtle mt-9 flex flex-col gap-4 border-t pt-7 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold">{t("account.session")}</h3>
              <p className="text-secondary mt-1 max-w-xl text-sm leading-5">
                {t("account.sessionDescription")}
              </p>
            </div>
            <Button
              className="shrink-0 self-start"
              loading={signingOut}
              onClick={() => void handleSignOut()}
              variant="secondary"
            >
              <Icon glyph={SignOutIcon} size={16} />
              {signingOut ? t("account.signingOut") : t("account.signOut")}
            </Button>
          </section>
        </div>
      ) : (
        <AsyncFeedback presentation="inline" state="loading" />
      )}
    </div>
  );
}
