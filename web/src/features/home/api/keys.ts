export const homeKeys = {
  all: ["home"] as const,
  papers: () => [...homeKeys.all, "papers"] as const,
  projects: () => [...homeKeys.all, "projects"] as const,
};
