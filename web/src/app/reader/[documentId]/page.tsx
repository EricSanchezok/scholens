import { ReaderPage } from "@/features/reader";
import { MotionRuntimeProvider } from "@/design-system/motion/motion-runtime-provider";

export default async function ReaderRoute({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  return (
    <MotionRuntimeProvider>
      <ReaderPage documentId={documentId} />
    </MotionRuntimeProvider>
  );
}
