import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import {
  colorSchemes,
  themeNames,
} from "@/design-system/generated/theme-metadata";
import { Button } from "./button";

function titleCase(value: string) {
  return value
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function ThemeSample({
  theme,
  appearance,
}: {
  theme: (typeof themeNames)[number];
  appearance: (typeof colorSchemes)[number];
}) {
  return (
    <article
      className="border-line bg-canvas text-foreground grid gap-6 rounded-[var(--radius-xl)] border p-6"
      data-color-scheme={appearance}
      data-testid={`theme-${theme}-${appearance}`}
      data-theme={theme}
      style={{ colorScheme: appearance }}
    >
      <header className="grid gap-1">
        <h2 className="text-lg font-semibold">
          {titleCase(theme)} · {titleCase(appearance)}
        </h2>
        <p className="text-muted text-sm">
          Semantic roles resolve through one theme and appearance contract.
        </p>
      </header>

      <section
        aria-label={`${theme} ${appearance} surfaces`}
        className="grid grid-cols-3 gap-2"
      >
        <div className="border-line bg-surface rounded-[var(--radius-md)] border p-3 text-xs">
          Surface
        </div>
        <div className="bg-subtle rounded-[var(--radius-lg)] p-3 text-xs">
          Subtle
        </div>
        <div className="bg-elevated shadow-raised rounded-[var(--radius-xl)] p-3 text-xs">
          Elevated
        </div>
      </section>

      <section
        aria-label={`${theme} ${appearance} text hierarchy`}
        className="grid gap-1 text-sm"
      >
        <p className="font-semibold">Primary research heading</p>
        <p className="text-secondary">Secondary explanatory content</p>
        <p className="text-muted">Muted metadata and supporting context</p>
        <a className="w-fit underline underline-offset-4" href="#theme-lab">
          Semantic link
        </a>
      </section>

      <section
        aria-label={`${theme} ${appearance} actions`}
        className="flex flex-wrap gap-2"
      >
        <Button>Primary action</Button>
        <Button variant="secondary">Secondary action</Button>
        <Button disabled>Disabled action</Button>
      </section>

      <section
        aria-label={`${theme} ${appearance} feedback`}
        className="grid gap-2 text-sm sm:grid-cols-2"
      >
        <div className="border-info bg-state-info-bg text-info rounded-[var(--radius-md)] border p-3">
          Informational state
        </div>
        <div className="border-success bg-state-success-bg text-success rounded-[var(--radius-md)] border p-3">
          Successful state
        </div>
        <div className="border-warning bg-state-warning-bg text-warning rounded-[var(--radius-md)] border p-3">
          Warning state
        </div>
        <div className="border-danger bg-state-danger-bg text-danger rounded-[var(--radius-md)] border p-3">
          Error state
        </div>
      </section>
    </article>
  );
}

const meta = {
  title: "Foundations/Theme Lab",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const CompleteMatrix: Story = {
  render: () => (
    <div className="grid max-w-6xl gap-6 lg:grid-cols-2">
      {themeNames.flatMap((theme) =>
        colorSchemes.map((appearance) => (
          <ThemeSample
            appearance={appearance}
            key={`${theme}-${appearance}`}
            theme={theme}
          />
        )),
      )}
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const theme of themeNames) {
      for (const appearance of colorSchemes) {
        const sample = canvas.getByTestId(`theme-${theme}-${appearance}`);
        const styles = getComputedStyle(sample);
        await expect(
          styles.getPropertyValue("--color-bg-canvas").trim(),
        ).not.toBe("");
        await expect(
          styles.getPropertyValue("--color-text-primary").trim(),
        ).not.toBe("");
        await expect(
          styles.getPropertyValue("--theme-font-interface").trim(),
        ).not.toBe("");
        await expect(
          styles.getPropertyValue("--theme-radius-lg").trim(),
        ).not.toBe("");
        await expect(
          styles.getPropertyValue("--elevation-raised").trim(),
        ).not.toBe("");
      }
    }
  },
};
