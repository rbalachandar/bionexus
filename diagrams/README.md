# Diagrams

Standalone Mermaid sources for the architecture diagrams. All diagrams are also
embedded inline in the docs (GitHub renders them natively). To export images,
install [`mermaid-cli`](https://github.com/mermaid-js/mermaid-cli) and run:

```sh
for f in diagrams/*.mmd; do
  mmdc -i "$f" -o "${f%.mmd}.svg"
done
```

See:
- `docs/README.md` (top-level layered view)
- `docs/architecture.md` (Block D lab pipeline)
- `docs/flows.md` (iteration loop, fork/snapshot state machine, wet-lab round trip,
  campaign pipeline, deployment view)

## Artifact pages

`artifacts/` contains styled, self-contained HTML pages (Claude-artifact style)
rendering every diagram with Mermaid v11 from CDN — open `artifacts/index.html`
in a browser. Regenerate after editing the diagram definitions inside
`generate_artifacts.py`:

```sh
python3 diagrams/generate_artifacts.py
```

To serve publicly (GitHub Pages), enable Pages from the repo Settings with the
root of a branch, then browse `diagrams/artifacts/index.html`, or run
`npx serve diagrams/artifacts` locally.
