"""SQLite store, Gmail backfill (read-only IMAP), one-hop link resolution. Standard library only."""
import email, http.client, imaplib, json, os, random, re, sqlite3, ssl, sys, time, zlib
from datetime import datetime, timezone
from email import policy
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse

from .extract import issue_from_message, find_links

UA = 'gmail-label-link-archive/0.1 (personal use; one request per link, redirect only)'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY, msgid TEXT UNIQUE, source TEXT, uid INTEGER, subject TEXT, date TEXT, issue_url TEXT, html BLOB);
CREATE TABLE IF NOT EXISTS links(id INTEGER PRIMARY KEY, issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE, pos INTEGER, kind TEXT,
  title TEXT, url TEXT, rkey TEXT, author TEXT, publication TEXT, published TEXT, flag TEXT, blurb TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS links_issue ON links(issue_id);
CREATE INDEX IF NOT EXISTS links_rkey ON links(rkey);
CREATE TABLE IF NOT EXISTS resolutions(rkey TEXT PRIMARY KEY, target TEXT, status TEXT, at TEXT);
'''
EXTRA_KEYS = ('show', 'channel', 'access', 'comment', 'published_raw')


def open_db(data_dir, name='archive.db'):
    os.makedirs(data_dir, exist_ok=True)
    db = sqlite3.connect(os.path.join(data_dir, name))
    db.execute('PRAGMA foreign_keys=ON'); db.executescript(SCHEMA)
    return db


def rkey_of(url, profile):
    """Key for a tracking link on one of the profile's resolve hosts and path prefix; '' for every other link."""
    u = urlparse(url)
    h = (u.hostname or '').lower()
    if profile.resolve_hosts and u.path.startswith(profile.resolve_prefix) and (h in profile.resolve_hosts or h.endswith(tuple('.' + x for x in profile.resolve_hosts))):
        return (u.netloc + u.path).lower()
    return ''


def clean_target(url, profile):
    u = urlparse(url)
    keep = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
            if not k.lower().startswith(profile.drop_prefixes) and not (k.lower() == 'ref' and v.lower() in profile.drop_ref_values)]
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(keep), ''))


def store_links(db, issue_id, found, profile):
    for pos, x in enumerate(found):
        extra = {k: x[k] for k in EXTRA_KEYS if x.get(k)}
        db.execute('INSERT INTO links(issue_id,pos,kind,title,url,rkey,author,publication,published,flag,blurb,extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (issue_id, pos, x['kind'], x['title'], x['url'], rkey_of(x['url'], profile), x.get('author', ''), x.get('publication', ''),
                    x.get('published', ''), x.get('access', ''), x.get('blurb', ''), json.dumps(extra, ensure_ascii=False) if extra else ''))


def ingest(db, msg, source, profile, uid=None):
    issue = issue_from_message(msg, profile)
    if db.execute('SELECT 1 FROM issues WHERE msgid=?', (issue['id'],)).fetchone(): return False
    cur = db.execute('INSERT INTO issues(msgid,source,uid,subject,date,issue_url,html) VALUES(?,?,?,?,?,?,?)',
                     (issue['id'], source, uid, issue['subject'], issue['date'].isoformat(), issue['issue_url'], zlib.compress(issue['html'].encode('utf-8'), 9)))
    store_links(db, cur.lastrowid, issue['all_links'], profile)
    db.commit()
    return True


def reextract(db, source, profile):
    """Redo link extraction from the stored HTML (after editing a profile). Resolutions are kept."""
    n = 0
    for iid, subject, blob in db.execute('SELECT id, subject, html FROM issues WHERE source=?', (source,)).fetchall():
        found = find_links(zlib.decompress(blob).decode('utf-8'), subject, profile)
        db.execute('DELETE FROM links WHERE issue_id=?', (iid,))
        store_links(db, iid, found, profile)
        db.execute('UPDATE issues SET issue_url=? WHERE id=?', (next((x['url'] for x in found if x['kind'] == 'issue'), ''), iid))
        n += 1
    db.commit()
    return n


# ---------------------------------------------------------------- Gmail (IMAP, read-only)

def connect(user, pw, label):
    M = imaplib.IMAP4_SSL('imap.gmail.com', 993)
    M.login(user, pw)
    typ, _ = M.select('"%s"' % label.replace('"', ''), readonly=True)          # readonly: never marks anything as read
    if typ != 'OK': sys.exit(f'Cannot open label "{label}". Labels are case sensitive; nested labels use "Parent/Child".')
    return M


def backfill(db, user, pw, label, source, profile, limit=None, batch=40):
    M = connect(user, pw, label)
    typ, data = M.uid('SEARCH', None, 'ALL')
    uids = [int(x) for x in data[0].split()]
    have = {r[0] for r in db.execute('SELECT uid FROM issues WHERE uid IS NOT NULL AND source=?', (source,))}
    todo = [u for u in reversed(uids) if u not in have]                          # newest first
    if limit: todo = todo[:limit]
    print(f'[{source}] {len(uids)} emails in the label, {len(have)} already stored, fetching {len(todo)}')
    added = failed = 0
    for n, uid in enumerate(todo, 1):
        for attempt in range(3):
            try:
                typ, parts = M.uid('FETCH', str(uid), '(BODY.PEEK[])')
                if typ == 'OK' and parts and isinstance(parts[0], tuple):
                    added += ingest(db, email.message_from_bytes(parts[0][1], policy=policy.default), source, profile, uid)
                break
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, ssl.SSLError, OSError) as e:
                print(f'  uid {uid}: {e}; reconnecting'); time.sleep(3 * (attempt + 1))
                try: M = connect(user, pw, label)
                except Exception: pass
        else:
            failed += 1
        if n % 25 == 0 or n == len(todo): print(f'  {n}/{len(todo)} fetched, {added} new')
        if n % batch == 0:
            try: M.logout()
            except Exception: pass
            time.sleep(1); M = connect(user, pw, label)
    try: M.logout()
    except Exception: pass
    if failed: print(f'{failed} emails failed; run backfill again to retry them')
    return added


# ---------------------------------------------------------------- resolving tracking links, one hop at a time

class Backoff(Exception): pass


def one_hop(url):
    u = urlparse(url)
    conn = (http.client.HTTPSConnection if u.scheme == 'https' else http.client.HTTPConnection)(u.netloc, timeout=20)
    try:
        conn.request('GET', (u.path or '/') + ('?' + u.query if u.query else ''), headers={'User-Agent': UA, 'Accept': '*/*'})
        r = conn.getresponse()
        loc = r.getheader('Location')
        head = r.read(8192).decode('utf-8', 'replace') if not loc else ''
        return r.status, loc, head
    finally:
        conn.close()


def resolve_url(url, profile):
    """Returns (status, target). Follows only hops that stay on a resolve host; the target page itself is never fetched."""
    for _ in range(4):
        code, loc, head = one_hop(url)
        if code in (429, 500, 502, 503, 504): raise Backoff(f'HTTP {code}')
        if not loc:
            m = re.search(r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\'>\s]+)', head, re.I)
            if not m: return ('gone' if code in (404, 410) else f'nolocation_{code}'), ''
            loc = m.group(1)
        loc = urljoin(url, loc)
        if not loc.startswith(('http://', 'https://')): return 'badscheme', ''
        if rkey_of(loc, profile): url = loc; continue
        return 'ok', clean_target(loc, profile)
    return 'loop', ''


def pending_links(db, source, profile, all_kinds=False, retry_errors=False):
    """(rkey, url) pairs still to resolve: one per distinct tracking link. Normally only the kinds in the profile's
    [kinds] resolve list; all_kinds=True also takes footer, puzzle, issue and every other kind."""
    kind_filter = ''
    if not all_kinds:
        kinds = ','.join("'%s'" % k.replace("'", '') for k in profile.resolve_kinds) or "''"
        kind_filter = f'AND l.kind IN ({kinds})'
    return db.execute(f'''SELECT rkey, url FROM (SELECT l.rkey, l.url, MIN(l.id) FROM links l JOIN issues i ON i.id=l.issue_id
                           WHERE l.rkey!='' AND i.source=? {kind_filter} GROUP BY l.rkey)
                          WHERE rkey NOT IN (SELECT rkey FROM resolutions {"WHERE status IN ('ok','gone')" if retry_errors else ""})''', (source,)).fetchall()


def resolve(db, source, profile, limit=None, delay=1.0, retry_errors=False, all_kinds=False):
    if not profile.resolve_hosts:
        print(f'[{source}] profile has no [resolve] hosts: nothing to resolve'); return
    rows = pending_links(db, source, profile, all_kinds, retry_errors)
    if limit: rows = rows[:limit]
    print(f'[{source}] {len(rows)} distinct tracking links to resolve at about {1 / max(delay, 0.01):.1f}/second')
    ok = bad = fails = 0
    for n, (rkey, url) in enumerate(rows, 1):
        try:
            status, target = resolve_url(url, profile); fails = 0
        except Backoff as e:
            fails += 1; print(f'  {e}; backing off'); time.sleep(min(300, 20 * 2 ** fails))
            if fails >= 5: print('Too many refusals; stopping. Run again later, nothing is lost.'); break
            continue
        except Exception as e:
            status, target = f'error_{type(e).__name__}', ''
        db.execute('INSERT OR REPLACE INTO resolutions VALUES(?,?,?,?)', (rkey, target, status, datetime.now(timezone.utc).isoformat()))
        ok += status == 'ok'; bad += status != 'ok'
        if n % 25 == 0: db.commit(); print(f'  {n}/{len(rows)}  ok {ok}  not-ok {bad}')
        time.sleep(delay * random.uniform(0.8, 1.3))
    db.commit()
    print(f'resolved {ok}, not resolved {bad}')


# ---------------------------------------------------------------- reading back

def issues_from_db(db, source, profile, n=15):
    issues = []
    for iid, msgid, subject, date, issue_url, blob in db.execute(
            'SELECT id, msgid, subject, date, issue_url, html FROM issues WHERE source=? ORDER BY date DESC LIMIT ?', (source, n)).fetchall():
        links = []
        for kind, title, url, target, author, pub, published, flag, blurb, extra in db.execute(
                '''SELECT l.kind, l.title, l.url, r.target, l.author, l.publication, l.published, l.flag, l.blurb, l.extra FROM links l
                   LEFT JOIN resolutions r ON r.rkey=l.rkey AND r.status='ok' AND l.rkey!='' WHERE l.issue_id=? ORDER BY l.pos''', (iid,)):
            links.append({'kind': kind, 'title': title, 'url': target or url, 'author': author, 'publication': pub, 'published': published,
                          'access': flag, 'blurb': blurb, **(json.loads(extra) if extra else {})})
        issues.append({'id': msgid, 'subject': subject, 'date': datetime.fromisoformat(date), 'html': zlib.decompress(blob).decode('utf-8'),
                       'issue_url': issue_url, 'all_links': links, 'articles': [x for x in links if x['kind'] in profile.keep]})
    return issues


def stats(db, source):
    tot = db.execute('SELECT COUNT(*), MIN(substr(date,1,10)), MAX(substr(date,1,10)) FROM issues WHERE source=?', (source,)).fetchone()
    print(f'[{source}] {tot[0]} emails, {tot[1]} to {tot[2]}')
    print('per year: emails, links per email (a sudden drop means an older layout is being missed)')
    for y, n, l in db.execute('''SELECT substr(i.date,1,4), COUNT(DISTINCT i.id), COUNT(l.id) FROM issues i LEFT JOIN links l ON l.issue_id=i.id
                                 WHERE i.source=? GROUP BY 1 ORDER BY 1''', (source,)):
        print(f'  {y}  {n:4d} emails  {l / n:5.1f} links')
    print('kinds:', dict(db.execute('SELECT l.kind, COUNT(*) FROM links l JOIN issues i ON i.id=l.issue_id WHERE i.source=? GROUP BY l.kind ORDER BY 2 DESC', (source,)).fetchall()))
    print('resolution:', dict(db.execute('SELECT status, COUNT(*) FROM resolutions GROUP BY status').fetchall()))
