"""Command line: python3 -m linkarchive <command>. Run with -h for the commands."""
import argparse, email, os, sys
from datetime import datetime
from email import policy

from . import archive, feeds, site
from .config import Config, DEFAULT_DIR

HELP = '''commands
  backfill [--limit N]   read each configured label (read-only IMAP, newest first), store what is not stored yet. Resumable.
  resolve  [--limit N] [--delay S] [--retry-errors] [--all-kinds]
                         follow each distinct tracking link ONE hop (only for profiles with [resolve] hosts) and record the target.
                         --all-kinds also follows footer, puzzle and issue links (normally only the profile's [kinds] resolve list).
  build                  write OUT_DIR/archive/index.html and two RSS feeds per source
  update                 backfill the newest 30 + resolve + build (the cron command)
  reextract              redo link extraction from stored HTML after editing a profile
  stats                  counts per year and kind
  ingest FILE.eml ...    store saved emails (needs --source); no Gmail needed
'''


def main(argv=None):
    ap = argparse.ArgumentParser(prog='linkarchive', description='Build a searchable link archive from newsletters in your Gmail labels.',
                                 epilog=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['backfill', 'resolve', 'build', 'update', 'reextract', 'stats', 'ingest'])
    ap.add_argument('files', nargs='*', help='ingest: .eml files')
    ap.add_argument('--config', default=DEFAULT_DIR, help='config folder (default ./config)')
    ap.add_argument('--source', help='limit to one label entry (its "source" id in accounts.json)')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--delay', type=float, default=1.0, help='seconds between resolve requests (default 1.0)')
    ap.add_argument('--retry-errors', action='store_true')
    ap.add_argument('--all-kinds', action='store_true', help='resolve: also follow footer, puzzle, issue and other normally skipped kinds')
    a = ap.parse_intermixed_args(argv)

    cfg = Config(a.config)
    db = archive.open_db(cfg.data_dir)
    pairs = [(acc, lab) for acc, lab in cfg.sources() if not a.source or lab['source'] == a.source]
    if not pairs: sys.exit('No matching label in accounts.json.')

    if a.cmd == 'ingest':
        if not a.source: sys.exit('ingest needs --source (which label entry, hence which profile, to use).')
        prof = cfg.profile(pairs[0][1]['profile'])
        n = 0
        for f in a.files:
            with open(f, 'rb') as fh: n += archive.ingest(db, email.message_from_binary_file(fh, policy=policy.default), a.source, prof)
        print(n, 'new emails stored'); return
    for acc, lab in pairs:
        src, prof = lab['source'], cfg.profile(lab['profile'])
        if a.cmd in ('backfill', 'update'):
            archive.backfill(db, acc['user'], cfg.password(acc['name']), lab['label'], src, prof, limit=a.limit or (30 if a.cmd == 'update' else None))
        if a.cmd in ('resolve', 'update'): archive.resolve(db, src, prof, a.limit if a.cmd == 'resolve' else None, a.delay, a.retry_errors, a.all_kinds)
        if a.cmd == 'reextract': print(f'[{src}]', archive.reextract(db, src, prof), 'emails re-extracted')
        if a.cmd == 'stats': archive.stats(db, src)
        if a.cmd in ('build', 'update'):
            n_iss, n_art = feeds.build_feeds(archive.issues_from_db(db, src, prof), cfg.out_dir, src, cfg.title, cfg.base_url)
            print(f'{datetime.now():%Y-%m-%d %H:%M} [{src}] feeds: {n_iss} emails, {n_art} links')
    if a.cmd in ('build', 'update'):
        print('archive page:', site.build_site(db, cfg.out_dir, cfg.title, {l['source']: cfg.profile(l['profile']) for _, l in cfg.sources()}))


if __name__ == '__main__':
    main()
