import type { Preview } from "@storybook/nextjs-vite";
import { initialize, mswLoader } from "msw-storybook-addon";
import { NextIntlClientProvider } from "next-intl";
import { useLayoutEffect } from "react";

import { localeDirection, type AppLocale } from "../src/i18n/config";
import {
  defaultThemeName,
  themeNames,
  type ThemeName,
} from "../src/design-system/generated/theme-metadata";
import {
  MotionProvider,
  MotionRuntimeProvider,
  type MotionPreference,
} from "../src/design-system/motion";
import { ScrollbarActivity } from "../src/design-system/scrollbars/scrollbar-activity";
import { ThemeProvider } from "../src/design-system/theme";
import { formats } from "../src/i18n/formats";
import en from "../src/i18n/messages/en.json";
import zhCN from "../src/i18n/messages/zh-CN.json";
import { QueryProvider } from "../src/lib/query/query-provider";
import { billingHandlers } from "./msw/billing-handlers";
import {
  conversationSearchHandler,
  foundationHandler,
  libraryTagsHandler,
  paperListPreferencesHandlers,
  paperSearchHandler,
  webPerformanceHandler,
  zoteroCollectionsHandler,
  zoteroLibraryItemsHandler,
  zoteroStatusHandler,
} from "./msw/handlers";
import "../src/styles/globals.css";

initialize(
  {
    onUnhandledRequest(request, print) {
      const pathname = new URL(request.url).pathname;
      if (
        pathname.startsWith("/@id/virtual:") ||
        pathname.startsWith("/brand/")
      ) {
        return;
      }
      print.error();
    },
  },
  [
    ...billingHandlers.success,
    webPerformanceHandler,
    conversationSearchHandler,
    paperSearchHandler,
    libraryTagsHandler,
    ...paperListPreferencesHandlers,
    zoteroCollectionsHandler,
    zoteroLibraryItemsHandler,
  ],
);

const messages = { en, "zh-CN": zhCN } as const;
const isStorybookTest =
  (import.meta as ImportMeta & { env?: { MODE?: string } }).env?.MODE ===
  "test";
const initialMotionPreference: MotionPreference = isStorybookTest
  ? "reduced"
  : "system";

const preview: Preview = {
  decorators: [
    (Story, context) => {
      const theme = themeNames.includes(context.globals.theme as ThemeName)
        ? (context.globals.theme as ThemeName)
        : defaultThemeName;
      const appearance =
        context.globals.appearance === "dark" ? "dark" : "light";
      const locale: AppLocale =
        context.globals.locale === "zh-CN" ? "zh-CN" : "en";
      const motion = (["system", "reduced", "full"] as const).includes(
        context.globals.motion,
      )
        ? (context.globals.motion as MotionPreference)
        : "system";
      useLayoutEffect(() => {
        document.documentElement.lang = locale;
        document.documentElement.dir = localeDirection(locale);
      }, [locale]);
      return (
        <NextIntlClientProvider
          formats={formats}
          locale={locale}
          messages={messages[locale]}
          now={new Date("2026-08-04T10:00:00Z")}
          timeZone="UTC"
        >
          <ThemeProvider
            initialColorSchemePreference={appearance}
            initialTheme={theme}
            key={`${theme}:${appearance}`}
          >
            <MotionProvider
              initialPreference={motion}
              key={motion}
              skipAnimations={isStorybookTest}
            >
              <ScrollbarActivity />
              <MotionRuntimeProvider>
                <QueryProvider>
                  <div
                    className={`bg-canvas text-foreground min-h-screen ${
                      context.parameters.layout === "fullscreen" ? "" : "p-6"
                    }`}
                  >
                    <Story />
                  </div>
                </QueryProvider>
              </MotionRuntimeProvider>
            </MotionProvider>
          </ThemeProvider>
        </NextIntlClientProvider>
      );
    },
  ],
  globalTypes: {
    theme: {
      description: "Theme palette",
      defaultValue: defaultThemeName,
      toolbar: {
        icon: "paintbrush",
        items: themeNames.map((value) => ({
          value,
          title: value
            .split("-")
            .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
            .join(" "),
        })),
      },
    },
    appearance: {
      description: "Color scheme",
      defaultValue: "light",
      toolbar: {
        icon: "mirror",
        items: [
          { value: "light", title: "Light" },
          { value: "dark", title: "Dark" },
        ],
      },
    },
    motion: {
      description: "Motion preference",
      defaultValue: initialMotionPreference,
      toolbar: {
        icon: "lightning",
        items: [
          { value: "system", title: "System motion" },
          { value: "reduced", title: "Reduced motion" },
          { value: "full", title: "Full motion" },
        ],
      },
    },
    locale: {
      description: "Locale",
      defaultValue: "en",
      toolbar: {
        icon: "globe",
        items: [
          { value: "en", title: "English" },
          { value: "zh-CN", title: "简体中文" },
        ],
      },
    },
    network: {
      description: "Mock network",
      defaultValue: "instant",
      toolbar: {
        icon: "transfer",
        items: [
          { value: "instant", title: "Instant" },
          { value: "slow", title: "Slow" },
          { value: "offline", title: "Offline" },
        ],
      },
    },
    data: {
      description: "Mock data",
      defaultValue: "populated",
      toolbar: {
        icon: "database",
        items: [
          { value: "populated", title: "Populated" },
          { value: "empty", title: "Empty" },
          { value: "error", title: "Error" },
        ],
      },
    },
  },
  initialGlobals: {
    theme: defaultThemeName,
    appearance: "light",
    motion: initialMotionPreference,
    locale: "en",
    network: "instant",
    data: "populated",
  },
  loaders: [mswLoader],
  parameters: {
    a11y: { test: "error" },
    controls: { expanded: true },
    layout: "fullscreen",
    msw: {
      handlers: [
        foundationHandler,
        libraryTagsHandler,
        ...paperListPreferencesHandlers,
        paperSearchHandler,
        webPerformanceHandler,
        zoteroStatusHandler,
      ],
    },
    viewport: {
      options: {
        desktop: {
          name: "Desktop",
          styles: { width: "1440px", height: "900px" },
        },
        ultrawide: {
          name: "Ultrawide desktop",
          styles: { width: "1920px", height: "1080px" },
        },
        narrowPanel: {
          name: "Narrow panel",
          styles: { width: "480px", height: "900px" },
        },
        mobile: { name: "Mobile", styles: { width: "390px", height: "844px" } },
        largeMobile: {
          name: "Large Mobile",
          styles: { width: "430px", height: "932px" },
        },
        smallMobile: {
          name: "Small Mobile",
          styles: { width: "320px", height: "568px" },
        },
        tablet: {
          name: "Tablet",
          styles: { width: "768px", height: "1024px" },
        },
      },
    },
  },
};

export default preview;
