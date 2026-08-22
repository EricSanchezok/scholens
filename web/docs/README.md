# Scholens Web Engineering Handbook

This directory is the operating contract for the replacement frontend. Its
purpose is to keep the codebase easy to change as product routes are added.

## Source-of-truth order

When two sources disagree, use this order:

1. Executable contracts: TypeScript, generated schemas, tests, and CI.
2. Repository architecture decisions in [`docs/decisions/`](../../docs/decisions/README.md).
3. The engineering guides in this directory.
4. Figma annotations and product notes.

Figma remains the source for layout intent, visual hierarchy, interaction
states, and design acceptance. The repository is the source for token values,
runtime behavior, accessibility, data contracts, and component APIs.

## Guides

| Guide                                                       | Read it when                                                                       |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| [Frontend change governance](./frontend-governance.md)      | Adding, changing, or deleting a page, module, component, or token                  |
| [Architecture](./architecture.md)                           | Adding a route, feature slice, provider, shared state, or dependency               |
| [Component development](./component-development.md)         | Creating or importing a component                                                  |
| [Design tokens](./design-tokens.md)                         | Changing color, spacing, radius, theme, or Figma variables                         |
| [Visual language](./visual-language.md)                     | Applying shared surface hierarchy or adapting ReUI and React Bits recipes          |
| [Product identity](./product-identity.md)                   | Changing the Scholens raven, app icons, metadata, or brand lockups                 |
| [Motion system](./motion.md)                                | Designing animation, transitions, layout continuity, or reduced motion             |
| [Web performance](./performance.md)                         | Changing navigation feedback, RUM, bundles, or performance budgets                 |
| [Installable Web App](./installable-web-app.md)             | Changing installation, standalone behavior, service workers, or offline boundaries |
| [Internationalization](./internationalization.md)           | Adding UI copy, locale behavior, formatting, or another language                   |
| [Authentication foundation](./authentication-foundation.md) | Building auth UI, session behavior, responsive auth layout, or mocks               |
| [Home experience](./home-experience.md)                     | Changing the Home shell, composer, recents, or conversation stream                 |
| [Library experience](./library-experience.md)               | Changing Papers, Outputs, import, filtering, or Library actions                    |
| [Reader experience](./reader-experience.md)                 | Changing PDF reading, paper conversations, annotations, or details                 |
| [Projects experience](./projects-experience.md)             | Changing Projects lists, details, papers, outputs, or Project chat                 |
| [Settings experience](./settings-experience.md)             | Changing account panels, usage, keys, connections, or preferences                  |
| [Documentation experience](./documentation-experience.md)   | Changing public MCP and machine-readable documentation                             |
| [API development](./api-development.md)                     | Changing a backend contract or adding a request/query                              |
| [Testing](./testing.md)                                     | Choosing test scope or adding a network/interaction state                          |
| [New feature checklist](./new-feature-checklist.md)         | Starting and finishing every product feature                                       |
| [Architecture decisions](../../docs/decisions/README.md)    | Deliberately changing a foundational repository or frontend rule                   |

## Maintenance rule

Documentation changes ship with the code that invalidates them. Do not create
parallel guides in feature folders. Feature-local README files may explain
domain behavior, but architecture, component, token, API, and testing rules
remain centralized here.
