# Swipe

Turn any list into a Tinder-style deck. Paste a list, decide what a left and
a right swipe mean, swipe through it, export the result, and run another
round on what's left. Self-hosted, built for a Raspberry Pi like
[WatchPi](https://github.com/Salterm27/watchpi).

**Architecture:** the same as WatchPi: Flask + SQLite, a single-file
frontend, no other dependencies, and the server never makes an outbound
request. The difference: **every project is its own SQLite file**
(`data/project-<id>.db`), holding its settings, items, rounds and decisions.
There is no central database; the project list is the `data/` directory. A
project can be copied, backed up, opened with `sqlite3`, or deleted
without touching any other.

```
Phone browser ──► Pi :8002  (Flask)
                    └── data/project-3f9a….db   ← one mini database per project
                    └── data/project-81c2….db
```

## How it works

1. **Create a project.** Name it and set what each swipe means. Each of
   the three choices (right, left, up for "don't know") gets a label, an icon
   and a colour. The defaults are ✓ green *Yes*, ✕ red *No*, and ? grey *Not sure*.
2. **Add your list.** Paste it or load a file. Swipe detects the format (see below).
3. **Lay out the card.** Swipe makes an educated guess about the card face:
   **title**, **subtitle**, a **highlight** next to the title (price, year,
   rating…), the **main photo**, plus **more photos** if the list has several
   photo fields or a field with several URLs. It also picks the description
   and link. You see a real sample card and can change any slot; tap it to
   preview its details.
4. **Swipe.** The card face shows only the essentials, Tinder-style. Drag it,
   tap the buttons, or use the keyboard (← → ↑, ⌫ undo). **Tap** the card (or
   ⓘ, or press Enter) to open its details: the photos large on top, then the
   description, every other field and the link. You can decide right from
   there. With several photos, tap the left or right edge of the photo to
   step through them. Close with ⌄, Esc, the back gesture or a pull-down.
5. **Results.** Each pile shows a count. You can filter by pile and change any
   decision with one tap. Export to CSV or JSON, or export only one pile.
6. **Next round.** Choose which piles go back into the deck (default:
   *Yes* + *Not sure*). You can also paste more data at the same time. Earlier
   decisions are never overwritten: each card shows its history
   (`R1 ✓ Yes`), and the export has one column per round plus the latest
   verdict.

### Lists it understands

Detection tries these formats in this order. The step 3 "Read as" picker overrides it.

| Format | Example |
|---|---|
| JSON | `[{"name": …}, …]`, `{"results": [ … ]}`, `{"id1": {…}}`, `["a", "b"]`. Nested objects flatten to `a.b` |
| JSON lines | one object per line |
| Markdown table | `\| Name \| Rating \|` + `\|---\|---\|` (surrounding prose is ignored) |
| Tab-separated | cells copied from Google Sheets / Excel |
| CSV | `,` `;` or `\|` delimited, header row detected (otherwise `column_1…`) |
| key: value blocks | `Name: Ana` / `Role: Dev` blocks separated by blank lines, or YAML-ish `- name: …` |
| One per line | the fallback. Bullets, numbering and `[ ]` checkboxes are stripped |

All of this lives in `parsers.py`. To add a format, write a function
`parse_x(text) -> list[dict] | None` and register it in `FORMATS`.

### Adding data later ("match items by")

Each item has a **key** so that a later paste can add fields to items you
have already swiped instead of creating duplicates. By default the key is an
id-like field (`id`, `sku`, `isbn`…), or a unique link or title. If none of
those exist, the whole record is the key. You can change it on the
layout step. When a pasted row matches an existing item, its new fields are
merged in (blank values never erase old ones). Rows that don't match become
new cards. You can import from the results page into the current round, or
into the next round as part of "Start next round". New fields show up in
⚙ Settings → card layout.

## Design

Calm and editorial: warm ivory paper, white cards with fine borders and
barely-there shadows, deep forest-green ink. Decisions use forest (yes),
dusty terracotta (no) and soft ochre (not sure). Headlines are set in
**Newsreader**, an editorial serif with real italics; everything else is
**DM Sans**. Both are self-hosted in `static/fonts/` under the SIL Open
Font License (`OFL-*.txt` next to them), so the browser never fetches
anything from outside the Pi. Photos sit contained on white with room
around them.

All text meets WCAG AA contrast, keyboard focus shows a forest ring, touch
targets are at least 44px, and `prefers-reduced-motion` turns animations
off. The design tokens (colours, type, radii, shadows) live at the top of
the `<style>` block in `static/index.html`. Projects that still use the
original dark-theme default colours pick up the new palette automatically.

## Files

```
swipe/
├── app.py                 # Flask backend: one SQLite file per project
├── parsers.py             # list-format detection + card-layout guessing
├── requirements.txt       # just flask
├── static/index.html      # entire frontend, single file
├── static/fonts/          # Newsreader + DM Sans (OFL), self-hosted
├── tests/                 # pytest (API, parsers, validation), jsdom unit tests, Playwright
├── pyproject.toml         # ruff + coverage config
├── eslint.config.js       # frontend lint (no innerHTML: list data is user content)
└── deploy/
    ├── swipe.service          # systemd unit (port 8002)
    ├── autodeploy.sh          # pull-based deploy with health-gated rollback
    ├── swipe-deploy.service
    └── swipe-deploy.timer     # every 10 minutes
```

## Install on the Pi

```bash
cd /srv/apps                       # same place as watchpi
git clone https://github.com/Salterm27/swipe.git
cd swipe

python3 -m venv venv
venv/bin/pip install -r requirements.txt

# edit deploy/swipe.service if your username isn't sebas (User= line)
sudo cp deploy/swipe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swipe
curl http://localhost:8002/api/health   # → {"ok": true}
```

Open `http://<pi-hostname>:8002` and "Add to Home Screen" for an app-like launcher.

### Auto-deploy

This works like WatchPi's: a timer checks `main` every 10 minutes, deploys
new commits and rolls back if `/api/health` doesn't come up.

```bash
sudo cp deploy/swipe-deploy.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swipe-deploy.timer
```

### Backups

WatchPi's nightly restic job backs up all of `/srv/apps` and takes a
consistent `sqlite3 .backup` snapshot of every `/srv/apps/*/data/*.db`.
Project files sit flat in `data/` so that glob picks them up. Snapshots
(`project-….bak.db`) never show up as projects.

> ⚠️ As of writing, that script's `--exclude="/srv/apps/*/data/*.db"` also
> matches the `*.bak.db` snapshots, so **no database (WatchPi's included)
> actually reaches the backup**. Fix it in the watchpi repo before relying on
> it for Swipe.

Deleting a project **renames** its file to `data/deleted-<id>-<timestamp>.db`
instead of erasing it. To restore one, rename it back to `project-<id>.db`.

## API

Everything the UI does goes through the API, so scripts can use it too.

| | |
|---|---|
| `POST /api/parse` `{text, filename?, format?}` | dry run: detected format, fields, guessed layout, sample |
| `GET /api/projects` · `POST /api/projects` `{name, text, choices?, mapping?, key_field?, format?}` | list / create |
| `GET · PATCH · DELETE /api/projects/<id>` | details / rename, choices, mapping / soft delete |
| `GET /api/projects/<id>/queue?limit=` | next undecided cards of the current round |
| `POST /api/projects/<id>/decisions` `{item_id, choice}` | `choice`: `left` `right` `unsure` (re-posting changes it) |
| `POST /api/projects/<id>/undo` | take back the latest decision |
| `GET /api/projects/<id>/items?round=&choice=` | a round's items with decisions + history |
| `POST /api/projects/<id>/import` `{text}` | add/merge data into the current round |
| `POST /api/projects/<id>/rounds` `{carry?, text?, note?}` | start the next round. `carry` defaults to `["right","unsure"]` (`"none"` = undecided) |
| `GET /api/projects/<id>/export?format=csv\|json&round=&choice=` | download |

## Tests

```bash
pip install -r requirements-dev.txt && npm ci

# static analysis
ruff check .                               # Python: pyflakes, bugbear, bandit security rules
npx eslint .                               # the <script> in index.html + JS tooling

# unit tests
python -m pytest tests/ --cov              # API, parsers, validation (CI gate: 95% coverage)
node --test tests/frontend.test.js         # frontend on jsdom: rendering, XSS-safety, editors

# end to end
npx playwright install chromium
npx playwright test                        # real browser: wizard, drag, keys, rounds
```

CI runs all of it on every push and PR. **CodeQL** scans Python and JS
(security-extended queries) on PRs and weekly. **Dependabot** opens weekly
PRs for pip, npm and GitHub Actions versions. Dependencies are pinned
exactly, so the Pi runs what CI tested and every bump goes through CI first.

The frontend lint bans `innerHTML` and friends. All DOM is built with `h()`,
which only sets text, because list data is user content.

## Not yet (ideas for next iterations)

- Profiles / several people swiping the same project and comparing piles
- Shuffle order, or sort by a field
- Images from local files (today: image URLs only)
- Smarter "one per line" splitting (`Title - note`, URLs with titles)
- Sharing a project as a link (the spin-off "as a service" path)
