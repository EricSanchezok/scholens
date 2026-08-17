import {
  createDocumentationFacts,
  renderDocumentationMarkdown,
} from "@/features/documentation";

export const dynamic = "force-dynamic";

export function GET(): Response {
  return new Response(renderDocumentationMarkdown(createDocumentationFacts()), {
    headers: {
      "Cache-Control": "public, max-age=300, s-maxage=3600",
      "Content-Type": "text/markdown; charset=utf-8",
    },
  });
}
