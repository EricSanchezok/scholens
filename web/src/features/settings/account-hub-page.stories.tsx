import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { http, HttpResponse } from "msw";
import { expect, within } from "storybook/test";

import { actor, authHandlers } from "../../../.storybook/msw/auth-handlers";
import { billingHandlers } from "../../../.storybook/msw/billing-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { AccountHubWorkspace } from "./account-hub-page";
import type { AccountHubView } from "./account-hub-routes";

const api = "http://127.0.0.1:7301/api/v1";

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

const accountHubHandlers = [
  ...billingHandlers.success,
  ...authHandlers.success,
  http.get(`${api}/me/reading-activity-preferences`, () =>
    HttpResponse.json({
      contribute_anonymous_project_aggregates: true,
      recording_enabled: true,
    }),
  ),
  http.put(`${api}/me/reading-activity-preferences`, async ({ request }) =>
    HttpResponse.json((await request.json()) as object),
  ),
  http.get(`${api}/conversations`, () =>
    HttpResponse.json({ items: [], next_cursor: null }),
  ),
  http.get(`${api}/me/access-keys`, () =>
    HttpResponse.json({ items: [], next_cursor: null, previous_cursor: null }),
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
];

function AccountHubStory({
  storyActor = actor,
  view = "home",
}: {
  storyActor?: typeof actor;
  view?: AccountHubView;
}) {
  return <AccountHubWorkspace actor={storyActor} view={view} />;
}

const meta = {
  title: "Features/Settings/Account Hub",
  component: AccountHubStory,
  args: { storyActor: actor, view: "home" },
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
    msw: { handlers: accountHubHandlers },
    nextjs: { appDirectory: true },
  },
  globals: { viewport: { value: "mobile", isRotated: false } },
} satisfies Meta<typeof AccountHubStory>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Home: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("link", { name: "Open account details" }),
    ).toHaveAttribute("href", "/me/account");
    await expect(
      await canvas.findByRole("link", { name: "Open plan and usage" }),
    ).toHaveAttribute("href", "/me/usage");
    await expect(
      canvas.getByRole("link", { name: /^Settings/ }),
    ).toHaveAttribute("href", "/me/settings");
    await expect(
      canvas.queryByRole("button", { name: "Sign out" }),
    ).not.toBeInTheDocument();
    const navigation = canvas.getByRole("navigation", {
      name: "Primary navigation",
    });
    await expect(
      within(navigation).getByRole("link", { name: "Me" }),
    ).toHaveAttribute("aria-current", "page");
  },
};

export const BillingLoading: Story = {
  parameters: {
    msw: {
      handlers: [...billingHandlers.loading, ...accountHubHandlers],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByText("Loading plan and usage…"),
    ).toBeVisible();
  },
};

export const BillingUnavailable: Story = {
  parameters: {
    msw: {
      handlers: [...billingHandlers.unavailable, ...accountHubHandlers],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/could not be loaded/)).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Try again" }),
    ).toBeVisible();
  },
};

export const LongIdentity: Story = {
  args: {
    storyActor: {
      ...actor,
      display_name:
        "A very long researcher name that must remain readable on a phone",
      email: "a.very.long.researcher.identity@example-university.edu",
    },
  },
};

export const Account: Story = {
  args: { view: "account" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "Account" }),
    ).toBeVisible();
    await expect(
      await canvas.findByRole("button", { name: "Sign out" }),
    ).toBeVisible();
    await expect(canvas.getByRole("link", { name: "Go back" })).toHaveAttribute(
      "href",
      "/me",
    );
  },
};

export const Usage: Story = {
  args: { view: "usage" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Usage" })).toBeVisible();
    await expect(await canvas.findByText("Papers per project")).toBeVisible();
  },
};

export const SettingsOverview: Story = {
  args: { view: "settings" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", { name: /Display and interaction/ }),
    ).toHaveAttribute("href", "/me/settings/display");
    await expect(
      canvas.getByRole("link", { name: /Translation/ }),
    ).toHaveAttribute("href", "/me/settings/translation");
  },
};

export const DisplayPreferences: Story = { args: { view: "display" } };
export const TranslationPreferences: Story = {
  args: { view: "translation" },
};
export const Connections: Story = { args: { view: "connections" } };
export const AccessKeys: Story = { args: { view: "accessKeys" } };

export const ChineseDark: Story = {
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("账户与偏好")).toBeVisible();
    await expect(canvas.getByRole("link", { name: "我的" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  },
};

export const SmallMobile320: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};

export const AccessKeysSmallMobile320: Story = {
  args: { view: "accessKeys" },
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "Access keys" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: /MCP setup guide/ }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Create access key" }),
    ).toBeVisible();
    expect(document.documentElement.scrollWidth <= window.innerWidth).toBe(
      true,
    );
  },
};
