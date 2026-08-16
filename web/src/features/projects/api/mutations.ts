import { apiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

type ProjectPermissions = components["schemas"]["ProjectPermissionSet"];

export async function createProject(input: {
  title: string;
  description: string | null;
}) {
  const { data } = await apiClient.POST("/api/v1/projects", { body: input });
  if (!data) throw new Error("Project create response was empty");
  return data;
}

export async function updateProject(
  projectId: string,
  input: { title: string; description?: string | null },
) {
  const { data } = await apiClient.PATCH("/api/v1/projects/{project_id}", {
    body: input,
    params: { path: { project_id: projectId } },
  });
  if (!data) throw new Error("Project update response was empty");
  return data;
}

export async function deleteProject(projectId: string) {
  await apiClient.DELETE("/api/v1/projects/{project_id}", {
    params: { path: { project_id: projectId } },
  });
}

export async function leaveProject(projectId: string) {
  await apiClient.POST("/api/v1/projects/{project_id}/leave", {
    params: { path: { project_id: projectId } },
  });
}

export async function addProjectPapers(
  projectId: string,
  documentIds: string[],
) {
  const { data } = await apiClient.POST(
    "/api/v1/projects/{project_id}/papers",
    {
      body: { document_ids: documentIds },
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) throw new Error("Project paper add response was empty");
  return data;
}

export async function removeProjectPaper(
  projectId: string,
  documentId: string,
  confirmationToken?: string,
) {
  await apiClient.DELETE("/api/v1/projects/{project_id}/papers/{document_id}", {
    headers: confirmationToken
      ? { "X-Scholens-Confirmation-Token": confirmationToken }
      : undefined,
    params: {
      path: { document_id: documentId, project_id: projectId },
    },
  });
}

export async function createProjectInvitation(
  projectId: string,
  input: ProjectPermissions & { email: string },
) {
  const { data } = await apiClient.POST(
    "/api/v1/projects/{project_id}/invitations",
    {
      body: input,
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) throw new Error("Project invitation response was empty");
  return data;
}

export async function resendProjectInvitation(
  projectId: string,
  invitationId: string,
) {
  const { data } = await apiClient.POST(
    "/api/v1/projects/{project_id}/invitations/{invitation_id}/resend",
    {
      params: {
        path: { invitation_id: invitationId, project_id: projectId },
      },
    },
  );
  if (!data) throw new Error("Project invitation response was empty");
  return data;
}

export async function revokeProjectInvitation(
  projectId: string,
  invitationId: string,
) {
  await apiClient.DELETE(
    "/api/v1/projects/{project_id}/invitations/{invitation_id}",
    {
      params: {
        path: { invitation_id: invitationId, project_id: projectId },
      },
    },
  );
}

export async function updateProjectMember(
  projectId: string,
  userId: number,
  permissions: ProjectPermissions,
) {
  const { data } = await apiClient.PATCH(
    "/api/v1/projects/{project_id}/members/{user_id}",
    {
      body: permissions,
      params: { path: { project_id: projectId, user_id: userId } },
    },
  );
  if (!data) throw new Error("Project member response was empty");
  return data;
}

export async function removeProjectMember(projectId: string, userId: number) {
  await apiClient.DELETE("/api/v1/projects/{project_id}/members/{user_id}", {
    params: { path: { project_id: projectId, user_id: userId } },
  });
}

export async function acceptProjectInvitation(token: string) {
  const { data } = await apiClient.POST(
    "/api/v1/project-invitations/{token}/accept",
    { params: { path: { token } } },
  );
  if (!data)
    throw new Error("Project invitation acceptance response was empty");
  return data;
}
