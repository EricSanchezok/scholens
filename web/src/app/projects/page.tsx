import { ProjectsPage } from "@/features/projects";
import { MotionRuntimeProvider } from "@/design-system/motion/motion-runtime-provider";

export default function ProjectsRoute() {
  return (
    <MotionRuntimeProvider>
      <ProjectsPage />
    </MotionRuntimeProvider>
  );
}
