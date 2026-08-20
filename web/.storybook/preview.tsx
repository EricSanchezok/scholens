import type { Preview } from "@storybook/nextjs-vite";
import { initialize, mswLoader } from "msw-storybook-addon";
import { NextIntlClientProvider } from "next-intl";
import { useLayoutEffect } from "react";

import { localeDirection, type AppLocale } from "../src/i18n/config";
import {
  MotionProvider,
  MotionRuntimeProvider,
  type MotionPreference,
} from "../src/design-system/motion";
import { formats } from "../src/i18n/formats";
import en from "../src/i18n/messages/en.json";
import zhCN from "../src/i18n/messages/zh-CN.json";
import { QueryProvider } from "../src/lib/query/query-provider";
import { billingHandlers } from "./msw/billing-handlers";
import {
  foundationHandler,
  webPerformanceHandler,
  zoteroCollectionsHandler,
  zoteroLibraryItemsHandler,
  zoteroStatusHandler,
} from "./msw/handlers";
import "../src/styles/globals.css";

initialize({ onUnhandledRequest: "error" }, [
  ...billingHandlers.success,
  webPerformanceHandler,
  zoteroCollectionsHandler,
  zoteroLibraryItemsHandler,
]);

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
        document.documentElement.dataset.theme = "default";
        document.documentElement.dataset.colorScheme = appearance;
        document.documentElement.lang = locale;
        document.documentElement.dir = localeDirection(locale);
      }, [appearance, locale, motion]);
      return (
        <NextIntlClientProvider
          formats={formats}
          locale={locale}
          messages={messages[locale]}
          now={new Date("2026-08-04T10:00:00Z")}
          timeZone="UTC"
        >
          <MotionProvider
            initialPreference={motion}
            key={motion}
            skipAnimations={isStorybookTest}
          >
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
        </NextIntlClientProvider>
      );
    },
  ],
  globalTypes: {
    theme: {
      description: "Theme palette",
      defaultValue: "default",
      toolbar: {
        icon: "paintbrush",
        items: [{ value: "default", title: "Default" }],
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
    theme: "default",
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
      handlers: [foundationHandler, webPerformanceHandler, zoteroStatusHandler],
    },
    viewport: {
      options: {
        desktop: {
          name: "Desktop",
          styles: { width: "1440px", height: "900px" },
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
