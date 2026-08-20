import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import {
  InstallExperienceProvider,
  type InstallExperienceInitialState,
} from "./install-experience";
import {
  InstallInstructionsDialog,
  InstallPromotion,
} from "./install-components";

function InstallPreview({ state }: { state: InstallExperienceInitialState }) {
  return (
    <InstallExperienceProvider initialState={state}>
      <div className="bg-canvas flex min-h-52 items-end pb-3">
        <div className="w-full">
          <InstallPromotion />
        </div>
      </div>
      <InstallInstructionsDialog />
    </InstallExperienceProvider>
  );
}

const iosState: InstallExperienceInitialState = {
  environment: { instructionKind: "ios", mobile: true, supported: true },
  promotionEligible: true,
};

const meta = {
  title: "Features/Install Experience",
  component: InstallPreview,
  args: { state: iosState },
  globals: { viewport: { value: "mobile" } },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof InstallPreview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const IosPromotion: Story = {};

export const IosPromotionInteraction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Install" }));
    const dialog = await within(document.body).findByRole("dialog", {
      name: "Add Scholens to your Home Screen",
    });
    await expect(
      within(dialog).getByText("Choose Add to Home Screen."),
    ).toBeVisible();
  },
};

export const AndroidInstructions: Story = {
  args: {
    state: {
      environment: {
        instructionKind: "android",
        mobile: true,
        supported: true,
      },
      instructionsOpen: true,
    },
  },
};

export const WeChatChineseDark: Story = {
  args: {
    state: {
      environment: {
        instructionKind: "in-app",
        mobile: true,
        supported: true,
      },
      instructionsOpen: true,
    },
  },
  globals: { appearance: "dark", locale: "zh-CN" },
};
