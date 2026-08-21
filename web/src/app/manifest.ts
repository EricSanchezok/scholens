import type { MetadataRoute } from "next";

import { pwaColors } from "@/design-system/generated/theme-metadata";

export default function manifest(): MetadataRoute.Manifest {
  return {
    background_color: pwaColors.light.canvas,
    description: "Read, organize, and ask across your research with Scholens.",
    display: "standalone",
    icons: [
      {
        sizes: "192x192",
        src: "/brand/icons/icon-192.png",
        type: "image/png",
      },
      {
        sizes: "512x512",
        src: "/brand/icons/icon-512.png",
        type: "image/png",
      },
      {
        purpose: "maskable",
        sizes: "512x512",
        src: "/brand/icons/icon-maskable-512.png",
        type: "image/png",
      },
    ],
    id: "/",
    name: "Scholens",
    scope: "/",
    short_name: "Scholens",
    start_url: "/",
    theme_color: pwaColors.light.canvas,
  };
}
