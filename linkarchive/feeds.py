"""RSS 2.0 output with the standard library."""
import hashlib, os, tempfile
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape


def rss(title, link, description, items):
    ns = 'xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom"'
    cdata = lambda s: '<![CDATA[' + s.replace(']]>', ']]]]><![CDATA[>') + ']]>'
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f'<rss version="2.0" {ns}><channel>',
           f'<title>{escape(title)}</title><link>{escape(link)}</link><description>{escape(description)}</description>',
           f'<lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>']
    for it in items:
        out.append('<item>')
        out.append(f'<title>{escape(it["title"])}</title><link>{escape(it["link"])}</link>')
        out.append(f'<guid isPermaLink="false">{escape(it["guid"])}</guid><pubDate>{format_datetime(it["date"])}</pubDate>')
        if it.get('summary'): out.append(f'<description>{escape(it["summary"])}</description>')
        if it.get('html'): out.append(f'<content:encoded>{cdata(it["html"])}</content:encoded>')
        out.append('</item>')
    out.append('</channel></rss>')
    return '\n'.join(out)


def write_atomic(path, text):
    d = os.path.dirname(path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(text)
    os.chmod(tmp, 0o600)      # archive content may be paid or private: owner-only by default
    os.replace(tmp, path)


def item_summary(a, issue_subject, source):
    bits = [a.get('author'), a.get('publication'), a.get('published') or a.get('published_raw')]
    head = ' | '.join(x for x in bits if x)
    if a['kind'] == 'article' and head: return f'{head}  ({source}, {issue_subject})'
    extra = a.get('show') or a.get('channel') or ''
    return f'{a["kind"].capitalize()}{": " + extra if extra else ""}. {a.get("blurb", "")}'.strip() + f'  ({source}, {issue_subject})'


def build_feeds(issues, out_dir, source, title, base_url=''):
    """Writes OUT_DIR/<source>.xml (one item per link kept) and OUT_DIR/<source>_issues.xml (one item per email)."""
    issues = sorted(issues, key=lambda i: i['date'], reverse=True)
    link = base_url or 'http://localhost/'
    art, iss = [], []
    for i in issues:
        iss.append({'title': i['subject'], 'link': i.get('issue_url') or link, 'guid': i['id'], 'date': i['date'], 'html': i['html']})
        for a in i['articles']:
            art.append({'title': a['title'], 'link': a['url'], 'guid': hashlib.sha1((i['id'] + a['url']).encode()).hexdigest(),
                        'date': i['date'], 'summary': item_summary(a, i['subject'], source)})
    write_atomic(os.path.join(out_dir, f'{source}.xml'), rss(f'{title}: links', link, 'One item per link', art))
    write_atomic(os.path.join(out_dir, f'{source}_issues.xml'), rss(f'{title}: issues', link, 'One item per email, full body', iss))
    return len(iss), len(art)
