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

`artifacts/` contains hand-drawn, self-contained SVG pages in a dark "blueprint"
style (no external dependencies — plain HTML/SVG, works offline and on GitHub
Pages). Open `artifacts/index.html` in a browser. These are the presentation
layer; the Mermaid sources in `docs/` remain the source of truth. When a diagram
changes, update both.

To serve: enable GitHub Pages, or `npx serve diagrams/artifacts` locally.
