# Intermittent gray player artwork backdrop

The displayed cover used a normal cross-origin image request. Rendering succeeded,
but sampling that image with canvas failed because it was not requested with CORS.
Separately, asynchronous background image callbacks had no track identity guard:
a late load/error from a previous track replaced or cleared the new track's art.
The resulting gray fallback was particularly visible in the macOS pack, which
forced the backdrop to 15% opacity and ignored the configured glow strength.

`player.js` now paints the CSS artwork immediately and samples a separate anonymous
image. Hosts without CORS still provide a visible blurred artwork background;
their sampling failure does not hide the displayed image. Sampling callbacks carry
a request generation, so stale results cannot change the current palette. New
tracks clear the preceding palette. The two presentation packs respect the shared
glow settings, including off, and the regular cards allow the artwork to show
through while retaining the configured application opacity.

Regression: `tests/player_artwork_browser.cjs` runs the real `onTrackChanged`
handler and shipped HTML/styles against two disposable loopback origins. It tests
CORS-enabled and CORS-disabled covers, cached repeats, delayed success/error from
old tracks, missing covers, glow off, and actual backdrop screenshot pixels in
current, macOS dark and macOS light. Before the fix it reported missing palettes,
erased current backgrounds and gray backdrop pixels. After the fix it passes.
No user profile or real media is used.

Validation: browser regression passed; 93 tests passed across artwork URLs,
player resources, visual effect lifecycle, layout geometry, macOS presentation,
frontend JavaScript and CSS wiring.

Run the browser regression with `node tests/player_artwork_browser.cjs`, with
`playwright-core` resolvable through `NODE_PATH`. Set `CHROME_PATH` to an installed
Chromium executable if no Playwright-managed browser is available.
