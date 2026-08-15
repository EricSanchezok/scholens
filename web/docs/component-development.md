# Component Development

## Classify before creating

Place a component according to the language and dependencies it owns:

| Kind                      | Location                            | May contain product vocabulary? | May request data?         |
| ------------------------- | ----------------------------------- | ------------------------------- | ------------------------- |
| Design-system primitive   | `src/components/ui`                 | No                              | No                        |
| Async/empty-state pattern | `src/components/feedback`           | Only through props              | No                        |
| Product component         | `src/features/<feature>/components` | Yes                             | Prefer data passed in     |
| Route composition         | `src/app` or feature `routes`       | Yes                             | Through feature API layer |

Sidebar, Composer, ConversationMessage, PaperRow, ProjectRow, and Reader tools
are product components, not UI primitives. A component is not promoted merely
because two mockups look similar; promote it when its semantics and behavior are
actually shared.

## Component API rules

- Prefer semantic props such as `tone`, `size`, `loading`, and `invalid` over
  visual props such as `gray`, `rounded12`, or `left4`.
- CVA owns finite visual variants. Call-site `className` is for layout and rare
  composition, not for redefining a component's states.
- Support controlled and uncontrolled usage only when both are real needs.
- Forward native attributes and refs when the underlying control supports them.
- Preserve native semantics; never make a clickable `div` imitate a button.
- Loading controls retain their accessible name and prevent duplicate actions.
- Disabled and read-only are distinct states.
- Destructive actions use explicit language and `AlertDialog` when confirmation
  is necessary.

## Visual and interaction rules

- Consume semantic Tailwind utilities backed by generated variables.
- Never write product colors directly in a component.
- Use the Scholens `Icon` wrapper with a named export from
  `src/design-system/icons/semantic-icons.ts`. Product code under `app/` and
  `features/` must not import `iconoir-react` directly, import another icon
  library, or manually redraw a glyph. `design:check` enforces this boundary.
- Every product meaning has exactly one semantic icon name, and every Iconoir
  glyph in the registry belongs to exactly one meaning. The same meaning must
  reuse the same semantic export everywhere; a glyph must not be registered a
  second time for a conflicting action. Extend the registry before adding a
  new product icon, and use the generic `AddIcon` only for meaning-neutral
  addition—not New conversation, Ask, Add annotation, or Edit.
- Rows and toolbars that mix icons with labels reserve an explicit, fixed-size,
  non-shrinking icon slot and align text in a separate flexible slot. Do not
  rely on each SVG's visible bounds, ad hoc margins, or the label length to
  establish alignment. Touch target size and glyph size are separate concerns.
- Every interactive control must have default, hover, pressed, focus-visible,
  disabled, and loading behavior where applicable.
- Keyboard focus visuals are a design-system primitive. Buttons, links, and
  product disclosures consume `keyboardFocusRing` from `components/ui`; feature
  code must not author its own focus border, outline, ring, or shadow. The
  shared treatment is intentionally one semantic pixel and appears only for
  `:focus-visible`, so pointer and touch activation never add a heavy black or
  white rectangle. `design:check` enforces this boundary for `app/` and
  `features/`.
- Text controls distinguish input modality: pointer and touch focus keep the
  resting border unchanged, while keyboard navigation receives the semantic
  focus ring. Composite controls delegate that keyboard cue to their outer
  interaction surface instead of drawing a second rectangle around the native
  input.
- Every `SelectTrigger` uses one light-line, large-radius surface. Hover, pressed,
  and open state change only its quiet background; they never strengthen the
  border. The default density is 44 px, while `compact` preserves that touch
  size and reduces to 36 px in dense desktop toolbars. Call sites may own width
  but must not reconstruct the surface, radius, or state treatment. Select and
  Dropdown menus use one elevated surface with a restrained raised shadow,
  local hover/selected rows, and 44 px touch rows that compact to 36 px on
  desktop.
- Dialog containers suppress the browser's native focus outline; keyboard focus
  remains visible on the first real interactive control through the shared
  focus primitive.
- Icon-only controls require an accessible label and usually a Tooltip.
- Narrow containers and long English or Simplified Chinese content must not
  break layout.
- User-visible product copy uses `next-intl` message keys. Do not concatenate
  translated fragments or hardcode fallback English inside product components.
- UI primitives remain language-agnostic. Callers provide labels and content;
  a primitive translates only a universal default that it explicitly owns.
- Motion must explain state or spatial continuity and respect reduced-motion.
  Use the recipes and runtime boundary in [Motion system](./motion.md); product
  code must not add raw timing, easing, keyframes, or another animation runtime.

### Collection rows and nested actions

Collections keep their native structure (`table`, `article`, `li`, or another
domain-appropriate element); do not route them through a generic row component.
They share this interaction contract instead:

- The row uses `bg-hover` for hover and `focus-within`, and `bg-pressed` for
  touch/pressed feedback. It consumes `motion-control`; reduced mode removes
  spatial press feedback while retaining the short semantic state change.
- One real Link owns the primary content region. Nested checkboxes, overflow
  menus, and other controls are siblings of that Link and must not trigger its
  navigation. A semantic table keeps the title as its only keyboard Link;
  non-action cells may extend pointer navigation without adding duplicate Tab
  stops.
- Overflow entry points use `OverflowMenuButton`. `contextual` visibility is
  revealed by row hover, row focus-within, current state, or an open menu on a
  fine pointer; touch layouts always show it. The button owns a 36 px desktop
  and 44 px touch target, `bg-pressed` hover/open feedback, the shared focus
  ring, and its accessible label.
- The row and its overflow button deliberately use different feedback colors;
  do not add scaling, glow, bounce, gradients, or a second page-local More
  button recipe.

## Action feedback contract

Classify an action by what changes before choosing its feedback. This prevents
each feature from inventing a different success animation, timer, or toast:

| Action kind                                      | Required response                                                                                                        |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Immediate, local, reversible action such as Copy | Keep focus in place; expose pending, success, and error through the shared transient-action pattern; reset automatically |
| Persistent selection or toggle                   | Let the changed control state be the confirmation; do not add a redundant success toast                                  |
| Visible async mutation                           | Keep the initiating control busy and block duplicate submission; resolve into the updated surface or an inline error     |
| Background async mutation                        | Confirm acceptance near the initiator, then use the owning status surface or Toast for completion/failure                |
| Destructive mutation                             | Use explicit destructive language and confirmation when the result is difficult to recover                               |
| Navigation or disclosure                         | The destination or expanded state is the feedback; do not announce success                                               |

Use `TransientActionIconButton` for icon actions whose result is brief and does
not create a persistent surface. It owns the `idle → pending → success/error →
idle` lifecycle, timer cleanup, stable focus target, tooltip, and polite live
announcement while continuing to render the shared `IconButton`. Use
`CopyActionButton` for clipboard writes; product code must not access
`navigator.clipboard` directly. Callers provide localized labels and the value,
not another timer or visual state. Errors must be visible and announced; never
silently catch them.

Do not use transient feedback when the resulting content is already visible,
and do not create a global action-state Context. The state belongs to the
control that initiated the action. Motion is limited to the `feedback` or
`standard` semantic duration without bounce or unrelated layout movement;
reduced motion retains the state change.

## Motion ownership

Shared primitives own their own CSS-first motion recipe. A feature must not add
enter/exit classes to Dialog, Sheet, Popover, Tooltip, Select, Dropdown, Toast,
Button, Input, Checkbox, Switch, Progress, Spinner, or Skeleton call sites.
Product components may use the runtime only for a bounded list, panel,
state-replacement, or container-layout change. Import `m`, `AnimatePresence`,
`LayoutGroup`, variants, and transitions from `@/design-system/motion`; direct
`motion/*` imports are an architecture violation.

An animated wrapper preserves the semantic element it replaces. Lists remain
lists, table rows remain rows, panels remain complementary regions, and motion
never creates the click target. Exit choreography cannot delay focus return,
mutation state, URL state, or navigation. Review every new choreography in
Storybook Full and Reduced modes before adding it to a feature.

Expected creation and navigation flows follow the same rule. Creating a
conversation, opening it, and rendering its first turn are one visible state
transition; do not add a success Toast that merely restates the selected scope
or destination. Toasts are reserved for failures, access or concurrent-state
changes that invalidate the visible action, and background completion whose
result is not otherwise present on the current surface. Copy must describe the
user-facing consequence rather than an internal routing, cache, or scope event.

## External component intake

Before accepting external source code:

1. Check license, maintenance activity, React/Next SSR compatibility, keyboard
   behavior, and accessibility.
2. Confirm Radix cannot already provide the required primitive.
3. Place the source in the correct UI or feature boundary.
4. Replace its colors, spacing, type, icons, global CSS, and portals with
   Scholens conventions.
5. Remove bundled themes and overlapping primitive/icon dependencies.
6. Add stories, interaction tests, dark appearance, narrow-container coverage,
   and axe checks.

shadcn/ui is a source distribution mechanism, not a runtime design dependency.
Imported source becomes Scholens-owned code and follows this handbook.

## Changing and deleting components

Before changing a shared primitive, inspect every consumer and its stories. A
one-screen visual need stays feature-owned unless it expresses a real shared
state; call-site classes may position a primitive but must not redefine its
color, focus, disabled, loading, validation, typography, or elevation contract.

Before deleting a component, search its direct imports, public barrel exports,
stories, tests, docs, messages, and Figma acceptance mappings. Delete the source
and obsolete coverage together. Do not leave an alias or compatibility wrapper
without a documented active consumer.

## Storybook contract

Stories are executable component states, not a screenshot gallery. A new
interactive component normally includes:

- Default and all meaningful variants/states.
- Light and Dark appearance verification through the global toolbar.
- Long/localized content and Narrow panel coverage.
- Keyboard interaction in a `play` function.
- Loading, empty, error, slow, or offline behavior when relevant, using MSW.
- No serious or critical axe violations.

Keep stories beside their component or feature. Use deterministic fixtures;
stories must not depend on the FastAPI process or a developer account.

## Component maturity

Maturity describes reuse confidence, not visual importance:

| Status          | Meaning                                                                    |
| --------------- | -------------------------------------------------------------------------- |
| Ready           | Public API and required states are covered; product features may reuse it  |
| Needs hardening | Foundation exists, but a real feature must close remaining state/test gaps |
| Feature-owned   | Product semantics belong to one feature; do not promote it to generic UI   |

Current baseline:

| Component group                                      | Status          |
| ---------------------------------------------------- | --------------- |
| Button, IconButton, LinkButton, OverflowMenuButton   | Ready           |
| Input, PasswordInput, Field, Checkbox, Select        | Ready           |
| Alert, Toast, Progress, Skeleton, AsyncFeedback      | Ready           |
| TransientActionIconButton, CopyActionButton          | Ready           |
| Dialog, AlertDialog, Popover, Tooltip                | Ready           |
| Combobox and complex responsive overlay compositions | Needs hardening |
| AuthViewport and Auth session harness                | Feature-owned   |

Update this table when a feature exposes a missing state. Do not silently work
around a `Needs hardening` primitive in page-local code.

## Definition of done

- The component is in the correct boundary and has no forbidden imports.
- Its public props express behavior rather than one screen's geometry.
- Semantic tokens and the Icon wrapper are used consistently.
- Keyboard, focus, disabled, loading, error, long-content, and narrow behavior
  are covered as applicable.
- Storybook and automated tests pass in Chromium.
- Product-specific behavior is not duplicated in a second feature.
- `pnpm design:check` proves tokens, utilities, theme parity, and the Storybook
  review axes remain intact.
