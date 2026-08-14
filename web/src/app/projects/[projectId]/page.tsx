import { ProjectDetailPage } from "@/features/projects";

export default async function ProjectDetailRoute({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <ProjectDetailPage projectId={projectId} />;
}
