# Roadmap

What is planned, in order. Each item names the gap it closes; see CHANGELOG.md for what shipped.

## Next

1. **Harder worked examples.** Complex multi-part subjects (a 70 m antenna, the Apollo Lunar Module, the Curiosity rover from NASA's public-domain 3D resources), run through the decomposition and pass gates. The current examples are mostly single bodies.
2. **Rebuild `espresso-cup` from `img2cad camera`.** Its model still uses the hand-written fit.
3. **A multi-photo worked example.** `img2cad hull` accepts photos from any angle with fitted cameras; it needs a real example run end to end.
4. **Verify the other hosts.** The Claude Code install is verified; Codex, Cursor and Gemini CLI installs are still untested.

## Later

- **SAM 2 against real photos.** `img2cad mask --sam` is tested with a stand-in predictor; measure it on the examples' photos.
- **Category tracks.** The checklists exist (MODELING.md); each still needs a tested worked example.
- **More standard parts.** Gears, pulleys, linear rails, servo motors; threads as real helices on request.
- **Printer hand-off.** Sending G-code to a printer (OctoPrint, PrusaLink, Bambu LAN) needs printer credentials; today `img2cad slice` stops at the file.
