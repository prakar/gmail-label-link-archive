# Cookbook: patterns that come up in newsletters

All examples are invented ("Example Digest" does not exist). Each pattern shows what you see in the email and the profile rule that handles it. Regexes are case-insensitive. Test every change with `reextract` and `stats`.

## 1. The email links to itself ("read online")
Seen: a heading link whose text equals the email subject.
```toml
[[rules]]
kind = "issue"
title_equals_subject = true
```
Put this rule first. It stops the issue's own link from being listed as an article.

## 2. A metadata line under each article
Seen: `Author | Publication | 13th August 2026 | U` on the line after the link, sometimes followed by a comment.
```toml
[meta]
regex = '^(?P<author>[^|]+?)\s*\|\s*(?P<publication>[^|]+?)\s*\|\s*(?P<date>[^|]+?)\s*\|\s*(?P<flag>[A-Z]{1,2})(?=\s|$)(?:\s+(?P<comment>.*))?$'
[[rules]]
kind = "article"
use_meta = true
```
Keep one field required (here the flag) so a lazy date group cannot swallow the rest of the line. If some entries omit the publication, write a second regex layout as a second profile or loosen the middle group to `(?:...\|)?`.

## 3. Media items announced by a leading word
Seen: blurb starts with "Podcast:" or "Video." and the link text is `Title | Show` or `Title | Site | Channel | 12m 04s`.
```toml
[[rules]]
kind = "podcast"
blurb_regex = '^podcast'
[[split_title]]
kind = "podcast"
field = "show"
```

## 4. Footer and housekeeping links
Seen: "letters to the editor", "frequently asked questions", "how to contact us".
```toml
[filter]
always_consider_regex = 'frequently asked|letters to the editor'
[[rules]]
kind = "footer"
any_regex = 'frequently asked|letters to the editor|for any queries'
```
Footer links are kept in the archive but left out of the RSS feed (`[kinds] keep`).

## 5. Links inside running prose
Seen: an essay-style issue with links in the middle of sentences. They match no rule, so they become kind `other`, with the whole sentence kept as the blurb. Keep `other` in `[kinds] keep` if you want them, drop it if the feed gets noisy.

## 6. Tracking wrappers
Seen: `https://click.example.net/track?url=https%3A%2F%2Fexample.org%2Fa&id=9`. List the parameter names that carry the real URL in `unwrap_keys`. Parameters starting with anything in `drop_param_prefixes` (`utm_`, `fbclid`, ...) are removed.

## 7. The newsletter's own redirect domain
Seen: every article link is `https://news.example.com/r/<id>`. Set `[resolve] hosts` and `path_prefix`, then run `resolve --limit 20` as a trial. Statuses: `ok`, `gone` (404/410), `nolocation_NNN`, `loop`, `error_*`. `--retry-errors` retries all but `ok` and `gone`.

## 8. A special edition with a different layout
Seen: a weekly edition (books, music, quizzes) whose links look different. Add a rule with `subject_regex = '^the weekend edition'` and a kind such as `supplement`, placed before the generic rules, and add the kind to `[kinds]` lists if you want it resolved or fed.

## 9. Old issues missed after a layout change
Run `stats`. A sudden drop in links per email for one year means an older layout. Save one email from that year as `.eml`, `ingest` it under a scratch `--config` folder, and add rules for it. Re-run `reextract` on the real archive.

## 10. Social and share links
Seen: share buttons, `bit.ly`, WhatsApp links. `skip_hosts` and `skip_text` in `[filter]` drop them before classification.

## 11. Case-sensitive rules
Seen: a byline `by Ann Lee • weekly note` that should count, while the shouted `BY ANN LEE • WEEKLY NOTE` elsewhere should not. Regexes ignore case by default, so say so per rule:
```toml
[[rules]]
kind = "issue"
blurb_regex = '^by .+ \u2022 '
case_sensitive = true
```
`[meta]` accepts `case_sensitive = true` too. To switch case off for just part of one regex, `(?-i:...)` still works: `blurb_regex = '(?-i:^by .+ \u2022 )'`. Case matters most for flag letters like `[A-Z]{1,2}`, which would otherwise also match lowercase words.

## 12. `any_regex` is shallow: `title_regex` and `blurb_regex` see everything
Seen: a footer phrase that appears late in a long blurb. `any_regex` only tests the title and the first 120 characters of the blurb, so it misses it. To test the whole blurb, use `blurb_regex`:
```toml
[[rules]]
kind = "footer"
title_regex = 'letters to the editor|for any queries'
[[rules]]
kind = "footer"
blurb_regex = 'letters to the editor|for any queries'
```
Use `any_regex` only when the phrase is short and sits near the start.

## 13. "A or B": one rule per branch
Seen: a link is a puzzle if the blurb starts with "Puzzle" OR the title mentions a daily word game. All conditions inside one rule must hold together, so branches become separate rules with the same kind:
```toml
[[rules]]
kind = "puzzle"
blurb_regex = '^puzzle'
[[rules]]
kind = "puzzle"
title_regex = 'daily word game'
```
Rules run top to bottom and the first match wins, so order them from most specific to most general.

## 14. Short footer links: `always_consider_regex`
Seen: "Contact us" or "FAQ" links whose text is shorter than `min_title_chars`, so they are dropped before any rule sees them. List their wording here and they are kept and classified (give them a footer rule so they do not show up as articles):
```toml
[filter]
always_consider_regex = 'contact us|faq|letters to the editor'
[[rules]]
kind = "footer"
title_regex = 'contact us|faq|letters to the editor'
```

## Resolving more than the default kinds
`resolve` follows tracking links only for the kinds in `[kinds] resolve`. To resolve every kind, including footer, puzzle and issue links, run `python3 -m linkarchive resolve --all-kinds` (add `--limit 20` for a trial). Useful when you want every redirect target on record; it makes more requests, so keep the delay polite.
