import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import {
  DocumentationPage,
  isDocumentationClient,
} from "@/features/documentation";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Documentation.metadata");
  return {
    title: t("title"),
    description: t("description"),
    alternates: {
      canonical: "/docs",
      types: { "text/markdown": "/docs.md" },
    },
  };
}

export default async function DocsRoute({
  searchParams,
}: {
  searchParams: Promise<{ client?: string | string[] }>;
}) {
  const client = (await searchParams).client;
  return (
    <DocumentationPage
      selectedClient={isDocumentationClient(client) ? client : "codex"}
    />
  );
}
