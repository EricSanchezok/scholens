import { z } from "zod";

const clientEnvironmentSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url().default("http://127.0.0.1:7301"),
  NEXT_PUBLIC_ACCOUNT_CENTER_URL: z
    .string()
    .url()
    .default("https://myaccount.sanchezcloud.net"),
  NEXT_PUBLIC_RELEASE_SHA: z.string().default("development"),
});

export const clientEnvironment = clientEnvironmentSchema.parse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_ACCOUNT_CENTER_URL:
    process.env.NEXT_PUBLIC_ACCOUNT_CENTER_URL || undefined,
  NEXT_PUBLIC_RELEASE_SHA: process.env.NEXT_PUBLIC_RELEASE_SHA || undefined,
});
