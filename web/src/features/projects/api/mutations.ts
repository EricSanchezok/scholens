import { apiClient } from "@/lib/api";

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
  confirmDeleteAnnotations = false,
) {
  await apiClient.DELETE("/api/v1/projects/{project_id}/papers/{document_id}", {
    params: {
      path: { document_id: documentId, project_id: projectId },
      query: { confirm_delete_annotations: confirmDeleteAnnotations },
    },
  });
}
