import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { delay, http, HttpResponse } from "msw";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { actor, authHandlers } from "../../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import {
  projectFixtures,
  projectInvitationFixtures,
  projectMemberFixtures,
} from "../api/fixtures";
import { projectHandlers } from "../api/handlers";
import { ManageProjectCollaboratorsDialog } from "./manage-project-collaborators-dialog";

const api = "http://127.0.0.1:7301/api/v1";
const project = projectFixtures[0]!;

const meta = {
  title: "Features/Projects/Manage collaborators",
  component: ManageProjectCollaboratorsDialog,
  args: {
    actorId: actor.id,
    onOpenChange: () => undefined,
    open: true,
    project,
  },
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
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...projectHandlers.populated] },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof ManageProjectCollaboratorsDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DeliveryStates: Story = {
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog", {
      name: "Manage collaborators",
    });
    await expect(
      await within(dialog).findByText("pending@example.com"),
    ).toBeVisible();
    await expect(
      await within(dialog).findByText("delivered@example.com"),
    ).toBeVisible();
    await expect(within(dialog).getByText(/Delivered/)).toBeVisible();
    await expect(
      await within(dialog).findByText("failed@example.com"),
    ).toBeVisible();
    await expect(
      within(dialog).getAllByRole("button", { name: "Send a new link" }),
    ).toHaveLength(2);
  },
};

export const InviteAndPermissions: Story = {
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog", {
      name: "Manage collaborators",
    });
    const email = within(dialog).getByRole("textbox", {
      name: "Email address",
    });
    const inviteForm = email.closest("form");
    if (!inviteForm) throw new Error("Invitation form is missing");
    await userEvent.type(email, "new@example.com");
    await userEvent.click(
      within(inviteForm).getByRole("checkbox", { name: "Edit project" }),
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Send invitation" }),
    );
    await waitFor(() => expect(email).toHaveValue(""));
  },
};

export const MutuallyExclusiveRowActions: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.post(
          `${api}/projects/:projectId/invitations/:invitationId/resend`,
          async ({ params }) => {
            await delay(500);
            return HttpResponse.json({
              ...projectInvitationFixtures[1],
              id: params.invitationId,
            });
          },
        ),
        ...projectHandlers.populated,
      ],
    },
  },
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog", {
      name: "Manage collaborators",
    });
    const email = await within(dialog).findByText("delivered@example.com");
    const row = email.closest("article");
    if (!row) throw new Error("Invitation row is missing");
    const resend = within(row).getByRole("button", {
      name: "Send a new link",
    });
    const revoke = within(row).getByRole("button", { name: "Revoke" });

    await userEvent.click(resend);
    await waitFor(() => {
      expect(resend).toBeDisabled();
      expect(revoke).toBeDisabled();
    });
    await waitFor(() => expect(revoke).toBeEnabled(), { timeout: 2_000 });
  },
};

export const PermissionBoundary: Story = {
  args: {
    actorId: 9,
    project: {
      ...project,
      capabilities: {
        ...project.capabilities,
        edit_project: false,
        manage_papers: false,
      },
      membership: {
        kind: "collaborator",
        permissions: {
          edit_project: false,
          manage_collaborators: true,
          manage_papers: false,
        },
      },
    },
  },
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/projects/:projectId/members`, () =>
          HttpResponse.json({
            items: [
              projectMemberFixtures[0],
              {
                display_name: "Alex Chen",
                email: "alex@example.com",
                is_owner: false,
                joined_at: "2026-08-10T09:00:00Z",
                permissions: {
                  edit_project: false,
                  manage_collaborators: true,
                  manage_papers: false,
                },
                user_id: 9,
              },
              projectMemberFixtures[1],
            ],
            next_cursor: null,
          }),
        ),
        ...projectHandlers.populated,
      ],
    },
  },
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog", {
      name: "Manage collaborators",
    });
    await expect(
      await within(dialog).findByText(
        "Only a collaborator with all of this member’s permissions can manage them.",
      ),
    ).toBeVisible();
    const members = within(dialog).getByRole("region", { name: "Members" });
    for (const checkbox of within(members).getAllByRole("checkbox")) {
      await expect(checkbox).toBeDisabled();
    }
  },
};

export const QueryError: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/projects/:projectId/members`, () =>
          HttpResponse.json(
            { code: "service_unavailable", message: "Unavailable" },
            { status: 503 },
          ),
        ),
        ...projectHandlers.populated,
      ],
    },
  },
};

export const LongContent: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/projects/:projectId/members`, () =>
          HttpResponse.json({
            items: [
              projectMemberFixtures[0],
              {
                ...projectMemberFixtures[1],
                display_name:
                  "Dr. A Very Long Collaborator Name Across Multilingual Research Programs",
                email:
                  "long-collaborator-address-for-narrow-layout@example-research-institute.org",
              },
            ],
            next_cursor: null,
          }),
        ),
        ...projectHandlers.populated,
      ],
    },
  },
};

export const Mobile390: Story = {
  globals: { viewport: { isRotated: false, value: "mobile" } },
};

export const SmallMobile320: Story = {
  globals: { viewport: { isRotated: false, value: "smallMobile" } },
  play: async ({ canvasElement }) => {
    await within(document.body).findByRole("dialog", {
      name: "Manage collaborators",
    });
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const ChineseDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
};
