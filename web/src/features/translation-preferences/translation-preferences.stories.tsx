import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function TranslationPreferenceContract() {
  return (
    <section
      aria-label="Translation preference contract"
      className="border-line bg-surface grid max-w-lg gap-4 rounded-[var(--radius-lg)] border p-5"
    >
      <div>
        <h1 className="text-lg font-semibold">Reader translation defaults</h1>
        <p className="text-secondary mt-1 text-sm">
          One shared preference owner serves Reader and Settings.
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt className="text-secondary">Source</dt>
        <dd>Detect automatically</dd>
        <dt className="text-secondary">Target</dt>
        <dd>Simplified Chinese</dd>
        <dt className="text-secondary">Display</dt>
        <dd>Original and translation</dd>
      </dl>
    </section>
  );
}

const meta = {
  title: "Features/Translation preferences/Contract",
  component: TranslationPreferenceContract,
} satisfies Meta<typeof TranslationPreferenceContract>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
