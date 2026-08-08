# Feel prototype

One page, playable solo, built to answer the question the mockups can't:
**does it actually feel good?**

Open `dist/clink-feel.html` — or run the dev version, `feel.html`, which links the
three modules separately instead of inlining them.

```
prototype/
├── engine.js        Texas Hold'em: deck, 7-card evaluator, betting, side pots, bots
├── engine.test.js   66 tests — run: node chipless/prototype/engine.test.js
├── feel.js          haptics + synthesised audio, one interface, three backends
├── feel.html        the app (dev: links chips.js / engine.js / feel.js)
├── build.js         inlines all three into a single file for publishing
└── dist/
    └── clink-feel.html    self-contained, no external requests
```

## What it does

A real hand against three bots. Tap a chip stack to add one chip to your bet — each
tap is one Taptic tick and one clink, pitch rising as the pile grows. Drag a chip
across the betting line, or fling one upward to shove. Tap the pot to zoom into it.
Win, and the rake cascades toward you at a length scaled to the pot.

The **Feel lab** drawer at the bottom edge holds the chip-skin switcher (A/B/C/D),
per-channel toggles for haptics / sound / motion, manual test buttons, and live
diagnostics.

## The three things to check on a physical iPhone

1. **A real Taptic tick when you tap a chip.** The diagnostics row reports whether
   `<input type="checkbox" switch>` is supported *and* whether the page is inside an
   iframe — so if it doesn't fire, you can tell which reason.
2. **Sound with the ringer switch off.** The most likely thing to be quietly broken:
   on iOS, Web Audio is routed to the ringer channel. The silent-`<audio>`-loop fix is
   in, and the drawer reports whether the loop is actually running.
3. **Latency.** Output latency is measured and displayed rather than guessed.

Then play ten hands and judge whether tap-tap-tap-to-bet is fun, whether the payout
lands, and whether the pot zoom reads as a camera move rather than a modal.

## Notes

- **The poker is real, not scripted.** The evaluator is validated two ways: hand-picked
  cases (wheel straights, flush-beats-straight, kickers) and a statistical check that
  category frequencies over 200k random hands match published Hold'em figures.
- **Chip conservation** is asserted across 2215 bot-vs-bot hands: the money on the table
  never drifts by a cent. All money is integer cents.
- **Pot piles use a different breakdown from wallets.** A literal breakdown of $200 is
  two $100 chips, which is an anticlimax at the exact moment the design is trying to
  land, so big chips get split down until the pile reads as a pile.
- **Chip skins are one variable.** `CHIP[skin]`, `stack(skin,…)`, `pot(skin,…)` — switching
  A→D repaints everything and touches nothing else. That's what makes skins sellable
  later without a rewrite.
- Rendering reuses `../mockups/chips.js` unmodified.
