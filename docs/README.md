# Documentation

User documentation for Botasaurus Automation Studio, built with
[Mintlify](https://mintlify.com).

## Preview locally

```bash
npm i -g mint        # the Mintlify CLI
cd docs
mint dev             # serves the docs at http://localhost:3000
```

The CLI reads `docs.json` for navigation and theme, and renders the `.mdx` pages.

## Structure

```
docs/
  docs.json              Navigation, theme, and metadata
  introduction.mdx       Landing page
  quickstart.mdx         Install → first automation in ~10 minutes
  concepts/              Architecture, recipes, runs & the agent
  guides/                AI automation, recording, self-healing, testing,
                         datasets, scheduling, stealth, CLI
  reference/             Recipe DSL, Botasaurus config, REST API
  best-practices.mdx     Reliability, stealth, and safety guidance
  images/                Hero + favicon SVGs
```

## Editing

Pages are MDX (Markdown + components). The components used here —
`<Card>`, `<CardGroup>`, `<Steps>`, `<Tabs>`, `<Accordion>`, `<Note>`,
`<Tip>`, `<Warning>`, `<ParamField>`, `<ResponseField>`, `<CodeGroup>` — are
all built into Mintlify. To add a page, create the `.mdx` file and list it under
the appropriate group in `docs.json`.

## Deploying

Connect the repository on the [Mintlify dashboard](https://dashboard.mintlify.com)
and point it at the `docs/` folder; pushes to the default branch publish
automatically. No build step is required for the docs themselves.
