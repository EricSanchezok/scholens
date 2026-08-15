import {
  aside,
  button,
  div,
  form,
  li,
  ol,
  section,
  span,
  tr,
} from "motion/react-m";
import * as React from "react";

import { useMotionPreference } from "./motion-provider";

function markMotionRuntime<T extends React.ElementType>(Component: T): T {
  const Marked = React.forwardRef<unknown, React.ComponentPropsWithoutRef<T>>(
    (props, ref) => {
      const { ready, resolved } = useMotionPreference();
      const reduced = resolved === "reduced";

      return React.createElement(Component, {
        ...props,
        initial: ready && !reduced ? props.initial : false,
        exit: reduced ? undefined : props.exit,
        layout: reduced ? false : props.layout,
        "data-motion-runtime": "",
        ref,
      });
    },
  );
  Marked.displayName = "MotionRuntime";
  return Marked as unknown as T;
}

export { AnimatePresence } from "motion/react";
export const m = {
  aside: markMotionRuntime(aside),
  button: markMotionRuntime(button),
  div: markMotionRuntime(div),
  form: markMotionRuntime(form),
  li: markMotionRuntime(li),
  ol: markMotionRuntime(ol),
  section: markMotionRuntime(section),
  span: markMotionRuntime(span),
  tr: markMotionRuntime(tr),
};

export {
  motionStagger,
  motionTransitions,
  motionVariants,
} from "./motion-config";
export {
  MotionProvider,
  motionPreferences,
  parseMotionPreference,
  storedMotionPreference,
  useMotionPreference,
  type MotionPreference,
  type ResolvedMotion,
} from "./motion-provider";
export { MotionRuntimeProvider } from "./motion-runtime-provider";
export { MotionPresence } from "./motion-presence";
