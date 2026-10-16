# Roadmap

What is planned, in order. Each item names the gap it closes; see CHANGELOG.md for what shipped.

## Next

1. **Harder worked examples.** Complex multi-part subjects (a 70 m antenna, the Apollo Lunar Module, the Curiosity rover from NASA's public-domain 3D resources), run through the decomposition and pass gates. The current examples are mostly single bodies.
2. **Rebuild `espresso-cup` from `img2cad camera`.** Its model still uses the hand-written fit.
3. **Verified installs.** Install the plugin in Claude Code, Codex, Cursor and Gemini CLI from a clean machine and record the steps. Publish to PyPI.

## Later

- **Learned segmentation.** Optional SAM-style masks, behind an extra, with the current polygon/seed tool as the default.
- **Multi-view input.** Intersect silhouettes from two or more photos (visual hull) as a starting body; mark unseen regions as estimates.
- **Category tracks.** Short, tested recipes per subject type (characters, animals, vehicles, buildings, mechanical parts), like the existing technique table but with their own detail checklists.
- **More outputs.** PDF engineering drawings, DFM checks for machining and sheet metal.
