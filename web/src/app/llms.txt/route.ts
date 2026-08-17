import {
  createDocumentationFacts,
  renderLlmsText,
} from "@/features/documentation";

export const dynamic = "force-dynamic";

export function GET(): Response {
  return new Response(renderLlmsText(createDocumentationFacts()), {
    headers: {
      "Cache-Control": "public, max-age=300, s-maxage=3600",
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
}
