"""把方法层 + 全部卡片打包成可上传到 claude.ai 的 skill：dist/qingbian.skill（zip 格式）。

用法：.venv/bin/python scripts/build_claude_skill.py

步骤：先跑卡片核对（有问题就停）→ 组装 dist/qingbian/ → 校验 SKILL.md → 打成 zip。
原文不打包：体积大，卡片已含观点、论证链和逐字锚句。
"""
import re
import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "skill_src"
DIST = ROOT / "dist"
NAME = "qingbian"


def check_cards():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_cards.py")], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        sys.exit("卡片核对没通过，先修好再打包")


def validate(skill_md):
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        sys.exit("SKILL.md 缺少 frontmatter")
    fm = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", m.group(1), re.M))
    if set(fm) - {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}:
        sys.exit(f"frontmatter 有不允许的字段：{set(fm)}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm.get("name", "")) or len(fm["name"]) > 64:
        sys.exit("name 必须是小写字母/数字/连字符，最长 64")
    desc = fm.get("description", "").strip()
    if not desc or len(desc) > 1024 or "<" in desc or ">" in desc:
        sys.exit(f"description 为空、超过 1024 字或含尖括号（当前 {len(desc)} 字）")


MAX_FILES = 200  # claude.ai 上传上限


def write_references(ref):
    """claude.ai 拒收含中文/全角符号路径、超过 200 个文件的 zip，所以包内：
    方法层 → method.md；卡片按月合并成 cards/YYYY-MM.md，每张前加一行 <!-- card 日期 -->
    （日期唯一）；标题收进 index.md。"""
    cards_dir = ref / "cards"
    cards_dir.mkdir(parents=True)
    shutil.copy(ROOT / "方法层.md", ref / "method.md")
    rows, months, seen = [], {}, set()
    for p in sorted((ROOT / "cards").glob("*.md")):
        date, title = p.stem[:10], p.stem[11:]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or date in seen:
            sys.exit(f"卡片文件名日期不合规或重复：{p.name}")
        seen.add(date)
        text = p.read_text(encoding="utf-8").strip()
        months.setdefault(date[:7], []).append(f"<!-- card {date} -->\n{text}\n")
        rows.append(f"- {date} 《{title}》")
    for month, cards in months.items():
        (cards_dir / f"{month}.md").write_text("\n".join(cards), encoding="utf-8")
    (ref / "index.md").write_text(
        f"# 卡片目录（{len(rows)} 张）\n\n"
        "卡片按月存在 `references/cards/YYYY-MM.md`，每张以 `<!-- card 日期 -->` 开头。\n\n"
        + "\n".join(rows) + "\n",
        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-articles", action="store_true", help="本机私用包附带已确认正文边界的原文")
    args = ap.parse_args()
    check_cards()
    out = DIST / NAME
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SRC, out, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    write_references(out / "references")
    n_articles, excluded_articles = 0, []
    if args.include_articles:
        articles = out / "references" / "articles"
        articles.mkdir()
        months, rows = {}, []
        for p in sorted((ROOT / "articles").glob("*.md")):
            text = p.read_text(encoding="utf-8")
            if not re.search(r"^end_marker: true$", text, re.M):
                excluded_articles.append(p.name)
                continue  # 推广边界不清的原文不进入 skill
            aid = re.search(r'^id: "([^"]+)"$', text, re.M)
            if not aid:
                sys.exit(f"原文缺 id：{p.name}")
            key = "article:" + aid.group(1)
            months.setdefault(p.name[:7], []).append(f"<!-- article {key} -->\n{text.strip()}\n")
            rows.append(f"- {key} {p.stem}")
        for month, texts in months.items():
            (articles / f"{month}.md").write_text("\n".join(texts), encoding="utf-8")
        n_articles = len(rows)
        (out / "references" / "articles-index.md").write_text("# 原文目录（非观点卡片）\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    n_cards = len(list((ROOT / "cards").glob("*.md")))
    skill = out / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("{{CARD_COUNT}}", str(n_cards)).replace("{{ARTICLE_COUNT}}", str(n_articles)), encoding="utf-8")
    (out / "references" / "coverage.json").write_text(json.dumps({"cards": n_cards, "searchable_articles": n_articles, "excluded_articles": excluded_articles}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.include_articles:
        print(f"原文可检索 {n_articles} 篇；正文边界待核 {len(excluded_articles)} 篇，未打包（清单见 references/coverage.json）")
    validate(out / "SKILL.md")

    pkg = DIST / f"{NAME}.skill"
    files = [f for f in sorted(out.rglob("*")) if f.is_file()]
    bad = [str(f.relative_to(DIST)) for f in files if not re.fullmatch(r"[A-Za-z0-9._/-]+", str(f.relative_to(DIST)))]
    if bad:
        sys.exit(f"包内路径必须是 ASCII（claude.ai 会拒收）：{bad[:5]}")
    if len(files) > MAX_FILES:
        sys.exit(f"包内 {len(files)} 个文件，超过 claude.ai 上限 {MAX_FILES}")
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(DIST))
    n_cards = sum(t.read_text(encoding="utf-8").count("<!-- card ") for t in (out / "references" / "cards").glob("*.md"))
    print(f"\n已生成 {pkg.relative_to(ROOT)}：{n_cards} 张卡片，{len(files)} 个文件，{pkg.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
