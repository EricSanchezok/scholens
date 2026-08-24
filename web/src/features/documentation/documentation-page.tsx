"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { CopyActionButton } from "@/components/feedback";
import { buttonVariants, focusSurfaceVariants } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  BackIcon,
  ExpandIcon,
  ExternalLinkIcon,
  KeyIcon,
  RepositoryIcon,
} from "@/design-system/icons/semantic-icons";
import { ProductLockup } from "@/features/product-identity";
import { useLocalePreference } from "@/i18n/use-locale-preference";
import {
  ACCESS_KEYS_SETTINGS_PATH,
  SOURCE_REPOSITORY_URL,
} from "@/lib/product";
import { cn } from "@/lib/utilities/cn";
import {
  createDocumentationFacts,
  documentationAnchors,
  documentationClients,
  mcpCapabilityGroups,
  mcpPermissions,
  mcpResources,
  mcpResourceTemplates,
  type DocumentationClient,
} from "./documentation-content";

const tableOfContents = [
  [documentationAnchors.quickStart, "quickStart"],
  [documentationAnchors.mcpSetup, "mcpSetup"],
  [documentationAnchors.permissions, "permissions"],
  [documentationAnchors.capabilities, "capabilities"],
  [documentationAnchors.repositoryBinding, "repositoryBinding"],
  [documentationAnchors.security, "security"],
  [documentationAnchors.troubleshooting, "troubleshooting"],
] as const;

function LocaleControl() {
  const t = useTranslations("Documentation");
  const { locale, pending, setLocale } = useLocalePreference();

  return (
    <div
      aria-label={t("header.language")}
      className="bg-subtle flex rounded-[var(--radius-md)] p-0.5"
      role="group"
    >
      {(["en", "zh-CN"] as const).map((option) => (
        <button
          aria-pressed={locale === option}
          className={cn(
            "motion-control min-h-11 rounded-[calc(var(--radius-md)-2px)] px-2.5 text-xs font-medium sm:min-h-9",
            focusSurfaceVariants({ intent: "selection" }),
            locale === option
              ? "bg-surface text-foreground"
              : "text-secondary hover:text-foreground",
          )}
          disabled={pending}
          key={option}
          onClick={() => setLocale(option)}
          type="button"
        >
          {option === "en" ? "EN" : "中文"}
        </button>
      ))}
    </div>
  );
}

function DocumentationHeader() {
  const t = useTranslations("Documentation");

  return (
    <header className="border-line-subtle bg-canvas sticky top-0 z-30 border-b">
      <div className="mx-auto flex min-h-16 max-w-[75rem] items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link
          className={cn(
            "flex min-h-11 items-center gap-2 rounded-[var(--radius-sm)] font-semibold sm:min-h-9",
            focusSurfaceVariants({ intent: "neutral" }),
          )}
          href="/"
        >
          <ProductLockup />
          <span className="text-secondary font-normal">/</span>
          <span className="text-secondary font-medium">{t("header.docs")}</span>
        </Link>
        <nav
          aria-label={t("header.navigation")}
          className="ml-auto flex items-center gap-2"
        >
          <Link
            className={cn(
              "text-secondary hover:text-foreground hidden min-h-9 items-center gap-1.5 rounded-[var(--radius-sm)] px-2 text-sm sm:inline-flex",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
            href="/"
          >
            <Icon glyph={BackIcon} size={16} tone="secondary" />
            {t("header.backToApp")}
          </Link>
          <a
            className={cn(
              "text-secondary hover:text-foreground hidden min-h-9 items-center gap-1.5 rounded-[var(--radius-sm)] px-2 text-sm md:inline-flex",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
            href={SOURCE_REPOSITORY_URL}
            rel="noopener noreferrer"
            target="_blank"
          >
            <Icon glyph={RepositoryIcon} size={16} tone="secondary" />
            {t("header.repository")}
            <Icon glyph={ExternalLinkIcon} size={16} tone="secondary" />
          </a>
          <LocaleControl />
        </nav>
      </div>
    </header>
  );
}

function TableOfContents({ compact = false }: { compact?: boolean }) {
  const t = useTranslations("Documentation");
  const links = (
    <nav aria-label={t("toc.label")} className="grid gap-0.5">
      {tableOfContents.map(([anchor, message]) => (
        <a
          className={cn(
            "text-secondary hover:bg-hover hover:text-foreground flex min-h-11 items-center rounded-[var(--radius-md)] px-3 text-sm sm:min-h-9",
            focusSurfaceVariants({ intent: "neutral" }),
          )}
          href={`#${anchor}`}
          key={anchor}
        >
          {t(`toc.${message}`)}
        </a>
      ))}
    </nav>
  );

  if (!compact) return links;
  return (
    <details className="border-line-subtle bg-subtle group rounded-[var(--radius-lg)] border p-2 lg:hidden">
      <summary
        className={cn(
          "flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--radius-md)] px-2 text-sm font-medium [&::-webkit-details-marker]:hidden",
          focusSurfaceVariants({ intent: "neutral" }),
        )}
      >
        <span>{t("toc.open")}</span>
        <Icon
          className="motion-control group-open:rotate-180"
          glyph={ExpandIcon}
          size={16}
          tone="secondary"
        />
      </summary>
      <div className="pt-1">{links}</div>
    </details>
  );
}

function Section({
  children,
  id,
  title,
  description,
}: {
  children: React.ReactNode;
  id: string;
  title: string;
  description?: string;
}) {
  return (
    <section className="scroll-mt-24 pt-16 first:pt-0" id={id}>
      <h2 className="text-2xl leading-8 font-semibold tracking-[-0.02em] sm:text-3xl sm:leading-10">
        {title}
      </h2>
      {description ? (
        <p className="text-secondary mt-3 max-w-[70ch] text-base leading-7">
          {description}
        </p>
      ) : null}
      <div className="mt-7">{children}</div>
    </section>
  );
}

function CodeSample({
  code,
  language,
  title,
}: {
  code: string;
  language: string;
  title: string;
}) {
  const t = useTranslations("Documentation");
  return (
    <figure className="border-line-subtle overflow-hidden rounded-[var(--radius-xl)] border">
      <figcaption className="border-line-subtle bg-subtle flex min-h-11 items-center justify-between gap-3 border-b px-3 sm:px-4">
        <span className="min-w-0 truncate text-xs font-medium">{title}</span>
        <span className="flex items-center gap-2">
          <span className="text-muted hidden text-xs sm:inline">
            {language}
          </span>
          <CopyActionButton
            errorLabel={t("copy.error")}
            label={t("copy.copy")}
            pendingLabel={t("copy.copying")}
            successLabel={t("copy.copied")}
            value={code}
          />
        </span>
      </figcaption>
      <pre
        aria-label={title}
        className={cn(
          "bg-surface overflow-x-auto p-4 text-[0.8125rem] leading-6",
          focusSurfaceVariants({ intent: "scroll" }),
        )}
        tabIndex={0}
      >
        <code>{code}</code>
      </pre>
    </figure>
  );
}

function ClientSelector({ selected }: { selected: DocumentationClient }) {
  const t = useTranslations("Documentation");

  return (
    <div>
      <p className="text-sm font-medium">{t("setup.chooseClient")}</p>
      <nav
        aria-label={t("setup.chooseClient")}
        className="mt-3 flex flex-wrap gap-2"
      >
        {documentationClients.map((client) => (
          <Link
            aria-current={selected === client ? "page" : undefined}
            className={buttonVariants({
              size: "sm",
              variant: selected === client ? "primary" : "secondary",
            })}
            href={`/docs?client=${client}`}
            key={client}
            scroll={false}
          >
            {t(`clients.${client}.label`)}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function DocumentationPage({
  selectedClient = "codex",
}: {
  selectedClient?: DocumentationClient;
}) {
  const t = useTranslations("Documentation");
  const facts = createDocumentationFacts();
  const client = facts.clients[selectedClient];
  const securityItems = [
    "store",
    "leastPrivilege",
    "confirm",
    "upload",
  ] as const;
  const troubleshootingItems = [
    "unauthorized",
    "missingTool",
    "restart",
    "localFile",
    "longOperation",
  ] as const;

  return (
    <div className="bg-canvas min-h-dvh" data-testid="documentation-page">
      <a
        className={cn(
          "bg-surface sr-only z-50 rounded-[var(--radius-md)] px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:top-3 focus:left-3",
          focusSurfaceVariants({ intent: "neutral" }),
        )}
        href="#documentation-content"
      >
        {t("header.skipToContent")}
      </a>
      <DocumentationHeader />
      <main id="documentation-content">
        <section className="border-line-subtle border-b">
          <div className="mx-auto max-w-[75rem] px-4 py-16 sm:px-6 sm:py-20 lg:px-8 lg:py-24">
            <div className="max-w-[52rem]">
              <h1 className="max-w-[18ch] text-4xl leading-[1.08] font-semibold tracking-[-0.035em] text-balance sm:text-6xl">
                {t("hero.title")}
              </h1>
              <p className="text-secondary mt-6 max-w-[66ch] text-lg leading-8">
                {t("hero.description", { count: facts.toolCount })}
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  className={buttonVariants({ variant: "primary" })}
                  href={ACCESS_KEYS_SETTINGS_PATH}
                >
                  <Icon glyph={KeyIcon} size={16} tone="inverse" />
                  {t("hero.createKey")}
                </Link>
                <a
                  className={buttonVariants({ variant: "secondary" })}
                  href={SOURCE_REPOSITORY_URL}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  <Icon glyph={RepositoryIcon} size={16} tone="secondary" />
                  {t("hero.openRepository")}
                  <Icon glyph={ExternalLinkIcon} size={16} tone="secondary" />
                </a>
              </div>
            </div>
          </div>
        </section>

        <div className="mx-auto max-w-[75rem] px-4 py-8 sm:px-6 lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-12 lg:px-8 lg:py-12 xl:gap-16">
          <aside className="hidden lg:block">
            <div className="sticky top-24">
              <TableOfContents />
            </div>
          </aside>
          <article className="max-w-[50rem] min-w-0">
            <TableOfContents compact />

            <Section
              description={t("quickStart.description")}
              id={documentationAnchors.quickStart}
              title={t("quickStart.title")}
            >
              <ol className="grid gap-0 border-y border-[var(--color-border-subtle)]">
                {(["create", "copy", "connect", "verify"] as const).map(
                  (step, index) => (
                    <li
                      className="border-line-subtle grid gap-2 border-b py-5 last:border-b-0 sm:grid-cols-[2rem_11rem_minmax(0,1fr)] sm:gap-4"
                      key={step}
                    >
                      <span className="text-muted text-sm tabular-nums">
                        {index + 1}
                      </span>
                      <span className="font-medium">
                        {t(`quickStart.steps.${step}.title`)}
                      </span>
                      <span className="text-secondary text-sm leading-6">
                        {t(`quickStart.steps.${step}.description`)}
                      </span>
                    </li>
                  ),
                )}
              </ol>
            </Section>

            <Section
              description={t("setup.description")}
              id={documentationAnchors.mcpSetup}
              title={t("setup.title")}
            >
              <div className="bg-subtle rounded-[var(--radius-xl)] px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-secondary text-sm">
                    {t("setup.endpoint")}
                  </span>
                  <code className="text-sm break-all">{facts.mcpUrl}</code>
                </div>
              </div>

              <div className="mt-8 grid gap-5 sm:grid-cols-2">
                <div>
                  <h3 className="font-semibold">{t("setup.remote.title")}</h3>
                  <p className="text-secondary mt-2 text-sm leading-6">
                    {t("setup.remote.description")}
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold">{t("setup.local.title")}</h3>
                  <p className="text-secondary mt-2 text-sm leading-6">
                    {t("setup.local.description")}
                  </p>
                </div>
              </div>

              <div className="mt-10">
                <ClientSelector selected={selectedClient} />
                <div className="mt-5">
                  <h3 className="text-xl font-semibold">
                    {t(`clients.${selectedClient}.label`)}
                  </h3>
                  <p className="text-secondary mt-2 max-w-[68ch] text-sm leading-6">
                    {t(`clients.${selectedClient}.description`)}
                  </p>
                  <div className="mt-5 grid gap-4">
                    <CodeSample
                      code={client.credential}
                      language={
                        selectedClient === "claude-desktop" ? "note" : "shell"
                      }
                      title={t("setup.credential")}
                    />
                    <CodeSample
                      code={client.configuration}
                      language={client.language}
                      title={t("setup.configuration")}
                    />
                  </div>
                  <p className="text-secondary mt-4 text-sm leading-6 [overflow-wrap:anywhere]">
                    {t(`clients.${selectedClient}.after`)}
                  </p>
                  {client.referenceUrl ? (
                    <a
                      className={cn(
                        "text-secondary hover:text-foreground mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius-sm)] text-sm underline underline-offset-4 sm:min-h-9",
                        focusSurfaceVariants({ intent: "inline" }),
                      )}
                      href={client.referenceUrl}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      {t("setup.officialReference")}
                      <Icon
                        glyph={ExternalLinkIcon}
                        size={16}
                        tone="secondary"
                      />
                    </a>
                  ) : null}
                </div>
              </div>

              <div className="border-line-subtle mt-10 border-t pt-8">
                <h3 className="text-lg font-semibold">
                  {t("setup.localUpload.title")}
                </h3>
                <p className="text-secondary mt-2 max-w-[70ch] text-sm leading-6">
                  {t("setup.localUpload.description", {
                    size: facts.maxLocalPdfMegabytes,
                  })}
                </p>
                <p className="text-muted mt-3 text-xs leading-5 break-all">
                  {facts.connectorSource.kind === "release"
                    ? t("setup.localUpload.releasePinned", {
                        sha: facts.connectorSource.ref,
                      })
                    : t("setup.localUpload.developmentFallback")}
                </p>
                <details className="group mt-4">
                  <summary
                    className={cn(
                      "flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--radius-sm)] text-sm font-medium underline-offset-4 hover:underline [&::-webkit-details-marker]:hidden",
                      focusSurfaceVariants({ intent: "neutral" }),
                    )}
                  >
                    <span>{t("setup.localUpload.showConfiguration")}</span>
                    <Icon
                      className="motion-control group-open:rotate-180"
                      glyph={ExpandIcon}
                      size={16}
                      tone="secondary"
                    />
                  </summary>
                  <div className="mt-4">
                    <CodeSample
                      code={facts.localConnector}
                      language="json"
                      title={t("setup.localUpload.configuration")}
                    />
                  </div>
                </details>
              </div>
            </Section>

            <Section
              description={t("permissions.description")}
              id={documentationAnchors.permissions}
              title={t("permissions.title")}
            >
              <dl className="border-line-subtle border-y">
                {mcpPermissions.map((permission) => (
                  <div
                    className="border-line-subtle grid gap-2 border-b py-5 last:border-b-0 sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-6"
                    key={permission.id}
                  >
                    <dt>
                      <code className="font-semibold">{permission.id}</code>
                    </dt>
                    <dd className="text-secondary text-sm leading-6">
                      {t(`permissions.items.${permission.id}`)}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="text-secondary mt-5 text-sm leading-6">
                {t("permissions.authorization")}
              </p>
            </Section>

            <Section
              description={t("capabilities.description", {
                count: facts.toolCount,
              })}
              id={documentationAnchors.capabilities}
              title={t("capabilities.title")}
            >
              <div className="border-line-subtle overflow-hidden rounded-[var(--radius-xl)] border">
                {mcpCapabilityGroups.map((group) => (
                  <div
                    className="border-line-subtle grid grid-cols-[3.5rem_minmax(0,1fr)] gap-4 border-b px-4 py-4 last:border-b-0 sm:grid-cols-[4.5rem_11rem_minmax(0,1fr)] sm:px-5"
                    key={group.id}
                  >
                    <span className="text-2xl font-semibold tabular-nums">
                      {group.count}
                    </span>
                    <span className="font-medium">
                      {t(`capabilities.groups.${group.id}.title`)}
                    </span>
                    <span className="text-secondary col-start-2 text-sm leading-6 sm:col-start-3">
                      {t(`capabilities.groups.${group.id}.description`)}
                    </span>
                  </div>
                ))}
              </div>

              <div className="mt-8 grid gap-6 sm:grid-cols-2">
                <div>
                  <h3 className="font-semibold">
                    {t("capabilities.resources")}
                  </h3>
                  <ul className="text-secondary mt-3 grid gap-2 text-sm">
                    {mcpResources.map((resource) => (
                      <li key={resource}>
                        <code>{resource}</code>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="font-semibold">
                    {t("capabilities.templates")}
                  </h3>
                  <ul className="text-secondary mt-3 grid gap-2 text-sm">
                    {mcpResourceTemplates.map((resource) => (
                      <li className="break-all" key={resource}>
                        <code>{resource}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="bg-subtle mt-8 rounded-[var(--radius-xl)] px-5 py-5">
                <h3 className="font-semibold">
                  {t("capabilities.boundary.title")}
                </h3>
                <p className="text-secondary mt-2 text-sm leading-6">
                  {t("capabilities.boundary.description")}
                </p>
              </div>
            </Section>

            <Section
              description={t("binding.description")}
              id={documentationAnchors.repositoryBinding}
              title={t("binding.title")}
            >
              <CodeSample
                code={facts.bindingMarkdown}
                language="markdown"
                title="AGENTS.md / README.md"
              />
              <p className="text-secondary mt-4 text-sm leading-6">
                {t("binding.guidance")}
              </p>
            </Section>

            <Section
              description={t("security.description")}
              id={documentationAnchors.security}
              title={t("security.title")}
            >
              <ul className="grid gap-4">
                {securityItems.map((item) => (
                  <li
                    className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-3"
                    key={item}
                  >
                    <span
                      aria-hidden
                      className="bg-foreground mt-2 size-1.5 rounded-full"
                    />
                    <span className="text-secondary text-sm leading-6">
                      {t(`security.items.${item}`)}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section
              id={documentationAnchors.troubleshooting}
              title={t("troubleshooting.title")}
            >
              <div className="divide-line-subtle border-line-subtle divide-y border-y">
                {troubleshootingItems.map((item) => (
                  <details className="group py-5" key={item}>
                    <summary
                      className={cn(
                        "flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--radius-sm)] font-medium [&::-webkit-details-marker]:hidden",
                        focusSurfaceVariants({ intent: "neutral" }),
                      )}
                    >
                      <span>{t(`troubleshooting.items.${item}.title`)}</span>
                      <Icon
                        className="motion-control group-open:rotate-180"
                        glyph={ExpandIcon}
                        size={16}
                        tone="secondary"
                      />
                    </summary>
                    <p className="text-secondary mt-3 max-w-[70ch] text-sm leading-6">
                      {t(`troubleshooting.items.${item}.description`, {
                        size: facts.maxLocalPdfMegabytes,
                      })}
                    </p>
                  </details>
                ))}
              </div>
            </Section>

            <footer className="border-line-subtle mt-20 flex flex-wrap gap-x-6 gap-y-3 border-t py-8 text-sm">
              <a
                className={cn(
                  "text-secondary hover:text-foreground inline-flex min-h-11 items-center rounded-[var(--radius-sm)] sm:min-h-9",
                  focusSurfaceVariants({ intent: "inline" }),
                )}
                href="/docs.md"
              >
                {t("footer.markdown")}
              </a>
              <a
                className={cn(
                  "text-secondary hover:text-foreground inline-flex min-h-11 items-center rounded-[var(--radius-sm)] sm:min-h-9",
                  focusSurfaceVariants({ intent: "inline" }),
                )}
                href="/llms.txt"
              >
                {t("footer.llms")}
              </a>
              <a
                className={cn(
                  "text-secondary hover:text-foreground inline-flex min-h-11 items-center rounded-[var(--radius-sm)] sm:min-h-9",
                  focusSurfaceVariants({ intent: "inline" }),
                )}
                href={SOURCE_REPOSITORY_URL}
                rel="noopener noreferrer"
                target="_blank"
              >
                {t("footer.repository")}
              </a>
              <span className="text-muted ml-auto">{t("footer.license")}</span>
            </footer>
          </article>
        </div>
      </main>
    </div>
  );
}
