import type { MetadataRoute } from "next"


const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://push-key.com"

const ROUTES = [
  "",
  "/docs",
  "/docs/agents",
  "/docs/api",
  "/docs/cli",
  "/portal",
  "/privacy",
  "/terms",
]

export default function sitemap(): MetadataRoute.Sitemap {
  return ROUTES.map((route) => ({
    url: `${SITE_URL}${route}`,
    lastModified: new Date("2026-07-21"),
    changeFrequency: route === "" ? "weekly" : "monthly",
    priority: route === "" ? 1 : 0.7,
  }))
}
