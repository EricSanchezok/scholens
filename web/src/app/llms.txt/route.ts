import {
  createDocumentationFacts,
  renderLlmsText,
} from "@/features/documentation";

export const dynamic = "force-dynamic";

export function GET(request: Request): Response {
  const origin = new URL(request.url).origin;
  return new Response(
    renderLlmsText(createDocumentationFacts(undefined, origin)),
    {
      headers: {
        "Cache-Control": "public, max-age=300, s-maxage=3600",
        "Content-Type": "text/plain; charset=utf-8",
      },
    },
  );
}
