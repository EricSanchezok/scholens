"use client";

import { ThemeProvider } from "@/design-system/theme";
import { MotionProvider } from "@/design-system/motion/motion-provider";
import { ScrollbarActivity } from "@/design-system/scrollbars/scrollbar-activity";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/features/authentication";
import { InstallExperienceProvider } from "@/features/install-experience";
import { QueryProvider } from "@/lib/query/query-provider";
import { useTranslations } from "next-intl";
import { WebPerformanceReporter } from "@/lib/observability/web-vitals-reporter";

export function Providers({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const t = useTranslations("Common.actions");
  return (
    <ThemeProvider>
      <MotionProvider>
        <ScrollbarActivity />
        <QueryProvider>
          <WebPerformanceReporter />
          <InstallExperienceProvider>
            <AuthProvider>
              <ToastProvider dismissLabel={t("dismiss")}>
                {children}
              </ToastProvider>
            </AuthProvider>
          </InstallExperienceProvider>
        </QueryProvider>
      </MotionProvider>
    </ThemeProvider>
  );
}
