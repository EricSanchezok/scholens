import { ProjectInvitationPage } from "@/features/projects";

export default async function ProjectInvitationRoute({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <ProjectInvitationPage token={token} />;
}
