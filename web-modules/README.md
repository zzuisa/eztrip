# web-modules

UI modules used by the current RogueTrip frontend. They are plain ES modules without a framework build step and are wired into the compiled Vue app by `build.cjs` (it uses acorn to find the component boundaries and refuses to build if the base bundle doesn't match).

- `stay-planner.js` – accommodation by segment: area first, then a concrete hotel, with a draggable timeline for the nights
- `budget-ui.js` – travellers / rooms / cars and the cost breakdown, per person and per group
- `trip-guidance.js` – pre-generation choices (trip style, interests, long-distance mode)
- `route-sync.js` – keeps map, route snapshot and narration in sync after edits
- `playback-camera.js` – camera framing for the leg-by-leg map playback
- `xhs-ui.js` – cuisine picker and source labels for Xiaohongshu tips
- `place-notes.js`, `adapters.js`, `dom.js` – small helpers

```bash
npm ci
npm test
node build.cjs <base-html-dir> <output-dir> <release-version>
```
