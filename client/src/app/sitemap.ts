import { MetadataRoute } from 'next'

export default function sitemap(): MetadataRoute.Sitemap {
    const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "http://127.0.0.1:7303";

    return ["/login", "/privacy", "/tos"].map((path) => ({
        url: `${baseUrl}${path}`,
        changeFrequency: "monthly" as const,
        priority: path === "/login" ? 0.8 : 0.3,
    }));
}
