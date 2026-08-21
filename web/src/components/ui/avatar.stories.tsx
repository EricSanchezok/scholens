import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { http, HttpResponse } from "msw";
import { expect, waitFor, within } from "storybook/test";

import { Avatar, type AvatarSource } from "./avatar";

const portrait =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%23272b35'/%3E%3Ccircle cx='32' cy='25' r='13' fill='%23d9b08c'/%3E%3Cpath d='M10 64c2-17 10-25 22-25s20 8 22 25' fill='%2386a8e7'/%3E%3C/svg%3E";

const source: AvatarSource = {
  expires_at: "2026-08-21T10:15:00Z",
  url: portrait,
  version: "11111111-1111-1111-1111-111111111111",
};

const meta = {
  title: "UI/Avatar",
  component: Avatar,
  args: {
    className: "size-12 text-sm",
    fallback: "E",
    sizes: "48px",
  },
  parameters: { layout: "centered" },
} satisfies Meta<typeof Avatar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ProfileImage: Story = { args: { source } };

export const InitialFallback: Story = { args: { source: null } };

export const BrokenImageFallback: Story = {
  args: {
    source: { ...source, url: "/missing-avatar-fixture.png" },
  },
  parameters: {
    msw: {
      handlers: [
        http.get("*/missing-avatar-fixture.png", () =>
          HttpResponse.json({}, { status: 404 }),
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText("E")).toHaveAttribute(
        "data-avatar-state",
        "fallback",
      ),
    );
  },
};

export const Compact: Story = {
  args: {
    className: "size-7 text-xs",
    fallback: "陈",
    sizes: "28px",
    source,
  },
};
