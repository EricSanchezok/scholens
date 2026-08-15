import { ProjectDetailPage } from "@/features/projects";
import { MotionRuntimeProvider } from "@/design-system/motion/motion-runtime-provider";

export default async function ProjectDetailRoute({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return (
    <MotionRuntimeProvider>
      <ProjectDetailPage projectId={projectId} />
    </MotionRuntimeProvider>
  );
}
