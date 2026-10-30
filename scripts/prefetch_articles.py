"""同等全局请求间隔（3–6 秒），最多三路在途下载；验证码停止新请求。

仅预下载已知文章到 data/raw；原文转换仍由 fetch_articles.py 负责。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import random
import threading
import time

import requests

from fetch_articles import ROOT, RAW_DIR, UA, CaptchaHit, article_id, check_page


class RequestGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.next_start = 0.0

    def acquire(self):
        with self.lock:
            delay = max(0, self.next_start - time.monotonic())
            if self.stop.wait(delay):
                return False
            self.next_start = time.monotonic() + random.uniform(3, 6)
            return True


def fetch(item, gate):
    aid = article_id(item)
    raw = RAW_DIR / f'{aid}.html'
    if raw.exists():
        return 'cached'
    for attempt, wait in enumerate((5, 15, 45), 1):
        if not gate.acquire():
            return 'stopped'
        try:
            with requests.Session() as session:
                session.headers['User-Agent'] = UA
                r = session.get(item['link'], timeout=20)
                if r.status_code == 429:
                    gate.stop.set()
                    raise RuntimeError('微信返回 HTTP 429 限流，已停止新请求')
                r.raise_for_status()
                r.encoding = 'utf-8'
                html = r.text
            reason = check_page(html)
            if reason:
                raise ValueError(reason)
            tmp = raw.with_suffix('.tmp')
            tmp.write_text(html, encoding='utf-8')
            tmp.replace(raw)
            return 'downloaded'
        except CaptchaHit:
            gate.stop.set()
            raise
        except requests.RequestException:
            if attempt == 3:
                raise
            if gate.stop.wait(wait):
                return 'stopped'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since-days', type=int, default=30, help='只补近 N 天的缺失正文，默认不补旧文')
    args = ap.parse_args()
    if args.since_days <= 0:
        raise ValueError('since-days 必须大于零；历史补采需另行明确范围')
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    items = [json.loads(l) for l in (ROOT / 'data/list.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    cutoff = time.time() - args.since_days * 86400
    items = [it for it in items if int(it['create_time']) >= cutoff]
    items = [it for it in items if not (RAW_DIR / f"{article_id(it)}.html").exists()]
    gate, errors, ok = RequestGate(), [], 0
    # 队列按最新文章优先；最多三路在途，所有请求（包括重试）共用 gate。
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch, it, gate): it for it in items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                status = future.result()
                if status in ('downloaded', 'cached'):
                    ok += 1
                    print(f"[{ok}/{len(items)}] {item['title']}", flush=True)
            except Exception as exc:
                reason = '触发验证码，已停止新请求' if isinstance(exc, CaptchaHit) else str(exc)
                errors.append({'id': article_id(item), 'title': item['title'], 'reason': reason})
                print(f"失败：{item['title']}：{reason}", flush=True)
    if errors:
        (ROOT / 'data/prefetch-errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise RuntimeError(f'预下载失败 {len(errors)} 篇；成功 {ok}，缺口保留')
    print(f'预下载完成：{ok} 篇', flush=True)


if __name__ == '__main__':
    main()
