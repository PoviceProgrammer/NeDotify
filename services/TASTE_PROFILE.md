# Taste profile and listening metrics

`UserTasteProfile` uses listening history as an input to recommendations. Its
artist, genre, and track scores are weighted taste signals, not listening
counts. A completed listen, an ordinary play, a favorite, a download, and a
playlist membership have different weights; history signals also decay with
age. Repeated listens therefore add signal independently.

`recent_history` is a display and recommendation feed. When the database
provides `get_history(limit=50)`, the profile uses that canonical feed, which
returns one row per track with bounded-window event metrics and the latest
event's completion/listening flags. The profile retains its bounded raw event
rows separately while calculating weighted taste scores. Connection-only and
legacy database callers use a compatibility adapter that keeps the newest row
per track, preserves its event flags, and aggregates event count and listened
duration.

Do not interpret `top_artists[*].play_count` from a taste profile as the
database's lifetime play counter. Taste profile values are weighted scores and
can differ from the home screen's count metrics by design.
