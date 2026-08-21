import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";

import { Providers } from "@/app/providers";
import { defaultThemeName } from "@/design-system/generated/theme-metadata";
import { motionInitializationScript } from "@/design-system/motion/motion-script";
import { themeInitializationScript } from "@/design-system/theme/theme-script";
import { localeDirection, type AppLocale } from "@/i18n/config";
import { formats } from "@/i18n/formats";
import "@/styles/globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("title"), description: t("description") };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = (await getLocale()) as AppLocale;
  const messages = await getMessages();

  return (
    <html
      data-color-scheme="light"
      data-motion="full"
      data-motion-preference="system"
      data-theme={defaultThemeName}
      dir={localeDirection(locale)}
      lang={locale}
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: themeInitializationScript }}
        />
        <script
          dangerouslySetInnerHTML={{ __html: motionInitializationScript }}
        />
      </head>
      <body className={geist.variable}>
        <NextIntlClientProvider
          formats={formats}
          locale={locale}
          messages={messages}
          now={new Date()}
          timeZone="UTC"
        >
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
