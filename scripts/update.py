"""一键更新：发现合集 → 补正文 → 覆盖报告 → 核对打包 → 可选同步本机 skill。

用法：.venv/bin/python scripts/update.py [--offline] [--install]
离线模式不请求网络，仅检查、打包当前数据。失败保留已有 skill。
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
RECENT_DAYS = 30


def run(script, *args):
    subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args], check=True)


def coverage():
    items = [json.loads(l) for l in (ROOT / 'data/list.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    articles, unsafe = {}, []
    for p in sorted((ROOT / 'articles').glob('*.md')):
        text = p.read_text(encoding='utf-8')
        match = re.search(r'^id: "([^"]+)"$', text, re.M)
        if not match:
            raise ValueError(f'原文缺 ID：{p.name}')
        if match.group(1) in articles:
            raise ValueError(f'原文 ID 重复：{match.group(1)}')
        articles[match.group(1)] = p
        if not re.search(r'^end_marker: true$', text, re.M):
            unsafe.append(p.name)
    cards = {p.name for p in (ROOT / 'cards').glob('*.md')}
    groups = {}
    for it in items:
        for a in it.get('albums', [{'id': '', 'title': it.get('album', '未知')} ]):
            group = groups.setdefault(a['title'], {'listed': 0, 'downloaded': 0, 'cards': 0})
            group['listed'] += 1
            p = articles.get(it['aid'])
            group['downloaded'] += p is not None
            group['cards'] += p is not None and p.name in cards
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'listed': len(items),
              'downloaded': len(articles), 'cards': len(cards), 'albums': groups,
              'searchable_articles': len(articles) - len(unsafe),
              'missing': [it['aid'] for it in items if it['aid'] not in articles],
              'needs_boundary_review': unsafe,
              'pending_cards': [p.name for p in articles.values() if p.name not in cards],
              'discovery_scope': '已下载文章页面可见的合集；不代表公众号全部历史文章或隐藏合集'}
    cutoff = datetime.now(timezone.utc).timestamp() - RECENT_DAYS * 86400
    missing_ids = set(report['missing'])
    report['recent_missing'] = [it['aid'] for it in items if it['aid'] in missing_ids and int(it['create_time']) >= cutoff]
    report['deferred_history'] = [it['aid'] for it in items if it['aid'] in missing_ids and int(it['create_time']) < cutoff]
    report['lookback_days'] = RECENT_DAYS
    (ROOT / 'data/coverage.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    checked = datetime.fromisoformat(report['checked_at']).astimezone(timezone(timedelta(hours=8)))
    lines = ['# 请辩知识库收录状态', '', f'核对时间：{checked:%Y-%m-%d %H:%M}（北京时间）', '',
             f"目录 {len(items)} 篇，已保存正文 {len(articles)} 篇，观点卡片 {len(cards)} 张；可打包原文 {report['searchable_articles']} 篇。", '',
             '卡片与原文可能对应同一篇文章，不能相加当文章总量。以下合集间也有交叉。', '',
             '| 合集 | 目录 | 正文 | 卡片 |', '| --- | ---: | ---: | ---: |']
    for title, group in sorted(groups.items()):
        lines.append(f"| {title} | {group['listed']} | {group['downloaded']} | {group['cards']} |")
    lines += ['', '范围：已下载页面中可识别的公开合集，不代表公众号全部历史文章。',
              '', f"周更只补近 {RECENT_DAYS} 天的新文和近期缺口；更早未收录的 {len(report['deferred_history'])} 篇不再自动补采。", '', '## 近期未取得正文', '']
    recent_ids = set(report['recent_missing'])
    lines += [f"- {it.get('title', '[缺标题]')}（{it['aid']}）" for it in items if it['aid'] in recent_ids] or ['无。']
    lines += ['', '## 正文边界待核（暂不打包原文）', '']
    lines += [f'- {name}' for name in sorted(unsafe)] or ['无。']
    lines += ['', f"详情：[覆盖数据]({ROOT / 'data/coverage.json'}) · [更新与回滚]({ROOT / '更新说明.md'})", '']
    (ROOT / '收录状态.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('listed', 'downloaded', 'cards', 'albums')}, ensure_ascii=False, indent=2), flush=True)
    return report


def hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def install(source, target):
    """先备份整个旧目录，逐文件核验；异常时恢复旧目录。只更新已安装的 qingbian。"""
    if target.name != 'qingbian' or target.is_symlink() or not (target / 'SKILL.md').is_file():
        raise ValueError(f'不是可更新的已安装 qingbian 目录：{target}')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = target.parent.parent / 'skill-backups' / target.name / stamp
    stage = target.parent / ('.qingbian-stage-' + stamp)
    expected = hashes(source)
    if not expected or 'SKILL.md' not in expected:
        raise ValueError('构建输出不完整')
    shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__'))
    # 保留旧安装的许可证及界面配置。
    for name in ('LICENSE', 'LICENSE-CONTENT.md', 'agents'):
        if (target / name).exists() and not (stage / name).exists():
            if (target / name).is_dir():
                shutil.copytree(target / name, stage / name)
            else:
                shutil.copy2(target / name, stage / name)
    staged_hashes = hashes(stage)
    if any(staged_hashes.get(k) != v for k, v in expected.items()):
        raise ValueError(f'暂存副本校验失败：{stage}')
    backup.parent.mkdir(parents=True, exist_ok=True)
    target.rename(backup)
    try:
        stage.rename(target)
        installed_hashes = hashes(target)
        if any(installed_hashes.get(k) != v for k, v in expected.items()):
            raise ValueError('安装后哈希校验失败')
    except BaseException:
        if target.exists():
            shutil.rmtree(target)
        backup.rename(target)
        raise
    return {'target': str(target), 'backup': str(backup), 'verified_files': len(expected)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--install', action='store_true')
    args = ap.parse_args()
    lock = ROOT / 'data/update.lock'
    lock.parent.mkdir(exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        network_error = None
        if not args.offline:
            # 新正文可能暴露更多合集；直到发现集合稳定。每轮正文仅补缺。
            from fetch_album import discover_albums
            for _ in range(10):
                before = set(discover_albums(ROOT / 'data/raw'))
                run('fetch_album.py', '--all')
                try:
                    try:
                        run('prefetch_articles.py', '--since-days', str(RECENT_DAYS))
                    except subprocess.CalledProcessError as exc:
                        network_error = str(exc)
                    run('fetch_articles.py', '--only-missing', '--offline')
                finally:
                    coverage()  # 失败也报告缺口；不把失败当作无更新。
                if network_error:
                    break  # 验证码或失败后不继续发现/联网；已成功正文仍可核对打包。
                after = set(discover_albums(ROOT / 'data/raw'))
                if after <= before:
                    break
            else:
                raise RuntimeError('合集发现超过 10 轮，停止并保留待查状态')
        report = coverage()
        run('build_claude_skill.py', '--include-articles')
        results = []
        if args.install:
            for parent in (Path.home() / '.codex/skills', Path.home() / '.claude/skills'):
                target = parent / 'qingbian'
                if target.exists():
                    results.append(install(ROOT / 'dist/qingbian', target))
            if not results:
                raise RuntimeError('没有找到已安装的 qingbian，未同步')
        state = {'checked_at': report['checked_at'], 'offline': args.offline, 'listed': report['listed'],
                 'downloaded': report['downloaded'], 'cards': report['cards'],
                 'searchable_articles': report['searchable_articles'],
                 'missing_count': len(report['missing']), 'boundary_review_count': len(report['needs_boundary_review']),
                 'recent_missing_count': len(report['recent_missing']), 'deferred_history_count': len(report['deferred_history']),
                 'status': 'partial' if report['recent_missing'] or network_error else 'complete',
                 'network_error': network_error,
                 'installs': results}
        (ROOT / 'data/last-update.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if results:
            (ROOT / 'data/last-install.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(state, ensure_ascii=False, indent=2))
        if network_error or (not args.offline and report['recent_missing']):
            raise RuntimeError('本轮仅部分完成；已核验内容已打包，缺口和失败见覆盖报告')
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()
