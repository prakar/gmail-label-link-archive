"""Tests run on the fake fixture only. No network, no Gmail, no real credentials."""
import email, json, os, sqlite3, sys, tempfile, unittest
from email import policy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from linkarchive import archive, feeds, site                       # noqa: E402
from linkarchive.config import Config                              # noqa: E402
from linkarchive.extract import Profile, issue_from_message, clean_url, parse_date   # noqa: E402

PROFILE = Profile.load(os.path.join(ROOT, 'config', 'profiles', 'example-newsletter.toml'))
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'sample_issue.eml')


def load():
    with open(FIXTURE, 'rb') as fh: return email.message_from_binary_file(fh, policy=policy.default)


class Extraction(unittest.TestCase):
    def setUp(self): self.issue = issue_from_message(load(), PROFILE)

    def kinds(self): return {x['title']: x['kind'] for x in self.issue['all_links']}

    def test_subject_forward_prefix_removed(self):
        self.assertEqual(self.issue['subject'], 'Example Digest: Issue 42')

    def test_kinds(self):
        k = self.kinds()
        self.assertEqual(k['The slow rise of community orchards'], 'article')
        self.assertEqual(k['Why seed libraries keep growing'], 'article')
        self.assertEqual(k['Listening to the river'], 'podcast')
        self.assertEqual(k['Pruning apple trees'], 'video')
        self.assertEqual(k['long report on seed libraries'], 'other')
        self.assertEqual(k['Example Digest: Issue 42'], 'issue')
        self.assertEqual(k['Frequently asked questions about this digest'], 'footer')

    def test_skipped_links_absent(self):
        titles = ' '.join(self.kinds())
        self.assertNotIn('Unsubscribe', titles)
        self.assertNotIn('Share this', titles)

    def test_meta_fields(self):
        a = next(x for x in self.issue['all_links'] if x['title'].startswith('The slow rise'))
        self.assertEqual((a['author'], a['publication'], a['published'], a['access']), ('Jane Roe', 'Example Gazette', '2026-08-13', 'U'))
        self.assertIn('empty city lots', a['comment'])
        b = next(x for x in self.issue['all_links'] if x['title'].startswith('Why seed'))
        self.assertEqual((b['published'], b['published_raw'], b['access']), ('2026-03-01', 'March 2026', 'M'))

    def test_title_split(self):
        p = next(x for x in self.issue['all_links'] if x['kind'] == 'podcast')
        v = next(x for x in self.issue['all_links'] if x['kind'] == 'video')
        self.assertEqual(p['show'], 'Example Audio Show')
        self.assertEqual(v['channel'], 'YouTube | Example Channel | 12m 04s')

    def test_tracking_unwrapped_and_params_dropped(self):
        b = next(x for x in self.issue['all_links'] if x['title'].startswith('Why seed'))
        self.assertEqual(b['url'], 'https://example.org/essay')
        self.assertEqual(clean_url('https://example.org/a?utm_source=x&keep=1', PROFILE), 'https://example.org/a?keep=1')

    def test_issue_url_and_kept_kinds(self):
        self.assertEqual(self.issue['issue_url'], 'https://news.example.com/issue/42')
        self.assertEqual({x['kind'] for x in self.issue['articles']}, {'article', 'podcast', 'video', 'other'})

    def test_dates(self):
        self.assertEqual(parse_date('13th August 2026', PROFILE), '2026-08-13')
        self.assertEqual(parse_date('not a date', PROFILE), '')


class StoreAndOutputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = archive.open_db(self.tmp.name)

    def test_ingest_is_idempotent_and_rkeys_set(self):
        self.assertTrue(archive.ingest(self.db, load(), 'example-digest', PROFILE))
        self.assertFalse(archive.ingest(self.db, load(), 'example-digest', PROFILE))
        rk = {r[0] for r in self.db.execute("SELECT rkey FROM links WHERE rkey!=''")}
        self.assertEqual(rk, {'news.example.com/r/abc123', 'news.example.com/r/def456', 'news.example.com/r/ghi789', 'news.example.com/r/jkl012'})

    def test_reextract_keeps_link_count(self):
        archive.ingest(self.db, load(), 'example-digest', PROFILE)
        before = self.db.execute('SELECT COUNT(*) FROM links').fetchone()[0]
        self.assertEqual(archive.reextract(self.db, 'example-digest', PROFILE), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM links').fetchone()[0], before)

    def test_resolution_is_used_by_outputs(self):
        archive.ingest(self.db, load(), 'example-digest', PROFILE)
        self.db.execute("INSERT INTO resolutions VALUES('news.example.com/r/abc123','https://example.org/orchards','ok','2026-01-01')")
        issues = archive.issues_from_db(self.db, 'example-digest', PROFILE)
        self.assertIn('https://example.org/orchards', [x['url'] for x in issues[0]['articles']])

    def test_feeds_and_site(self):
        archive.ingest(self.db, load(), 'example-digest', PROFILE)
        out = os.path.join(self.tmp.name, 'out')
        n_iss, n_art = feeds.build_feeds(archive.issues_from_db(self.db, 'example-digest', PROFILE), out, 'example-digest', 'Test archive')
        self.assertEqual((n_iss, n_art), (1, 5))
        for name in ('example-digest.xml', 'example-digest_issues.xml'):
            import xml.etree.ElementTree as ET
            ET.parse(os.path.join(out, name))                    # well-formed XML
        page = site.build_site(self.db, out, 'Test archive', {'example-digest': PROFILE})
        with open(page, encoding='utf-8') as fh: text = fh.read()
        self.assertIn('The slow rise of community orchards', text)
        self.assertNotIn('__DATA__', text)

    def test_resolve_off_when_no_hosts(self):
        prof = Profile({'name': 'x'})
        archive.ingest(self.db, load(), 'example-digest', prof)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM links WHERE rkey!=''").fetchone()[0], 0)


class ExampleConfig(unittest.TestCase):
    def test_example_files_parse(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'profiles'))
            for n in ('accounts',):
                with open(os.path.join(ROOT, 'config', n + '.example.json')) as s, open(os.path.join(d, n + '.json'), 'w') as t: t.write(s.read())
            with open(os.path.join(ROOT, 'config', 'profiles', 'example-newsletter.toml')) as s, open(os.path.join(d, 'profiles', 'example-newsletter.toml'), 'w') as t: t.write(s.read())
            cfg = Config(d)
            (acc, lab), = cfg.sources()
            self.assertEqual(cfg.profile(lab['profile']).name, 'example-newsletter')
            self.assertTrue(acc['user'].endswith('@example.com'))
        with open(os.path.join(ROOT, 'config', 'credentials.example.json')) as fh: json.load(fh)


CASE_FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'case_sample.eml')


def case_profile(**rule_extra):
    return Profile({'name': 'case-test', 'filter': {'min_title_chars': 10},
                    'rules': [{'kind': 'byline', 'blurb_regex': '^by .+ \u2022 ', **rule_extra}]})


class CaseSensitivity(unittest.TestCase):
    def kinds(self, profile):
        with open(CASE_FIXTURE, 'rb') as fh: msg = email.message_from_binary_file(fh, policy=policy.default)
        return {x['url'].rsplit('/', 1)[1]: x['kind'] for x in issue_from_message(msg, profile)['all_links']}

    def test_default_is_case_insensitive(self):
        self.assertEqual(self.kinds(case_profile()), {'lower': 'byline', 'upper': 'byline'})

    def test_case_sensitive_rule_does_not_match_other_casing(self):
        self.assertEqual(self.kinds(case_profile(case_sensitive=True)), {'lower': 'byline', 'upper': 'other'})

    def test_inline_flag_form_still_works(self):
        p = Profile({'name': 'case-test', 'filter': {'min_title_chars': 10}, 'rules': [{'kind': 'byline', 'blurb_regex': '(?-i:^by .+ \u2022 )'}]})
        self.assertEqual(self.kinds(p), {'lower': 'byline', 'upper': 'other'})

    def test_case_sensitive_applies_only_to_its_own_rule(self):
        p = Profile({'name': 'case-test', 'filter': {'min_title_chars': 10}, 'rules': [
            {'kind': 'strict', 'blurb_regex': '^by .+ \u2022 ', 'case_sensitive': True},
            {'kind': 'loose', 'blurb_regex': '^by .+ \u2022 '}]})
        self.assertEqual(self.kinds(p), {'lower': 'strict', 'upper': 'loose'})

    def test_meta_case_sensitive_option(self):
        meta = '^(?P<author>[^|]+?)\\s*\\|\\s*(?P<date>[^|]+?)\\s*\\|\\s*(?P<flag>[A-Z])$'
        loose = Profile({'meta': {'regex': meta}})
        strict = Profile({'meta': {'regex': meta, 'case_sensitive': True}})
        self.assertTrue(loose.meta.match('Ann | 2026 | u'))
        self.assertFalse(strict.meta.match('Ann | 2026 | u'))
        self.assertTrue(strict.meta.match('Ann | 2026 | U'))


class ResolveAllKinds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = archive.open_db(self.tmp.name)
        archive.ingest(self.db, load(), 'example-digest', PROFILE)

    def test_default_skips_footer_all_kinds_includes_it(self):
        default = {r[0] for r in archive.pending_links(self.db, 'example-digest', PROFILE)}
        every = {r[0] for r in archive.pending_links(self.db, 'example-digest', PROFILE, all_kinds=True)}
        self.assertEqual(default, {'news.example.com/r/abc123', 'news.example.com/r/def456', 'news.example.com/r/ghi789'})
        self.assertEqual(every - default, {'news.example.com/r/jkl012'})

    def test_resolve_follows_footer_only_with_all_kinds(self):
        import unittest.mock as mock
        calls = []
        def fake(url, profile): calls.append(url); return 'ok', 'https://example.org/target'
        with mock.patch.object(archive, 'resolve_url', fake), mock.patch.object(archive.time, 'sleep', lambda s: None):
            archive.resolve(self.db, 'example-digest', PROFILE, delay=0)
            self.assertFalse(any('jkl012' in u for u in calls))
            archive.resolve(self.db, 'example-digest', PROFILE, delay=0, all_kinds=True)
        self.assertTrue(any('jkl012' in u for u in calls))
        self.assertEqual(self.db.execute("SELECT status FROM resolutions WHERE rkey='news.example.com/r/jkl012'").fetchone()[0], 'ok')

    def test_cli_flag_is_accepted(self):
        from linkarchive.__main__ import main
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'cfg', 'profiles'))
            with open(os.path.join(ROOT, 'config', 'accounts.example.json')) as fh: c = json.load(fh)
            c['out_dir'], c['data_dir'] = os.path.join(d, 'out'), os.path.join(d, 'data')
            with open(os.path.join(d, 'cfg', 'accounts.json'), 'w') as fh: json.dump(c, fh)
            with open(os.path.join(ROOT, 'config', 'profiles', 'example-newsletter.toml')) as s, open(os.path.join(d, 'cfg', 'profiles', 'example-newsletter.toml'), 'w') as t: t.write(s.read())
            cfg = os.path.join(d, 'cfg')
            main(['--config', cfg, 'ingest', '--source', 'example-digest', FIXTURE])
            seen = []
            with mock.patch.object(archive, 'resolve_url', lambda u, p: (seen.append(u), ('ok', 'https://example.org/t'))[1]), mock.patch.object(archive.time, 'sleep', lambda s: None):
                main(['--config', cfg, 'resolve', '--all-kinds', '--delay', '0'])
            self.assertTrue(any('jkl012' in u for u in seen))


class Cli(unittest.TestCase):
    def test_ingest_stats_build_through_main(self):
        from linkarchive.__main__ import main
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'cfg', 'profiles'))
            with open(os.path.join(ROOT, 'config', 'accounts.example.json')) as fh: c = json.load(fh)
            c['out_dir'], c['data_dir'] = os.path.join(d, 'out'), os.path.join(d, 'data')
            with open(os.path.join(d, 'cfg', 'accounts.json'), 'w') as fh: json.dump(c, fh)
            with open(os.path.join(ROOT, 'config', 'profiles', 'example-newsletter.toml')) as s, open(os.path.join(d, 'cfg', 'profiles', 'example-newsletter.toml'), 'w') as t: t.write(s.read())
            cfg = os.path.join(d, 'cfg')
            main(['--config', cfg, 'ingest', '--source', 'example-digest', FIXTURE])      # option before the file: the order the README shows
            main(['--config', cfg, 'stats']); main(['--config', cfg, 'build'])
            self.assertTrue(os.path.exists(os.path.join(d, 'out', 'archive', 'index.html')))


if __name__ == '__main__':
    unittest.main()
