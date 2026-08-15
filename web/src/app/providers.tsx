"use client";

import { ThemeProvider } from "@/design-system/theme/theme-provider";
import { MotionProvider } from "@/design-system/motion";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/features/authentication";
import { QueryProvider } from "@/lib/query/query-provider";
import { useTranslations } from "next-intl";

export function Providers({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const t = useTranslations("Common.actions");
  return (
    <ThemeProvider>
      <MotionProvider>
        <QueryProvider>
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
