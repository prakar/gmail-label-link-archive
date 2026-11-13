# gmail-label-link-archive

Build a searchable link archive from newsletters in your Gmail labels.

*Not affiliated with Google. Gmail only; no other IMAP servers.*

A label-to-link-archive for newsletters. You point it at one or more Gmail labels, tell it (in a small TOML file) how each newsletter lays out its links, and it:

- reads the label read-only over IMAP (it never marks, moves or deletes mail),
- stores every email's HTML in a local SQLite file, so re-extraction never needs Gmail again,
- extracts the links, with title, blurb and optional author, publication and date, and labels each by kind (article, podcast, video, other, issue, footer, ...),
- optionally resolves the newsletter's own tracking links to the real article URL, one polite request per link,
- writes one static, searchable HTML page and two RSS feeds per label.

Standard library only: **Python 3.11+**, nothing to `pip install`.

## Early version

This is an early version. The profile engine reproduces the output of the original hard-coded parser exactly on 1,600+ real newsletter emails from one newsletter.

## This needs your own extractor work

Newsletters have no common layout, so **there is no profile that works for everyone**. `config/profiles/example-newsletter.toml` describes a made-up newsletter. For a real one you will write rules (regular expressions) against your own emails: save one as `.eml`, run `ingest`, look at `stats`, edit, run `reextract`, repeat. `cookbook.md` lists anonymised patterns that come up often. Expect an hour or two per newsletter layout, and expect older issues to need extra rules.

## Set up

1. In Gmail, make a filter that applies a label to the newsletter and skips the inbox. Nested labels are written `Parent/Child`.
2. Turn on 2-Step Verification for the Google account and create an App Password (16 characters).
3. Copy the examples and edit them:
   ```
   cp config/accounts.example.json    config/accounts.json
   cp config/credentials.example.json config/credentials.json && chmod 600 config/credentials.json
   cp config/profiles/example-newsletter.toml config/profiles/my-newsletter.toml
   ```
   - `accounts.json`: accounts and labels (JSON). Each label has a `source` id and the `profile` it uses.
   - `credentials.json`: app passwords by account name (JSON). Git-ignored. Only commands that talk to Gmail read it.
   - `profiles/*.toml`: extraction profiles. Only the example is tracked by git; your own are ignored.

## Use

```
python3 -m linkarchive ingest --source example-digest tests/fixtures/sample_issue.eml   # try it with no Gmail at all
python3 -m linkarchive backfill --limit 20      # a small trial from Gmail
python3 -m linkarchive stats                    # links per email per year: a drop means a layout is being missed
python3 -m linkarchive reextract                # after editing a profile
python3 -m linkarchive resolve --limit 20       # only for profiles with [resolve] hosts
python3 -m linkarchive resolve --all-kinds      # also follow footer, puzzle and issue links (default: the profile's [kinds] resolve list)
python3 -m linkarchive build                    # writes OUT_DIR/archive/index.html and the RSS feeds
python3 -m linkarchive update                   # backfill the newest 30, resolve, build: the cron command
```

`--config DIR` picks another config folder; `--source ID` limits a command to one label. Run the tests (fixture only, no network):

```
python3 -m unittest discover -s tests -t .
```

## Privacy

- The archive page, the SQLite file and the feeds contain your newsletters' content, which may be paid or private. Keep them on your own machine or LAN; do not publish them. Output files are written owner-only (mode 600).
- `.gitignore` excludes credentials, your accounts file, your profiles, databases, `.eml`, HTML and feeds. Check `git status` before every commit.
- Resolving makes one request per distinct tracking link to the newsletter's own redirect host (never to the article page), about one per second, with an honest User-Agent. Check the publisher's terms first, or leave `[resolve] hosts` empty to switch it off.

## Scope and contributions

Gmail only (IMAP with an App Password), extraction profiles in TOML, accounts and labels in JSON. This repository is for cloning and forking only: see `CONTRIBUTING.md`. No pull requests.

## Licence

MIT, see `LICENSE`.
