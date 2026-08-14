import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const distDir = process.env.NODE_ENV === "development" ? ".next-dev" : ".next";

const nextConfig: NextConfig = {
  devIndicators: false,
  distDir,
  reactStrictMode: true,
  typedRoutes: true,
};

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

export default withNextIntl(nextConfig);
