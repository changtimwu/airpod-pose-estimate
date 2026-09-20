# web/ — the interface

Owners 03 (INTERFACE) and 04 (EXPERIENCE). One pose, **Triangle**, and the longer
you hold it the bigger the voxel tree gets.

Transport is SSE, matching Bridge's scaffold: frames on `GET /stream`, commands
as `POST /command`. Served same-origin, so there is no CORS and no second port.

```
index.html     structure + the frozen §8 ids          Owner 04
style.css      the entire visual system               Owner 04
app.js         SSE client, state → data-* and CSS     Owner 03
voxel-tree.js  the grower and the isometric renderer  Owner 03
pose-dial.js   the live forearm dial                  Owner 03
mock.js        a fake arm at 25 Hz, no hardware       Owner 03
```

`style.css` reads state; it never sets it. `app.js` writes `data-*` attributes
and CSS custom properties; it never sets a style or names a colour. That is §8
of the contract, and it is why the whole look can be rebuilt at T+55 without
opening a file Owner 03 has open.

---

## Run it

```bash
python -m http.server 8765 --directory airpod-pose-estimate/web
```

Or let Bridge serve it — the server already does, same origin.

| URL | What you get |
|-----|--------------|
| `/` | live if `/stream` answers, otherwise the mock |
| `/?mock=1` | forces the mock **even when the server is up** — the rehearsal path |
| `/?mock=1&held=90` | starts the tree at 90 s of growth, for stills and camera checks |

**Mock controls:** move the pointer (Y is forearm pitch, X is roll), or hold
<kbd>space</kbd> to snap into the pose and stay there.
Keyboard everywhere: <kbd>C</kbd> calibrate · <kbd>S</kbd> start · <kbd>K</kbd>
skip · <kbd>R</kbd> reset.

---

## What SIGNAL has

Done: `python/airpod_pose/poses.json` now streams a single pose, Triangle
(Trikonasana), per issue #3. The tree is not a pose — it is how long you held
one, so the screen and the sequence agree on exactly one thing to hold.

```json
"sequence": ["triangle"],
"triangle": {
  "label_en": "Triangle", "label_sa": "Trikonasana",
  "hold_ms": 6000,
  "pitch": [58, 88],          // MEASURE THIS. Still a guess.
  "roll":  [45, 135],
  "exit_margin_deg": 8
}
```

`web/mock.js` mirrors that band, so the rehearsal path and the live path agree
about what counts as held. If you retune one, retune the other.

**One caveat on the band, from issue #3.** `pitch: [58, 88]` reaches into the
region where Euler angles stop being separable: with 0.5° of real sensor noise,
reported roll wobbles ±14° at 88° of pitch, which is wider than
`exit_margin_deg: 8`. Near the top of that range the pose can flicker in and out
while the body is perfectly still. If it does that on stage, narrow the pitch
band rather than widening the exit margin.

Two optional additive fields the UI uses if they turn up, and does without if
they do not (§4 says unknown fields are ignored, never rejected):

- `pose.band: [lo, hi]` — the pitch band, so the dial can draw the target arc
  from YAML instead of guessing. Without it the arc is simply not drawn.
- `session.labels` — already in Bridge's scaffold, keep it.

---

## The one deviation from the contract, stated plainly

`pose.hold_ms` resets to zero the moment you leave the band. **The tree must
not.** A single wobble cannot be allowed to raze forty seconds of work in front
of judges.

So the tree runs off a locally integrated `held`, which gains at 1× while
matched and drains at **0.25×** while not. A three-second stumble costs three
quarters of a second of tree. `hold_ms` still drives the inner ring exactly as
specified, and `target_ms` still scales it.

Nothing else departs from the wire contract. No field is renamed, none removed.

---

## Growth

Roughly **five blocks a second**, plus a small head start so the first two
seconds already show a plant. Milestones:

| | | |
|---|---|---|
| Seed | 0 s | one block |
| Sprout | 3 s | ~20 blocks |
| Sapling | 9 s | ~50 |
| Tree | 22 s | ~115 |
| Canopy | 40 s | ~205 |
| Bloom | 65 s | ~330, blossom appears |
| Ancient | 65 s+ | one tree ring every 30 s, and the trunk thickens |

It does not stop at Bloom. Past it the crown keeps rising, new shoots keep
throwing, and every ring lays another course of bark on the trunk — which is
what stops a very long hold turning into a mushroom. The camera pulls back on a
one-second lag as the tree outgrows the frame. Hard stop at 1500 blocks, about
five minutes of holding.

Tuning lives at the top of `app.js` (`VOX_PER_SEC`, `DECAY`, `STAGES`) and
`voxel-tree.js` (`BUDGET`, `GROUND_R`). None of it needs a restart — it is a
reload.

---

## Notes for whoever touches this next

- **The palette is locked to dawn**, deliberately not wired to
  `prefers-color-scheme`. A judge whose laptop is in dark mode should not see a
  different demo than the one we rehearsed. `<html data-theme="dark">` opts into
  the predawn variant if you want it.
- **The tree is deterministic.** Same seed, same tree, every frame and every
  run. It has to be, or it shimmers at 25 Hz.
- **Rendering is cheap on purpose.** The voxel DOM is built once in painter's
  order and revealed by birth index, so a frame is a handful of `display`
  toggles, not a redraw. Don't replace that with a rebuild.
- **`skip` is bound first**, to a button and to <kbd>K</kbd>. When a pose refuses
  to trigger in front of judges that key is the demo.
- Losing the connection dims the UI and shows a reconnect pill. It never blanks.
  `EventSource` retries on its own — that is most of §10 for free.
