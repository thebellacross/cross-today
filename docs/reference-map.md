# Reference map

Reference: `samscorsby/samscorsby.github.io` at
`4913a48eee128d201a01fdd2d3edc1074e0ec50a`.

| Reference responsibility | Independent project implementation |
| --- | --- |
| `exp/chance/index.html` | `web/index.html`, `web/style.css`, `web/app.js`: measured desktop/mobile composition and audio-state-driven record. |
| `engine/chance_fontana.py` | `music/engine.py`: recording palette, chance structures, fusion, sparse and loop plans, stereo rendering. |
| `engine/chance_data.py` | `music/data.py`: deterministic arithmetic/file-byte data as sound and control; no implicit host files. |
| `engine/publish_album.py` | `music/album.py`, `music/artwork.py`, `music/cloud.py`: metadata, real source labels, data-derived record, exports and atomic publication. |
| `engine/day_radio.py` and network fallback | Replaced with `music/library.py` and private cloud snapshots. No network radio collection or material-free fallback. |
| `.github/workflows/daily_chance.yml` | `.github/workflows/daily.yml`: rendering, publication, recovery and cleanup through durable task state. |
| `chance-trigger/` | `worker/src/index.js`, `worker/src/logic.js`: scheduling, authenticated writes, media proxy and permanent curation. |
| score / sharing / archive | `web/score.*`, sharing dialog and actual iframe, `web/catalog.*`; expired daily cards retained. |

Observed daily distributions are centralized in `config.json`: 5–13 tracks with
weights 26/28/24/9/5/3/2/2/2; lognormal durations with median 210 seconds and
sigma 0.7, rejected outside 60–780 seconds; chance structure weights
fusion 3, loops 1, baseline .8, fontana .6, automaton .2, drift .2; pure days 1/7.
The engine contains the seven fusion techniques and audio-derived periodic loop
ideas. It uses source content features, not station/frequency/freshness scoring.

Every generation needs valid selected recordings. File-byte feeds are separate
algorithm inputs. Deliberate noise and sustained material are not discarded by
radio static heuristics. Source PCM16 conversion is explicit and the originals
retain their native format and channel count.

The structured score is the authoritative input for “now hearing” and score
visualization. A safe `radio [name]` text marker is retained in the downloadable
compatibility log; the publisher does not infer private paths or fictitious radio
station metadata from it.

Additional infrastructure supplies private originals/cache, permanent Selected
copies, private curated exports, and SQLite Durable Object records for leases,
revision checks, deduplication and atomic current-album updates. At the user's
request, the deployed backend uses project GitHub Release assets without a card
or paid subscription. Original recordings and exports with private notes live in
a private repository; public Selected files use independent `kept-*` releases.
R2 remains an optional adapter and is not provisioned. The reference itself does
not provide this personal material and curation layer.

The site's artist identity and discography are read from the verified Bandcamp
record in `web/artist.json`. The user subsequently set the displayed name to
**CROSS** and the repository name to **cross-today**. Generated
track names are derived from selected filenames and processes; no prior releases
or artist biography are invented.
