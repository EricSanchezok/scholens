import type { StorybookConfig } from "@storybook/nextjs-vite";
import { fileURLToPath } from "node:url";

const webVitalsMock = fileURLToPath(
  new URL("./mocks/next-web-vitals.ts", import.meta.url),
);

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(js|jsx|mjs|ts|tsx)"],
  addons: [
    "@storybook/addon-docs",
    "@storybook/addon-a11y",
    "@storybook/addon-vitest",
  ],
  framework: { name: "@storybook/nextjs-vite", options: {} },
  staticDirs: ["../public"],
  viteFinal: async (viteConfig) => {
    const aliases = Array.isArray(viteConfig.resolve?.alias)
      ? viteConfig.resolve.alias
      : Object.entries(viteConfig.resolve?.alias ?? {}).map(
          ([find, replacement]) => ({ find, replacement }),
        );
    return {
      ...viteConfig,
      optimizeDeps: {
        ...viteConfig.optimizeDeps,
        include: [
          ...(viteConfig.optimizeDeps?.include ?? []),
          "openapi-fetch",
          "zod",
        ],
      },
      resolve: {
        ...viteConfig.resolve,
        alias: [
          { find: "next/web-vitals", replacement: webVitalsMock },
          ...aliases,
        ],
      },
    };
  },
};

export default config;
