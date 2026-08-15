import { LibraryPage } from "@/features/library";
import { MotionRuntimeProvider } from "@/design-system/motion/motion-runtime-provider";

export default function LibraryRoute() {
  return (
    <MotionRuntimeProvider>
      <LibraryPage />
    </MotionRuntimeProvider>
  );
}
