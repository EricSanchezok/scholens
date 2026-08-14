import { ReaderPage } from "@/features/reader";

export default async function ReaderRoute({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  return <ReaderPage documentId={documentId} />;
}
