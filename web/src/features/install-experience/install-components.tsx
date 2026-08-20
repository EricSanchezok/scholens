"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  IconButton,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  DismissIcon,
  InstallAppIcon,
} from "@/design-system/icons/semantic-icons";
import { useInstallExperience } from "./install-experience";

const instructionSteps = ["step1", "step2", "step3"] as const;

export function InstallPromotion() {
  const t = useTranslations("InstallExperience.promotion");
  const experience = useInstallExperience();
  const { markPromotionShown, promotionVisible } = experience;

  React.useEffect(() => {
    if (promotionVisible) markPromotionShown();
  }, [markPromotionShown, promotionVisible]);

  if (!promotionVisible) return null;

  return (
    <aside
      aria-label={t("title")}
      className="bg-elevated shadow-raised mx-3 mb-2 grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-[var(--radius-xl)] p-3 lg:hidden"
    >
      <span className="bg-subtle grid size-10 shrink-0 place-items-center rounded-[var(--radius-lg)]">
        <Icon glyph={InstallAppIcon} size={20} tone="primary" />
      </span>
      <span className="min-w-0">
        <strong className="block text-sm font-medium">{t("title")}</strong>
        <span className="text-secondary mt-0.5 block text-xs leading-5">
          {t("description")}
        </span>
      </span>
      <IconButton
        className="col-start-3 row-start-1"
        label={t("dismiss")}
        onClick={experience.dismissPromotion}
        variant="ghost"
      >
        <Icon glyph={DismissIcon} size={20} tone="secondary" />
      </IconButton>
      <Button
        className="col-start-2 row-start-2 justify-self-start"
        onClick={() => void experience.openInstallExperience()}
        size="sm"
      >
        {t("install")}
      </Button>
    </aside>
  );
}

export function InstallInstructionsDialog() {
  const t = useTranslations("InstallExperience.instructions");
  const experience = useInstallExperience();
  const kind = experience.instructionKind ?? "android";

  return (
    <Dialog
      onOpenChange={experience.setInstructionsOpen}
      open={experience.instructionsOpen}
    >
      <DialogContent closeLabel={t("close")} placement="responsive-bottom">
        <DialogHeader>
          <DialogTitle>{t(`${kind}.title`)}</DialogTitle>
          <DialogDescription>{t(`${kind}.description`)}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <ol className="grid gap-4">
            {instructionSteps.map((step, index) => (
              <li
                className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3"
                key={step}
              >
                <span className="bg-subtle grid size-8 place-items-center rounded-full text-sm font-semibold tabular-nums">
                  {index + 1}
                </span>
                <p className="pt-1 text-sm leading-6">{t(`${kind}.${step}`)}</p>
              </li>
            ))}
          </ol>
        </DialogBody>
        <DialogFooter>
          <Button
            className="w-full sm:w-auto"
            onClick={() => experience.setInstructionsOpen(false)}
            variant="secondary"
          >
            {t("done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
