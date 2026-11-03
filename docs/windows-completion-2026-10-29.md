# Windows completion — 2026-10-29

Only the Windows project was changed. Existing uncommitted work was retained;
the real user profile was not used for tests. No Android/Linux changes or
atmosphere engine were added.

- Main agent: bridge volume/readiness contracts and renderer reload restoration,
  bounded watchdog reloads, source-aware search and repeated-query correlation,
  playlist rename/membership APIs, full playlist grid, virtual row state,
  same-origin artwork, feedback/events and integration.
- Settings/onboarding agent: compatible settings aliases and migrations, immediate
  consumers/rollback, radius/source controls, short durable onboarding based on
  Riff's actual first-run source, native-looking controls and CSS contracts.
- Player agent: 340×64 status-bar mini player, three transport controls, shared
  timeline, morphing play/pause, finite duration, slow seek, live normalization,
  fullscreen with the existing lyrics DOM, macOS palette and transport.
- Recommendations/downloads agent: Riff-derived shared taste/history/feedback
  pipeline, local fallback, source opt-outs throughout resolution and recovery,
  cache-before-conversion, cancellation, lyrics matching and library CRUD checks.

The user's final progress-mode clarification is implemented: panel mode seeks
by dragging the filled bar itself; its separate bottom line is hidden. Buttons,
volume, links and artist navigation keep their original actions. Thin mode
retains its own slider and keyboard seeking remains available.

Riff source, commit, dependency inspection and adapted mechanisms are recorded in
[recommendations/downloads](riff-recommendations-downloads.md) and
[onboarding](riff-onboarding.md). Its MIT notice is retained in
`licenses/riff-MIT.txt`; Electron dependencies were not added to this app.

Validation: the complete offline pytest run passed **2493 tests** (9 skipped,
1 network test deselected). Final CSS/JS/player checks after the last button
transition change also passed. Chromium exercised both skins, light/dark,
responsive layouts, onboarding, settings restore, playlist CRUD and player
controls. One real anonymous YouTube download passed audio validation:
252182 bytes in 17.1 seconds, with a disposable profile.

Native WebView2 checks used two local WAV fixtures in a disposable profile.
Play/pause, previous/next, seek, mini dimensions, fullscreen, restart/reload
state and actual full-panel pointer dragging were checked. The drag changed
1:33 to 1:23 while preserving pause, with the extra line hidden.

A continuous native run exceeded ten minutes, including minimize/restore,
maximize, background playback and a renderer reload. Background audio advanced
83648 ms over 83754 ms of wall time; the queue continued between the two files.
After reload, the selected macOS light presentation and active track were
restored, with only one autostart/watchdog pair. Foreground visual checks after
restore and at the end showed the complete interface without a white screen.

Limits: live SoundCloud/Spotify/authenticated sources, physical speaker output
and real-provider word-synced lyrics were not comprehensively verified.
The intermittent WHITE-001 compositor failure has not been reproduced; a
successful smoke run is not proof that its underlying cause is eliminated.
Direct destruction of the fixture window logged a late pywebview JS callback
after the native UI thread exited; the test process did exit. This teardown
diagnostic was not reproduced through the normal application close action.
