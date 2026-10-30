import json
import time
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fetch_album
import fetch_articles
import update
import prefetch_articles
import build_claude_skill


class UpdatesTest(unittest.TestCase):
    def test_private_package_excludes_unreviewed_articles(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for directory in ('cards', 'articles', 'skill_src'):
                (root / directory).mkdir()
            (root / '方法层.md').write_text('方法')
            (root / 'cards/2026-10-30_Test.md').write_text('# Test')
            (root / 'skill_src/SKILL.md').write_text('---\nname: qingbian\ndescription: Test\n---\n{{CARD_COUNT}} {{ARTICLE_COUNT}}')
            for key, marker in [('safe', 'true'), ('unsafe', 'false')]:
                (root / f'articles/2026-10-30_{key}.md').write_text(f'---\nid: "{key}"\nend_marker: {marker}\n---\n# {key}\n正文')
            with patch.object(build_claude_skill, 'ROOT', root), patch.object(build_claude_skill, 'SRC', root / 'skill_src'), patch.object(build_claude_skill, 'DIST', root / 'dist'), patch.object(build_claude_skill, 'check_cards'), patch.object(sys, 'argv', ['build_claude_skill.py', '--include-articles']):
                build_claude_skill.main()
            out = root / 'dist/qingbian'
            body = (out / 'references/articles/2026-10.md').read_text()
            self.assertIn('article:safe', body)
            self.assertNotIn('article:unsafe', body)
            manifest = json.loads((out / 'references/coverage.json').read_text())
            self.assertEqual(manifest['searchable_articles'], 1)
            self.assertEqual(manifest['excluded_articles'], ['2026-10-30_unsafe.md'])

    def test_album_http_rate_limit_does_not_retry(self):
        from unittest.mock import Mock
        session = Mock()
        session.get.return_value.status_code = 429
        with patch.object(fetch_album.time, 'sleep') as sleep:
            with self.assertRaises(RuntimeError):
                fetch_album.get_page(session, 'test')
        self.assertEqual(session.get.call_count, 1)
        sleep.assert_not_called()

    def test_coverage_counts_missing_and_multi_album_articles(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for directory in ('data', 'articles', 'cards'):
                (root / directory).mkdir()
            items = [{'aid': 'x', 'create_time': int(time.time()), 'albums': [{'id': '1', 'title': '认知'}, {'id': '2', 'title': '财富'}]},
                     {'aid': 'y', 'create_time': 0, 'albums': [{'id': '2', 'title': '财富'}]}]
            (root / 'data/list.jsonl').write_text('\n'.join(json.dumps(x) for x in items))
            (root / 'articles/a.md').write_text('---\nid: "x"\nend_marker: false\n---\n正文')
            (root / 'cards/a.md').write_text('卡片')
            with patch.object(update, 'ROOT', root):
                result = update.coverage()
            self.assertEqual(result['missing'], ['y'])
            self.assertEqual(result['recent_missing'], [])
            self.assertEqual(result['deferred_history'], ['y'])
            self.assertEqual(result['downloaded'], 1)
            self.assertEqual(result['searchable_articles'], 0)
            self.assertEqual(result['albums']['财富']['listed'], 2)
            self.assertEqual(result['albums']['认知']['downloaded'], 1)
            self.assertEqual(result['needs_boundary_review'], ['a.md'])

    def test_captcha_stops_subsequent_prefetch_requests(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            gate = prefetch_articles.RequestGate()
            session = Mock()
            session.headers = {}
            session.get.return_value.text = '环境异常，完成验证后即可继续访问'
            manager = Mock()
            manager.__enter__ = Mock(return_value=session)
            manager.__exit__ = Mock(return_value=False)
            with patch.object(prefetch_articles, 'RAW_DIR', Path(d)), patch.object(prefetch_articles.requests, 'Session', return_value=manager):
                with self.assertRaises(fetch_articles.CaptchaHit):
                    prefetch_articles.fetch({'aid': 'a', 'link': 'https://example.invalid/a'}, gate)
                status = prefetch_articles.fetch({'aid': 'b', 'link': 'https://example.invalid/b'}, gate)
                self.assertEqual(status, 'stopped')
                self.assertEqual(session.get.call_count, 1)
                self.assertEqual(list(Path(d).iterdir()), [])

    def test_multi_album_memberships_survive_refresh(self):
        old = {'x': {'aid': 'x', 'album': '认知'}}
        new = {'x': {'aid': 'x', 'album': '财富', 'albums': [{'id': 'wealth', 'title': '财富'}]}}
        merged = fetch_album.merge_items(old, new)
        again = fetch_album.merge_items(merged, new)
        self.assertEqual(len(again), 1)
        self.assertEqual({a['title'] for a in again['x']['albums']}, {'认知', '财富'})
        self.assertEqual(len(again['x']['albums']), 2)

    def test_removed_album_membership_is_not_reintroduced_from_legacy_label(self):
        old = {'x': {'aid': 'x', 'album': '认知', 'albums': []}}
        new = {'x': {'aid': 'x', 'album': '财富', 'albums': [{'id': 'wealth', 'title': '财富'}]}}
        merged = fetch_album.merge_items(old, new)
        self.assertEqual([a['title'] for a in merged['x']['albums']], ['财富'])

    def test_truncated_album_is_not_accepted(self):
        response = {'base_info': {'article_count': 2, 'title': '测试'}, 'article_list': [], 'continue_flag': '0'}
        with patch.object(fetch_album, 'get_page', return_value=response):
            with self.assertRaises(RuntimeError):
                fetch_album.fetch_album(None, 'test')

    def test_rate_limit_does_not_retry(self):
        from unittest.mock import Mock
        session = Mock()
        session.get.return_value.json.return_value = {'base_resp': {'ret': 200013}}
        with patch.object(fetch_album.time, 'sleep') as sleep:
            with self.assertRaises(RuntimeError):
                fetch_album.get_page(session, 'test')
        self.assertEqual(session.get.call_count, 1)
        sleep.assert_not_called()

    def test_discover_from_realistic_html(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'a.html').write_text("album_id: '123',\n title: '财富',")
            self.assertEqual(fetch_album.discover_albums(p)['123'], '财富')

    def test_article_filename_collision_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '2026-10-30_标题.md'
            p.write_text('---\nid: "old"\n---\nold')
            with patch.object(fetch_articles, 'OUT_DIR', Path(d)):
                with self.assertRaises(ValueError):
                    fetch_articles.write_markdown({'date': '2026-10-30', 'title': '标题'}, {}, 'new')
            self.assertIn('old', p.read_text())

    def test_install_backs_up_and_verifies_all_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, target = root / 'build', root / 'skills/qingbian'
            source.mkdir()
            target.mkdir(parents=True)
            (source / 'SKILL.md').write_text('new')
            (source / 'references').mkdir()
            (source / 'references/card.md').write_text('evidence')
            (target / 'SKILL.md').write_text('old')
            (target / 'LICENSE').write_text('license')
            result = update.install(source, target)
            self.assertEqual((target / 'SKILL.md').read_text(), 'new')
            self.assertEqual((Path(result['backup']) / 'SKILL.md').read_text(), 'old')
            self.assertEqual((target / 'LICENSE').read_text(), 'license')
            self.assertEqual(result['verified_files'], 2)

    def test_failed_install_restores_old_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, target = root / 'build', root / 'skills/qingbian'
            source.mkdir()
            target.mkdir(parents=True)
            (source / 'SKILL.md').write_text('new')
            (target / 'SKILL.md').write_text('old')
            original = update.hashes
            calls = 0
            def fail_final(path):
                nonlocal calls
                calls += 1
                return {} if calls == 3 else original(path)
            with patch.object(update, 'hashes', side_effect=fail_final):
                with self.assertRaises(ValueError):
                    update.install(source, target)
            self.assertEqual((target / 'SKILL.md').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
