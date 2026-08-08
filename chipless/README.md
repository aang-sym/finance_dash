# Clink — a tactile chipless poker app

Design exploration for a rebuild of [playchipless.com](https://www.playchipless.com) around the
thing it throws away: the **feel** of poker chips.

The incumbent solves a real problem — poker night with cards but no chips — but solves it as a
*form*: type a number, tap Bet, read a ledger. This explores the alternative where money is
physical again: chips you drag with your thumb, a pot you lean over to inspect, and a payout that
lands like Balatro paying out a blind.

Unrelated to the `finance_dash` project it currently sits inside; kept self-contained so it can be
lifted into its own repo once the direction settles.

## Contents

```
chipless/
└── mockups/
    ├── index.html       start here — links all six with context
    ├── chips.js         the chip factory, shared by every page
    ├── chip-lab.html    01 · four art directions at true size
    ├── table.html       02 · the hero screen, my turn on the flop
    ├── pot.html         03 · the pot inspector, zoomed
    ├── showdown.html    04 · the payout, frozen mid-rake
    ├── landing.html     05 · host / join
    └── stats.html       06 · settle up + session stats
```

Open `mockups/index.html` in a browser. No build step, no dependencies.

**Scope: look-and-feel only.** These are static — no drag, no audio, no haptics. They exist to
settle the art direction and screen architecture before any application code is written. Design
reasoning is annotated beside each screen.

## The constraint that shapes everything

iOS Safari has **no Vibration API** and never has. The only route to the Taptic Engine is a
side-effect of WebKit's native `<input type="checkbox" switch>` control, and **iOS 26.5 patched
script-triggered toggles** — only a direct finger tap on the real control still fires a tick, at a
single fixed intensity.

Two consequences:

- **No escalating haptic patterns on web.** A Balatro-style `tick-tick-THUD` payout rhythm is
  impossible from script.
- **No haptics on passive events.** You cannot buzz someone's phone when another player bets.

So the interaction is built around what *is* possible: **one direct tap, one real tick.** Tapping a
stack four times to bet $12 gives four genuine Taptic ticks, each paired with a rising-pitch clink.
The constraint produced a better interaction than a slider would have.

A second trap: at a real poker night every phone is on silent, and on iOS Web Audio routes to the
*ringer* channel while `<audio>` tags don't ([WebKit #237322](https://bugs.webkit.org/show_bug.cgi?id=237322)).
Untreated, the entire feel layer is inaudible for exactly the users who matter most. Fixable with
the silent-`<audio>`-loop technique, but it has to be designed in from the start.

Native iOS is the only way to get the haptics originally imagined — `CHHapticPattern` with
intensity/sharpness curves, plus continuous haptics during a drag. **That platform decision is
deliberately still open.** Web owns the zero-install join path, which is arguably the whole product;
native owns the feel. See the design plan for the full tradeoff.

Sources: [project-fathom](https://github.com/m1ckc3s/project-fathom) ·
[ios-haptics](https://github.com/tijnjh/ios-haptics) ·
[mdn/browser-compat-data#29166](https://github.com/mdn/browser-compat-data/issues/29166)

## Art direction

Four directions are rendered in full in `chip-lab.html`, each built by a different method on
purpose — A is flat shapes plus grain, B is generated hypotrochoid line geometry, C is masked
cut-outs, D is real Bayer-matrix dither.

| | Direction | Reads at 40px | Greyscale |
|---|---|---|---|
| **A** | Screen-printed token *(recommended)* | excellent | holds — value bands + spot count |
| **B** | Banknote / intaglio | poor — hairlines collapse | trivially, it's monochrome |
| **C** | Board-game token | good — silhouette does the work | holds — shape-coded |
| **D** | 1-bit dithered | good, 6 densities is the ceiling | by construction |

Two rules throughout:

- **These are tokens, not casino chips.** Photoreal clay reads as mud at 44px and "casino" is the
  wrong register for a kitchen table.
- **The felt is not green.** Green baize plus gold plus red is gambling-app visual language. The
  ground is warm paper; the pot is a recessed darker well, so money moves *into* shadow.

Every denomination is coded three ways at once — colour value, edge-spot pattern, and numeral — so
it survives a dim room and a colourblind eye. Stacks render at ~15° because across a table you read
a stack by its edge, not its face.

## Notes for whoever builds this

- **Chip scatter is seeded**, never random. In the app the seed is `(handId, actionIndex)` so every
  player's pot is identical down to the pixel. Random-per-client would quietly break the premise
  that everyone is looking at the same table.
- **The chart palette is not the chip palette.** The chip colours fail as line series — two of them
  fall below the chroma floor and read gray, and pine↔oxblood is ΔE 6.0 under protanopia. `stats.html`
  carries a separately validated four-colour set.
- **Integer cents everywhere.** No floats, ever.
- **All money maths server-side.** The client never holds a balance.
- Keep chips as DOM/CSS/SVG rather than Canvas — a Capacitor shell then reuses the view layer
  verbatim if the native path is taken later.
