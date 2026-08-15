import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import {
  motionDurations,
  motionEasings,
} from "@/design-system/generated/motion-metadata";
import {
  AnimatePresence,
  m,
  motionTransitions,
  motionVariants,
  useMotionPreference,
} from "@/design-system/motion";

const durationEntries = Object.entries(motionDurations) as [
  keyof typeof motionDurations,
  number,
][];
const easingEntries = Object.entries(motionEasings) as [
  keyof typeof motionEasings,
  readonly number[],
][];

function MotionLab() {
  const { preference, resolved } = useMotionPreference();
  const [items, setItems] = React.useState(["Sources", "Notes"]);
  const [panelOpen, setPanelOpen] = React.useState(false);

  return (
    <main className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-10 sm:px-8">
      <header className="max-w-2xl">
        <p className="text-accent text-xs font-semibold tracking-[0.14em] uppercase">
          Motion foundations
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.03em]">
          Calm motion with a job to do
        </h1>
        <p className="text-secondary mt-3 leading-7">
          Tokens control tempo, semantic recipes control behavior, and product
          features only choreograph meaningful state changes.
        </p>
        <p className="text-muted mt-3 text-sm" data-motion-lab-preference>
          Preference: {preference} · resolved: {resolved}
        </p>
      </header>

      <section aria-labelledby="tempo-heading">
        <h2 className="text-lg font-semibold" id="tempo-heading">
          Duration scale
        </h2>
        <div className="mt-4 grid gap-2">
          {durationEntries.map(([name, value]) => (
            <div
              className="border-line-subtle grid grid-cols-[6rem_minmax(0,1fr)_4rem] items-center gap-3 border-t py-3"
              key={name}
            >
              <code className="text-sm">{name}</code>
              <div className="bg-subtle h-1.5 overflow-hidden rounded-full">
                <div
                  className="bg-accent h-full rounded-full"
                  style={{
                    width: `${Math.max(2, (value / motionDurations.deliberate) * 100)}%`,
                  }}
                />
              </div>
              <span className="text-muted text-right text-sm tabular-nums">
                {value} ms
              </span>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="easing-heading">
        <h2 className="text-lg font-semibold" id="easing-heading">
          Easing roles
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {easingEntries.map(([name, value]) => (
            <article
              className="border-line bg-surface rounded-[var(--radius-lg)] border p-4"
              key={name}
            >
              <h3 className="font-medium">{name.replace("_", "–")}</h3>
              <code className="text-muted mt-2 block text-xs leading-5">
                {value.join(", ")}
              </code>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="choreography-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold" id="choreography-heading">
              Choreography
            </h2>
            <p className="text-secondary mt-1 text-sm">
              Layout reflow, bounded inserts, and contextual disclosure.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              onClick={() =>
                setItems((current) => [
                  ...current,
                  `Finding ${current.length - 1}`,
                ])
              }
              size="sm"
              variant="secondary"
            >
              Add finding
            </Button>
            <Button onClick={() => setPanelOpen((open) => !open)} size="sm">
              Toggle context
            </Button>
          </div>
        </div>
        <m.div
          className="mt-4 grid min-h-52 gap-4 sm:grid-cols-[minmax(0,1fr)_16rem]"
          layout="size"
          transition={motionTransitions.layout}
        >
          <m.div
            className="border-line bg-surface rounded-[var(--radius-xl)] border p-4"
            layout="size"
            transition={motionTransitions.layout}
          >
            <AnimatePresence initial={false}>
              {items.map((item) => (
                <m.div
                  animate="animate"
                  className="border-line-subtle flex items-center justify-between border-b py-3 last:border-0"
                  exit="exit"
                  initial="initial"
                  key={item}
                  layout="position"
                  variants={motionVariants.listItem}
                >
                  <span className="text-sm font-medium">{item}</span>
                  <span className="text-muted text-xs">Ready</span>
                </m.div>
              ))}
            </AnimatePresence>
          </m.div>
          <AnimatePresence initial={false}>
            {panelOpen ? (
              <m.aside
                animate="animate"
                className="border-line bg-subtle rounded-[var(--radius-xl)] border p-4"
                exit="exit"
                initial="initial"
                key="context-panel"
                variants={motionVariants.panel}
              >
                <h3 className="font-medium">Research context</h3>
                <p className="text-secondary mt-2 text-sm leading-6">
                  Motion preserves spatial continuity while the workspace
                  changes shape.
                </p>
              </m.aside>
            ) : null}
          </AnimatePresence>
        </m.div>
      </section>

      <section aria-labelledby="overlay-heading">
        <h2 className="text-lg font-semibold" id="overlay-heading">
          CSS-first overlays
        </h2>
        <div className="mt-4 flex flex-wrap gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="secondary">Open popover</Button>
            </PopoverTrigger>
            <PopoverContent>
              <p className="text-sm font-medium">Anchored to its trigger</p>
              <p className="text-secondary mt-1 text-sm">
                The origin and direction communicate hierarchy.
              </p>
            </PopoverContent>
          </Popover>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="secondary">Open dialog</Button>
            </DialogTrigger>
            <DialogContent closeLabel="Close motion example">
              <DialogTitle>Focused decision</DialogTitle>
              <DialogDescription>
                The surface settles quickly and keeps focus behavior owned by
                the dialog primitive.
              </DialogDescription>
            </DialogContent>
          </Dialog>
        </div>
      </section>
    </main>
  );
}

const meta = {
  title: "Foundations/Motion Lab",
  component: MotionLab,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof MotionLab>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FullMotion: Story = {
  globals: { motion: "full" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/resolved: full/)).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Add finding" }));
    await waitFor(() => expect(canvas.getByText("Finding 1")).toBeVisible());
    await userEvent.click(
      canvas.getByRole("button", { name: "Toggle context" }),
    );
    await waitFor(() =>
      expect(canvas.getByText("Research context")).toBeVisible(),
    );
  },
};

export const ReducedMotion: Story = {
  globals: { motion: "reduced" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/resolved: reduced/)).toBeVisible();
    await expect(document.documentElement).toHaveAttribute(
      "data-motion",
      "reduced",
    );
  },
};
