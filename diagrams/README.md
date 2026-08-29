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
