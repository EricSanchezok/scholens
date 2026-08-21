import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";

import { Providers } from "@/app/providers";
import { defaultThemeName } from "@/design-system/generated/theme-metadata";
import { motionInitializationScript } from "@/design-system/motion/motion-script";
import { themeInitializationScript } from "@/design-system/theme/theme-script";
import { metadataColors } from "@/design-system/generated/color-metadata";
import { localeDirection, type AppLocale } from "@/i18n/config";
import { formats } from "@/i18n/formats";
import { PRODUCTION_APP_ORIGIN } from "@/lib/product";
import "@/styles/globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  const title = t("title");
  const description = t("description");
  return {
    applicationName: "Scholens",
    description,
    icons: {
      other: [
        {
          color: metadataColors.brandInk,
          rel: "mask-icon",
          url: "/brand/safari-pinned-tab.svg",
        },
      ],
    },
    manifest: "/manifest.webmanifest",
    metadataBase: new URL(PRODUCTION_APP_ORIGIN),
    openGraph: {
      description,
      images: [
        {
          alt: "Scholens raven",
          height: 630,
          url: "/opengraph-image.png",
          width: 1200,
        },
      ],
      siteName: "Scholens",
      title,
      type: "website",
    },
    title,
    twitter: {
      card: "summary_large_image",
      description,
      images: ["/opengraph-image.png"],
      title,
    },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    {
      color: metadataColors.canvasLight,
      media: "(prefers-color-scheme: light)",
    },
    {
      color: metadataColors.canvasDark,
      media: "(prefers-color-scheme: dark)",
    },
  ],
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
