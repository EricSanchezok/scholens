import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { delay, http, HttpResponse } from "msw";
import { expect, within } from "storybook/test";

import { authHandlers } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { ProjectInvitationPage } from "./project-invitation-page";

const api = "http://127.0.0.1:7301/api/v1";
const token = "signed.invitation-token";

const meta = {
  title: "Features/Projects/Accept invitation",
  component: ProjectInvitationPage,
  args: { token },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
  loaders: [
    async () => {
      resetRefreshForTests();
      window.history.replaceState({}, "", `/project-invitations/${token}`);
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: authHandlers.success },
    nextjs: {
      appDirectory: true,
      navigation: {
        asPath: `/project-invitations/${token}`,
        pathname: `/project-invitations/[token]`,
        query: { token },
      },
    },
  },
} satisfies Meta<typeof ProjectInvitationPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Accepting: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.post(`${api}/project-invitations/:token/accept`, async () => {
          await delay("infinite");
          return HttpResponse.json({ project_id: "unused" });
        }),
      ],
    },
  },
};

export const AccountMismatch: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.post(`${api}/project-invitations/:token/accept`, () =>
          HttpResponse.json(
            {
              code: "project_invitation_recipient_mismatch",
              kind: "permission_denied",
              message: "Wrong account",
              retryable: false,
            },
            { status: 403 },
          ),
        ),
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText(
        "This invitation belongs to another account",
      ),
    ).toBeVisible();
  },
};

export const ExpiredOrRevoked: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.post(`${api}/project-invitations/:token/accept`, () =>
          HttpResponse.json(
            {
              code: "project_invitation_invalid",
              kind: "not_found",
              message: "Invalid",
              retryable: false,
            },
            { status: 404 },
          ),
        ),
      ],
    },
  },
};

export const OfflineRetry: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.post(`${api}/project-invitations/:token/accept`, () =>
          HttpResponse.error(),
        ),
      ],
    },
  },
};

export const ChineseDarkMobile430: Story = {
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { isRotated: false, value: "largeMobile" },
  },
  parameters: AccountMismatch.parameters,
};
