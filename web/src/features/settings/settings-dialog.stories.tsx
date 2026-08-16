import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { http, HttpResponse } from "msw";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { authHandlers } from "../../../.storybook/msw/auth-handlers";
import { billingHandlers } from "../../../.storybook/msw/billing-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { SettingsDialog, SettingsDialogSurface } from "./settings-dialog";

function ControlledSettingsDialog() {
  const [section, setSection] = React.useState<"general" | "account">(
    "general",
  );

  return (
    <SettingsDialogSurface
      accountCenterUrl="https://account-center.example.test/"
      onSectionChange={(next) => {
        if (next === "general" || next === "account") setSection(next);
      }}
      section={section}
    />
  );
}

const api = "http://127.0.0.1:7301/api/v1";
let signOutRequests = 0;
const integrations = [
  {
    category: "built_in",
    connection_method: "built_in",
    enabled: true,
    managed: true,
    provider: "scholight",
    state: "connected",
    updated_at: "2026-08-14T08:00:00Z",
    verified_at: "2026-08-14T08:00:00Z",
  },
  {
    category: "parsing",
    connection_method: "credential",
    enabled: false,
    managed: false,
    provider: "mineru",
    state: "disconnected",
    updated_at: null,
    verified_at: null,
  },
  ...(["anysearch", "tavily", "exa", "firecrawl", "openalex"] as const).map(
    (provider) => ({
      category: "search",
      connection_method: "credential",
      enabled: false,
      managed: false,
      provider,
      state: "disconnected",
      updated_at: null,
      verified_at: null,
    }),
  ),
  {
    category: "reference_manager",
    connection_method: "oauth",
    enabled: false,
    managed: false,
    provider: "zotero",
    state: "disconnected",
    updated_at: null,
    verified_at: null,
  },
];

const settingsHandlers = [
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
      await body.findByRole("heading", {
        name: "Appearance, motion & language",
      }),
    ).toBeVisible();
    await expect(body.getByRole("button", { name: "Light" })).toBeVisible();
    await expect(body.getByRole("button", { name: "Dark" })).toBeVisible();
    await expect(body.getByRole("button", { name: "System" })).toBeVisible();
    await expect(
      await body.findByRole("combobox", { name: "Interface language" }),
    ).toBeVisible();
    await userEvent.click(body.getByRole("button", { name: "Dark" }));
    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute(
        "data-color-scheme",
        "dark",
      ),
    );
    await expect(body.getByRole("button", { name: "Dark" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(localStorage.getItem("scholens-color-scheme")).toBe("dark");
    await userEvent.click(body.getByRole("button", { name: /Reduce motion/ }));
    await expect(localStorage.getItem("scholens-motion")).toBe("reduced");
    await expect(document.documentElement).toHaveAttribute(
      "data-motion",
      "reduced",
    );
  },
};

export const NonBlockingPanelReplacement: Story = {
  globals: { motion: "full" },
  render: () => <ControlledSettingsDialog />,
  play: async () => {
    const body = within(document.body);
    const initialHeading = await body.findByRole("heading", {
      name: "Appearance, motion & language",
    });
    await waitFor(() => expect(initialHeading).toBeVisible());
    await userEvent.click(body.getByRole("button", { name: "Account" }));
    const heading = await body.findByRole("heading", { name: "Account" });
    const accountCenter = await body.findByRole("link", {
      name: "Manage SanchezCloud account",
    });
    await expect(heading).toBeInTheDocument();
    accountCenter.focus();
    await expect(accountCenter).toHaveFocus();
  },
};

export const Account: Story = {
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Account" }),
    ).toBeVisible();
    await expect(await body.findByText("Eric")).toBeVisible();
    await expect(await body.findByText("eric@scholens.ai")).toBeVisible();
    const accountCenterLink = await body.findByRole("link", {
      name: "Manage SanchezCloud account",
    });
    await expect(accountCenterLink).toHaveAttribute(
      "href",
      "https://account-center.example.test/",
    );
    await expect(accountCenterLink).toHaveAttribute("target", "_blank");
    await expect(accountCenterLink).toHaveAttribute(
      "rel",
      expect.stringContaining("noopener"),
    );
    await expect(accountCenterLink).toHaveAttribute(
      "rel",
      expect.stringContaining("noreferrer"),
    );
    await expect(body.queryByLabelText("Display name")).not.toBeInTheDocument();
    await expect(
      body.queryByLabelText("Current password"),
    ).not.toBeInTheDocument();
    await expect(
      await body.findByRole("button", { name: "Sign out" }),
    ).toBeVisible();
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

export const AccountCenterDefault: Story = {
  args: { accountCenterUrl: undefined },
  parameters: { nextjs: navigation("account") },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByRole("link", { name: "Manage SanchezCloud account" }),
    ).toHaveAttribute("href", "https://myaccount.sanchezcloud.net");
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
    const period = body.getByRole("combobox", { name: "Usage period" });
    await userEvent.click(period);
    await userEvent.click(
      await body.findByRole("option", { name: "Last 4 weeks" }),
    );
    await expect(
      await body.findByRole("combobox", { name: "Usage period" }),
    ).toHaveTextContent("Last 4 weeks");
    await expect(
      body.queryByRole("button", { name: "Upgrade" }),
    ).not.toBeInTheDocument();
    await expect(
      body.queryByRole("button", { name: "Manage billing" }),
    ).not.toBeInTheDocument();
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

export const OpenAlexConnection: Story = {
  parameters: { nextjs: navigation("connections") },
  play: async () => {
    const body = within(document.body);
    const openalex = await body.findByText("OpenAlex");
    const row = openalex.closest("article");
    await expect(row).not.toBeNull();
    await userEvent.click(
      within(row as HTMLElement).getByRole("button", { name: "Connect" }),
    );
    const dialogs = await body.findAllByRole("dialog");
    const credentialDialog = dialogs.at(-1)!;
    await expect(
      within(credentialDialog).getByRole("link", {
        name: "Get an OpenAlex API key",
      }),
    ).toHaveAttribute("href", "https://openalex.org/settings/api");
    await expect(
      within(credentialDialog).getByLabelText("API key"),
    ).toBeVisible();
  },
};

export const ConnectedOpenAlexConnection: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/me/integrations`, () =>
          HttpResponse.json({
            items: integrations.map((integration) =>
              integration.provider === "openalex"
                ? {
                    ...integration,
                    enabled: true,
                    state: "connected",
                    updated_at: "2026-08-15T08:00:00Z",
                    verified_at: "2026-08-15T08:00:00Z",
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
    const openalex = await body.findByText("OpenAlex");
    const row = openalex.closest("article");
    await expect(row).not.toBeNull();
    await expect(
      within(row as HTMLElement).getByText("Connected"),
    ).toBeVisible();
    await expect(
      within(row as HTMLElement).getByRole("switch", {
        name: "Enable OpenAlex",
      }),
    ).toBeChecked();
  },
};

export const DisabledOpenAlexConnection: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/me/integrations`, () =>
          HttpResponse.json({
            items: integrations.map((integration) =>
              integration.provider === "openalex"
                ? {
                    ...integration,
                    enabled: false,
                    state: "disabled",
                    updated_at: "2026-08-15T08:00:00Z",
                    verified_at: "2026-08-15T08:00:00Z",
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
    const openalex = await body.findByText("OpenAlex");
    const row = openalex.closest("article");
    await expect(row).not.toBeNull();
    await expect(
      within(row as HTMLElement).getByText("Disabled"),
    ).toBeVisible();
    await expect(
      within(row as HTMLElement).getByRole("switch", {
        name: "Enable OpenAlex",
      }),
    ).not.toBeChecked();
  },
};

export const InvalidOpenAlexConnection: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/me/integrations`, () =>
          HttpResponse.json({
            items: integrations.map((integration) =>
              integration.provider === "openalex"
                ? {
                    ...integration,
                    enabled: true,
                    last_error_code: "openalex_credential_invalid",
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
    const openalex = await body.findByText("OpenAlex");
    const row = openalex.closest("article");
    await expect(row).not.toBeNull();
    await expect(
      within(row as HTMLElement).getByText("Needs attention"),
    ).toBeVisible();
    await expect(
      within(row as HTMLElement).getByRole("button", {
        name: "Replace credential",
      }),
    ).toBeVisible();
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
        name: "Replace credential",
      }),
    ).toBeVisible();
  },
};

export const ZoteroConnected: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.success,
        http.get(`${api}/me/integrations`, () =>
          HttpResponse.json({
            items: integrations.map((integration) =>
              integration.provider === "zotero"
                ? {
                    ...integration,
                    enabled: true,
                    state: "connected",
                    updated_at: "2026-08-15T08:00:00Z",
                    verified_at: "2026-08-15T08:00:00Z",
                  }
                : integration,
            ),
          }),
        ),
        http.get(`${api}/integrations/zotero/status`, () =>
          HttpResponse.json({
            active_operation_id: null,
            auto_import_enabled: false,
            auto_import_state: "off",
            automatic_annotation_sync: "active",
            automatic_sync_eligible: true,
            connected_at: "2026-08-15T08:00:00Z",
            connection_state: "connected",
            last_error_code: null,
            last_successful_sync_at: "2026-08-16T06:30:00Z",
          }),
        ),
      ],
    },
    nextjs: navigation("connections"),
  },
  play: async () => {
    const body = within(document.body);
    const zotero = await body.findByText("Zotero");
    const row = zotero.closest("article");
    await expect(row).not.toBeNull();
    if (!row) return;
    await expect(
      within(row).getByRole("button", { name: "Sync now" }),
    ).toBeVisible();
    await expect(
      await within(row).findByRole("switch", {
        name: "Automatically import new papers",
      }),
    ).not.toBeChecked();
  },
};

export const MinerUDeferredVerification: Story = {
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
                    state: "connected_unverified",
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
      within(row as HTMLElement).getByText("Saved · verifies on first use"),
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
    const sourceLanguage = body.getByRole("combobox", {
      name: "Source language",
    });
    await userEvent.click(sourceLanguage);
    await userEvent.click(
      await body.findByRole("option", { name: "Japanese" }),
    );
    await expect(sourceLanguage).toHaveTextContent("Japanese");
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
    await expect(
      await body.findByRole("button", { name: "Sign out" }),
    ).toBeVisible();
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
      await body.findByRole("link", { name: "管理 SanchezCloud 账户" }),
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
