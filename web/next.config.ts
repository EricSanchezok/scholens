import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const distDir = process.env.NODE_ENV === "development" ? ".next-dev" : ".next";

const nextConfig: NextConfig = {
  devIndicators: false,
  distDir,
  experimental: {
    optimizePackageImports: ["motion/react", "motion/react-m"],
  },
  generateBuildId: async () =>
    process.env.NEXT_PUBLIC_RELEASE_SHA ?? "development",
  headers: async () => [
    {
      source: "/docs",
      headers: [
        {
          key: "Link",
          value: '</docs.md>; rel="alternate"; type="text/markdown"',
        },
      ],
    },
  ],
  output: "standalone",
  productionBrowserSourceMaps: true,
  reactStrictMode: true,
  typedRoutes: true,
};

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

export default withNextIntl(nextConfig);
