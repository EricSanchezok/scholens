import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function IntegrationStateCatalog() {
  return (
    <section className="grid max-w-lg gap-3" aria-label="Integration states">
      <h1 className="text-xl font-semibold">Integration connection states</h1>
      <div className="border-line bg-surface flex items-center justify-between rounded-[var(--radius-lg)] border p-4">
        <span>MinerU</span>
        <span className="bg-state-warning-bg text-warning rounded-full px-2 py-1 text-xs font-medium">
          Saved · not yet verified
        </span>
      </div>
      <div className="border-line bg-surface flex items-center justify-between rounded-[var(--radius-lg)] border p-4">
        <span>Exa</span>
        <span className="bg-state-success-bg text-success rounded-full px-2 py-1 text-xs font-medium">
          Connected
        </span>
      </div>
      <div className="border-line bg-surface flex items-center justify-between rounded-[var(--radius-lg)] border p-4">
        <span>Tavily</span>
        <span className="bg-state-danger-bg text-danger rounded-full px-2 py-1 text-xs font-medium">
          Needs attention
        </span>
      </div>
    </section>
  );
}

const meta = {
  title: "Features/Integrations/State catalog",
  component: IntegrationStateCatalog,
} satisfies Meta<typeof IntegrationStateCatalog>;

export default meta;
type Story = StoryObj<typeof meta>;
export const States: Story = {};
