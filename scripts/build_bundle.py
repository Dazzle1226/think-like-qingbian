"""把方法层和卡片合并成几个大文件，给不能读仓库的聊天类工具上传（ChatGPT GPTs、Gemini Gems 等）。

用法：python3 scripts/build_bundle.py   （只用标准库）

输出 dist/bundle/：
  00-method.md（方法层）、cards-2023.md ~ cards-2026.md（按年份合并，每张卡片前加标题分隔）、system-prompt.md
同时打成 dist/qingbian-chat.zip 供直接下载。文件名用 ASCII，避免 Windows 解压乱码。
"""
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "bundle"


def main():
    cards = sorted((ROOT / "cards").glob("*.md"))
    if not cards:
        sys.exit("cards/ 是空的")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copy(ROOT / "方法层.md", OUT / "00-method.md")
    prompt = (ROOT / "prompts" / "system-prompt.md").read_text(encoding="utf-8")
    body = re.search(r"\n---\n(.*)\n---", prompt, re.S)
    (OUT / "system-prompt.md").write_text(body.group(1).strip() + "\n" if body else prompt, encoding="utf-8")

    by_year = defaultdict(list)
    for c in cards:
        by_year[c.name[:4]].append(c)
    for year, items in sorted(by_year.items()):
        parts = [f"# 请辩观点卡片 · {year} 年（{len(items)} 张，非官方读书笔记）\n"]
        for c in items:
            text = c.read_text(encoding="utf-8").strip()
            parts.append(f"\n\n======== {c.name[:-3]} ========\n\n{text}\n")
        (OUT / f"cards-{year}.md").write_text("".join(parts), encoding="utf-8")

    for f in sorted(OUT.iterdir()):
        print(f"  {f.name}  {f.stat().st_size / 1024:.0f} KB")
    pkg = OUT.parent / "qingbian-chat.zip"
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.iterdir()):
            z.write(f, f"qingbian-chat/{f.name}")
    print(f"\n已生成 {OUT.relative_to(ROOT)}/：{len(cards)} 张卡片按年份合并")
    print(f"已打包 {pkg.relative_to(ROOT)}：{pkg.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
