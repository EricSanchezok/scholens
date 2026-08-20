"use client";

import { ThemeProvider } from "@/design-system/theme/theme-provider";
import { MotionProvider } from "@/design-system/motion/motion-provider";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/features/authentication";
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
        <QueryProvider>
          <WebPerformanceReporter />
          <AuthProvider>
            <ToastProvider dismissLabel={t("dismiss")}>
              {children}
            </ToastProvider>
          </AuthProvider>
        </QueryProvider>
      </MotionProvider>
    </ThemeProvider>
  );
}
