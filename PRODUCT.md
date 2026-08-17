# Scholens product principles

This document records durable product decisions. It describes the intended
user experience and should not prescribe implementation details that may
change as the system evolves.

## One conversational agent, contextualized by where the user is

All user-facing conversational experiences in Scholens should feel like the
same capable agent.

This includes conversations started from Home, Everything Ask, a project, or a
paper in the Reader. These surfaces should not become separate products with
different capabilities or independently maintained tool sets.

The differences between them come from context:

- the system guidance appropriate to the current experience;
- the information already in view and supplied to the conversation;
- sensible defaults inferred from where the conversation was started.

For example, a conversation opened from a paper should already understand that
paper. A conversation opened from a project should already understand the
project and naturally begin within that research scope. A broader conversation
should begin from the user's wider research library.

These starting points are defaults, not artificial capability boundaries. When
the user's request calls for a narrower or broader research scope, the same
agent should be able to adjust accordingly, provided the user is allowed to
access that information.

This symmetry is a deliberate product and maintenance principle:

- users should not need to learn which version of the agent can perform a
  particular task;
- the same interaction should behave consistently wherever it is initiated;
- new capabilities should strengthen the conversational product as a whole,
  rather than being implemented repeatedly for individual surfaces;
- product context should specialize the agent's behavior without fragmenting
  its underlying capabilities.

The interface should make the active context understandable and should reveal
when the agent intentionally works beyond that initial context. Tool activity,
sources, citations, progress, and errors should use a consistent interaction
language across all conversational surfaces.

Ordinary questions should receive ordinary answers. Research retrieval is a
capability the agent uses when evidence is needed, not a mandatory prelude to
every response. When tools are used, the product may disclose a concise,
inspectable activity history, but it must not expose model chain-of-thought,
raw tool arguments, provider heartbeats, or internal iteration mechanics.

That consistency includes the surrounding interface. New pages may have
different information architecture and density, but they should not invent an
independent visual or interaction dialect. Shared actions, context, progress,
feedback, and account behavior should remain recognizable so the product grows
as one system rather than a collection of separately themed tools.

Access control remains an invariant. Contextual flexibility must never allow an
agent to reach information the current user is not permitted to access.

## External scholarly catalogs use user-owned credentials

OpenAlex access belongs to the researcher who connects it. Scholens does not
ship or silently fall back to a shared OpenAlex credential. DOI import,
external paper search, author works, and citation graphs use the current
actor's enabled connection; a missing or rejected key produces a clear
connection action. Upload, direct PDF URL, and arXiv import remain independent
of OpenAlex. DOI import uses OpenAlex's catalog result as its deterministic
source and never substitutes a general web-search provider.

Bibliographic hydration remains usable without an OpenAlex connection:
Crossref is consulted first, complete Crossref metadata ends the lookup, and
OpenAlex may fill only missing fields when the current user has connected it.
Provider credentials never enter public DTOs, logs, telemetry, or research
provenance.

Conversation history is durable research provenance. Editing a visible user
prompt creates an alternate path from that point instead of rewriting the
original prompt or discarding its answer. Switching prompt versions restores
the complete selected suffix, sources, worklog, and authorized context for that
alternative. The interface may present one path at a time, but refresh and
other conversation surfaces must agree on which path is active.

## Projects are durable knowledge boundaries for external research agents

A Scholens Project may be the paper knowledge base for research that lasts
months in an external Agent workspace or Git repository. The repository should
bind to the Project by immutable UUID and `scholens://` resource URI in durable
guidance such as `AGENTS.md` or `README.md`; a mutable title is useful context,
not identity. Returning that ready-to-paste binding is part of creating or
reading a Project, not a convention every Agent must reinvent.

The Scholens MCP surface exists to ingest already-known papers and manage the
resulting knowledge: Projects, Library membership, paper content, annotations,
comments, collaborators, jobs, and existing research outputs. It deliberately
does not discover literature on the internet or generate new research outputs.
External Agents remain free to choose their own search and reasoning tools,
while Scholens remains the durable, permission-aware system of record. The
in-product Agent uses the same capability definitions so the two surfaces do
not develop conflicting semantics.

Known DOI, arXiv, and HTTP(S) sources can be imported directly. A local Agent
may also upload a PDF from an explicitly exposed filesystem root through the
official local bridge; the local path never leaves the computer. After
ingestion, the same paper can be searched and cited by an Agent or opened in
the Scholens Web Reader for deep human reading and collaboration.

Agent autonomy does not remove user control. Public sharing, invitations,
access changes, and destructive actions require a bounded impact preview and a
short-lived confirmation tied to the actor, credential, exact arguments, and
current resource state. A changed or replayed confirmation must fail safely.

## Plans should support a complete research workflow

The promotional Basic plan is intentionally useful enough for a researcher to
build a real working library instead of merely evaluating an upload screen.
Researcher is the high-comfort plan intended for future paid access and current
internal team members. The first public release does not mount checkout,
customer-portal, subscription-mutation, or payment-webhook routes; operators
grant expiring Researcher access through the audited private CLI. Current
product limits are:

| Plan       | Papers | Storage | Projects | Papers per Project | Weekly Token Credits | Zotero auto-sync |
| ---------- | -----: | ------: | -------: | -----------------: | -------------------: | ---------------- |
| Basic      |    300 |   5 GiB |       10 |                300 |           30,000,000 | No               |
| Researcher |  5,000 | 100 GiB |      100 |              5,000 |          300,000,000 | Yes              |

Paper count and storage are account-level unique-document quantities. A paper
in a personal Library and any number of Projects owned by the same person is
charged once to that account. Each Project still counts its own memberships,
and its owner—not a collaborator who adds a paper—carries the Project and
account quota responsibility.

An expired entitlement never removes existing research. An over-limit account
remains readable and may remove resources, but cannot add another paper or
Project or begin AI work beyond its current Token Credit limit. Token windows
reset on Monday UTC and continue to use provider-reported raw total tokens.

The entitlement resolver keeps paid subscriptions and explicitly expiring
product grants independent so future charging does not require a schema or
ownership rewrite. During the first release only product grants are issued: an
internal grant never pretends that a payment occurred.

## Zotero is a read-only personal-library bridge

Scholens may connect to a user's personal Zotero library as a one-way import
source. The connection never writes to Zotero and does not expose Group
Libraries. Scholens requests only personal-library read access, but accepts an
OAuth key when those required capabilities are present even if Zotero adds
unused privileges to the key; those privileges do not expand product behavior.
The first supported paper types are journal articles, conference papers, and
preprints.

Every account may browse Zotero, import selected papers manually, and run a
manual annotation sync for papers it already imported. A manual sync never
silently expands the Scholens Library. Researcher additionally receives
scheduled annotation sync and may explicitly enable automatic import for
papers added to Zotero in the future. Automatic import is off by default and
starts from the library version observed when it is enabled, so existing
Zotero papers are not backfilled unexpectedly.
An account has at most one active Zotero import or sync. Its durable status is
restored after refresh, and automatic-import progress never advances beyond a
temporary provider, download, or Scholens quota failure.

Losing Researcher access pauses automatic behavior without discarding the
preference or imported research; restoring access resumes it. Disconnecting
Zotero prevents future browsing and synchronization but preserves papers,
annotations, and audit history already accepted by Scholens. Zotero
annotations are append-only in Scholens by their stable Zotero annotation key:
the integration does not delete or overwrite Scholens annotations and never
syncs them back to Zotero.

## Reading transformations preserve the paper as source of truth

Translation and reading reflow are derived views of an authorized paper. They
must never overwrite the uploaded PDF, alter its canonical metadata, or become
an alternate paper record. PDF remains the final authority. Reflow may repair
visible structure and corrupted presentation only when the result remains
traceable to the source page and coordinates; uncertain content degrades to an
explicit PDF fallback instead of a plausible reconstruction. Derived views
exist to reduce interaction cost, especially on narrow mobile screens where
selection-based tools are difficult to operate.

The reflow product is a semantic PDF-to-Markdown reading view, not a recreation
of paper pages and not an AI summary. It preserves academic order and meaning
while removing page whitespace, headers, footers, and column geometry that make
PDFs difficult to read on narrow screens. MinerU's structured content list is
the evidence boundary; rendered blocks retain source spans so navigation and
auditing always return to the PDF.

AI reflow is an explicit user action and requires that user to connect a MinerU
token in Settings. Scholens does not provide a shared MinerU credential and does
not start reflow automatically after PDF ingestion. Missing or rejected
credentials lead to a clear connection action rather than a generic processing
failure; failed attempts remain retryable without weakening the PDF reading
path. The same user-owned connection may rescue a scanned or locally
unparseable PDF, while a digital PDF retains its deterministic local fallback
when the remote rescue is unavailable.

Interface locale and paper-content language are independent preferences. A
reader may use an English interface while translating a paper into Chinese, or
the reverse. Selection translation starts only from an explicit selection and
may run automatically after that selection stabilizes. Full-paper translation
is available from AI reflow, defaults to bilingual source-and-translation
reading, and remains lazy at the visible semantic-block boundary so the product
does not spend credits on unread text. Author names, affiliations, code,
equations, and image pixels are not translated; references require opt-in.

Completed translation is durable and reusable. Its identity includes the
normalized source, language direction, custom instructions, prompt revision,
and AI runtime profile revision. A cache hit is free and does not consume a
second provider request; raw selected source text is not retained in the cache.
Access to a cached result is always re-authorized against the paper before the
result is returned.

## Annotations are anchored threads, not separate highlight and comment silos

Reader annotations use one durable mental model across personal reading and
Project collaboration. An annotation thread owns a stable passage anchor, one
visual mark and color, an author, an immutable audience, and zero or more
chronological comments. A highlight is a thread without a comment; commenting
on a selection creates the same thread with its first comment. Comments do not
own colors, visibility, or recursively nested reply trees.

Personal annotations remain visible only to their creator. Project annotations
belong to one specific Project and are visible to its current members; they
must never become document-global merely because the same paper appears in
another Project. Leaving a Project immediately removes access to its threads,
while personal annotations remain independent.

Removing a paper from the personal Library also removes that user's personal
highlights and notes anchored to the paper. This is an intentional personal
data deletion boundary: adding the same shared Document again starts with a
clean personal reading layer. Project references, Project discussions, and
other users' data remain untouched.

Collaborative discussion protects authored contributions. People edit and
delete only their own comments. A thread with another person's reply cannot be
hard-deleted by its creator; Project discussion is concluded by resolving it
and may later be reopened by an authorized Project editor. Audience is chosen
when a thread is created and cannot be changed afterward.

In a Project reading context, personal marks and that Project's discussions are
shown together with explicit audience labels. Highlighting defaults to personal
because reading marks are often private; starting a comment defaults to the
current Project because its purpose is discussion. Color classifies the marked
passage and never stands in for author identity or comment ownership.

Reader distinguishes those derived modes without splitting the durable model:
a comment-free Highlight paints one quiet translucent fill, while a Note or
Discussion uses the same color as an underline so commentary never obscures the
source. The annotation rail remains ordered by the anchored passage, keeps all
comments visible as one compact chronological timeline, and reduces the quote
to a one-line locator; selecting or hovering a card emphasizes the source
anchor but never changes list order.

The interface derives three presentation modes from that one aggregate: a
thread with no comments is a highlight; a commented personal thread is a note;
and a commented Project thread is a discussion. Only Project discussions have
an open/resolved lifecycle. Personal highlights and notes remain reference
material rather than tasks, and comment-free Project marks are removed rather
than resolved.

Concrete event fields and tool schemas remain implementation contracts, but
the single-agent behavior and disclosure boundary above are durable product
requirements.
