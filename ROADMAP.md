# Roadmap

What is planned, in order. Each item names the gap it closes; see CHANGELOG.md for what shipped.

## Next

1. **Harder worked examples.** Complex multi-part subjects (a 70 m antenna, the Apollo Lunar Module, the Curiosity rover from NASA's public-domain 3D resources), run through the decomposition and pass gates. The current examples are mostly single bodies.
2. **Rebuild `espresso-cup` from `img2cad camera`.** Its model still uses the hand-written fit.
3. **First PyPI release.** The release workflow is ready; it needs the one-time trusted-publisher setup on pypi.org, then a `v0.12.0` tag. The Claude Code install is verified; Codex, Cursor and Gemini CLI installs are still untested.

## Later

- **Learned segmentation.** Optional SAM-style masks, behind an extra, with the current polygon/seed tool as the default.
- **Multi-view input beyond orthographic views.** `img2cad hull` takes front/right/top silhouettes; next is hulls from arbitrary fitted cameras (`img2cad camera` frames).
- **Category tracks.** The checklists exist (MODELING.md); each still needs a tested worked example.
- **More outputs.** DFM checks for machining and sheet metal.
