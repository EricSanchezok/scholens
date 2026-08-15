import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { http, HttpResponse } from "msw";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { actor, authHandlers } from "../../../.storybook/msw/auth-handlers";
import { billingHandlers } from "../../../.storybook/msw/billing-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { SettingsDialog } from "./settings-dialog";

const api = "http://127.0.0.1:7301/api/v1";
let signOutRequests = 0;
const integrations = [
  {
    category: "built_in",
    enabled: true,
    managed: true,
    provider: "scholight",
    state: "connected",
    updated_at: "2026-08-14T08:00:00Z",
    verified_at: "2026-08-14T08:00:00Z",
  },
  {
    category: "parsing",
    enabled: false,
    managed: false,
    provider: "mineru",
    state: "disconnected",
    updated_at: null,
    verified_at: null,
  },
  ...(["anysearch", "tavily", "exa", "firecrawl"] as const).map((provider) => ({
    category: "search",
    enabled: false,
    managed: false,
    provider,
    state: "disconnected",
    updated_at: null,
    verified_at: null,
  })),
];

const settingsHandlers = [
  http.get(`${api}/me/profile`, () => HttpResponse.json(actor)),
  ...billingHandlers.success,
  http.get(`${api}/me/access-keys`, () =>
    HttpResponse.json({
      items: [
        {
          created_at: "2026-08-01T08:00:00Z",
          expires_at: "2026-10-30T08:00:00Z",
          id: "51000000-0000-4000-8000-000000000001",
          key_prefix: "sk_scholens_7K2P",
          last_used_at: "2026-08-14T08:00:00Z",
          name: "Literature notebook",
          permissions: ["read", "write"],
          status: "active",
        },
      ],
      next_cursor: null,
      previous_cursor: null,
    }),
  ),
  http.get(`${api}/me/integrations`, () =>
    HttpResponse.json({ items: integrations }),
  ),
  http.get(`${api}/me/translation-preferences`, () =>
    HttpResponse.json({
      auto_translate_selection: true,
      custom_instructions: "Preserve domain-specific English terminology.",
      full_translation_display: "bilingual",
      show_translation_marker: true,
      source_language: "auto",
      target_language: "zh-CN",
      translate_references: false,
      updated_at: "2026-08-14T08:00:00Z",
    }),
  ),
  http.post(`${api}/auth/logout`, () => {
    signOutRequests += 1;
    return new HttpResponse(null, { status: 204 });
  }),
];

const navigation = (section: string) => ({
  appDirectory: true,
  navigation: {
    asPath: `/?settings=${section}`,
    pathname: "/",
    query: { settings: section },
  },
});

const meta = {
  title: "Features/Settings/Dialog",
  component: SettingsDialog,
  args: {
    accountCenterUrl: "https://account-center.example.test/",
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
      signOutRequests = 0;
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...settingsHandlers, ...authHandlers.success] },
    nextjs: navigation("general"),
  },
} satisfies Meta<typeof SettingsDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const General: Story = {
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "General" }),
    ).toBeVisible();
    await expect(
      await body.findByRole("combobox", { name: "Interface language" }),
    ).toBeVisible();
  },
};

export const Account: Story = {
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Account" }),
    ).toBeVisible();
    await expect(await body.findByDisplayValue("Eric")).toBeVisible();
    await expect(await body.findByText("Researcher")).toBeVisible();
    await expect(
      body.getByRole("link", { name: "Open Account Center" }),
    ).toHaveAttribute("href", "https://account-center.example.test/");
    await expect(body.getByRole("button", { name: "Sign out" })).toBeVisible();
  },
};

export const AccountSignOut: Story = {
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await userEvent.click(
      await body.findByRole("button", { name: "Sign out" }),
    );
    await waitFor(() => expect(signOutRequests).toBe(1));
  },
};

export const AccountCenterUnavailable: Story = {
  args: { accountCenterUrl: "" },
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByText(
        "Account Center is not configured for this environment.",
      ),
    ).toBeVisible();
    await expect(
      body.getByRole("button", {
        name: /Open Account Center.*not configured/i,
      }),
    ).toBeDisabled();
  },
};

export const Usage: Story = {
  parameters: { nextjs: navigation("usage") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Usage" }),
    ).toBeVisible();
    await expect(await body.findByText("Token Credits")).toBeVisible();
    await expect(await body.findByText("Papers per project")).toBeVisible();
    await expect(await body.findByText("Up to 120")).toBeVisible();
    await expect(await body.findByText("768 MiB / 3 GiB")).toBeVisible();
    await expect(
      body.getByRole("button", { name: /Upgrade.*not available/i }),
    ).toBeDisabled();
    await expect(
      body.getByRole("button", { name: /Manage billing.*not available/i }),
    ).toBeDisabled();
  },
};

export const AccessKeys: Story = {
  parameters: { nextjs: navigation("access-keys") },
  play: async () => {
    const body = within(document.body);
    await expect(await body.findByText("Literature notebook")).toBeVisible();
    await expect(
      body.getByRole("button", { name: "Create access key" }),
    ).toBeVisible();
  },
};

export const Connections: Story = {
  parameters: { nextjs: navigation("connections") },
  play: async () => {
    const body = within(document.body);
    const mineru = await body.findByText("MinerU");
    const row = mineru.closest("article");
    await expect(row).not.toBeNull();
    await userEvent.click(
      within(row as HTMLElement).getByRole("button", { name: "Connect" }),
    );
    const dialogs = await body.findAllByRole("dialog");
    const credentialDialog = dialogs.at(-1)!;
    await expect(
      within(credentialDialog).getByRole("link", {
        name: "Get a MinerU token",
      }),
    ).toHaveAttribute("href", "https://mineru.net/apiManage/token");
  },
};

export const InvalidConnection: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/me/integrations`, () =>
          HttpResponse.json({
            items: integrations.map((integration) =>
              integration.provider === "mineru"
                ? {
                    ...integration,
                    enabled: true,
                    last_error_code: "integration_credentials_unreadable",
                    state: "invalid",
                    updated_at: "2026-08-15T08:00:00Z",
                  }
                : integration,
            ),
          }),
        ),
      ],
    },
    nextjs: navigation("connections"),
  },
  play: async () => {
    const body = within(document.body);
    const mineru = await body.findByText("MinerU");
    const row = mineru.closest("article");
    await expect(row).not.toBeNull();
    await expect(
      within(row as HTMLElement).getByText("Needs attention"),
    ).toBeVisible();
    await expect(
      within(row as HTMLElement).getByRole("button", {
        name: "Replace token",
      }),
    ).toBeVisible();
  },
};

export const Translation: Story = {
  parameters: { nextjs: navigation("translation") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Translation" }),
    ).toBeVisible();
    await expect(
      await body.findByDisplayValue(
        "Preserve domain-specific English terminology.",
      ),
    ).toBeVisible();
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  parameters: { nextjs: navigation("connections") },
};

export const MobileAccount390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Account" }),
    ).toBeVisible();
    await expect(body.getByRole("button", { name: "Sign out" })).toBeVisible();
  },
};

export const DarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  parameters: { nextjs: navigation("connections") },
  play: async () => {
    await expect(
      await within(document.body).findByRole("heading", { name: "连接" }),
    ).toBeVisible();
  },
};

export const AccountDarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "账户" }),
    ).toBeVisible();
    await expect(
      body.getByRole("link", { name: "打开账户中心" }),
    ).toBeVisible();
  },
};

export const UsageDarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  parameters: { nextjs: navigation("usage") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "用量" }),
    ).toBeVisible();
    await expect(await body.findByText("768 MiB / 3 GiB")).toBeVisible();
    await expect(await body.findByText("最多 120 篇")).toBeVisible();
  },
};
