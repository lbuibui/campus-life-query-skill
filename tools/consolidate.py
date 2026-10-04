#!/usr/bin/env python3
"""把「问卷者把校名变更说明填进校名字段」造成的错放回答归并回正确学校。

背景：上游生成管线直接用问卷里的「学校名」字段做文件名与 H1 标题。个别填写
者在该字段写了说明文字（例如「原校名：广东轻工职业技术学院\n学校升本了，
校名改为广东轻工职业技术大学」），于是上游多出一个 69 字符乱码文件名、标题
是说明文字的孤立条目。该条目只有 1 位问卷者，但 25 问全覆盖、自由补充详尽，
质量很高，却不会被任何按学校名检索的路径找到。

归并策略：**原地插入**，不做整文件重建。历史教训：上游个别回答是多段落，
且「自由补充部分」的条目不带 `- ` 前缀；任何 parse→rebuild 的写法都会悄悄
吃掉这些行。这里只在三处插入文本，其余字节保持原样：
  1. <details> 来源列表中按提交时间插入一行；
  2. 各问题区块最后一条回答之后插入该问卷者的回答；
  3. 从索引移除错放文件的行，并删除错放文件。

用法：
    python3 tools/consolidate.py --check   # 只报告，不改动
    python3 tools/consolidate.py           # 执行归并
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"
ACTIVE = REF / "universities"
ARCHIVE_ACTIVE = REF / "archived" / "universities"
INDEX = REF / "index.md"

# 错放文件 → 目标学校名（目标文件由索引按学校名解析得出）
MERGE_MAP: dict[str, str] = {
    "yuan-xiao-ming-yan-dong-qing-gong-zhi-ye-ji-zhu-xue-yuan-xue-xiao-sheng-ben-liao-xiao-ming-gai-wei-yan-dong-qing-gong-zhi-ye-ji-zhu-da-xue.md":
        "广东轻工职业技术大学",
}

SOURCE_RE = re.compile(r"^<li>(A\d+):\s*(.*?)\s*\(([^)]*)\)</li>$", re.M)
ANSWER_RE = re.compile(r"^(- |)(A\d+):\s*(.*)$")
HEADING_RE = re.compile(r"^## (.+)$", re.M)


def parse_source_entry(path: Path, aid: str) -> tuple[str, str, str] | None:
    for a, ident, date in SOURCE_RE.findall(path.read_text(encoding="utf-8")):
        if a == aid:
            return a, ident, date
    return None


def parse_answers(path: Path) -> dict[str, list[str]]:
    """返回 {区块标题: [回答完整文本]}。

    回答完整文本 = 从答案行首到**下一条答案行首之前**的全部内容，因此多段落
    回答（上游确实存在，例如一条回答下另起一段补充说明）会被完整保留。
    历史教训：只取首行的实现会静默吃掉续行，曾导致 42 行内容丢失。
    """
    text = path.read_text(encoding="utf-8")
    body = text[text.find("\n## "):] if "\n## " in text else ""
    blocks: dict[str, list[str]] = {}
    for chunk in body.split("\n## "):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        lines = chunk.splitlines()
        heading = lines[0].strip()
        starts = [i for i, l in enumerate(lines) if i > 0 and ANSWER_RE.match(l)]
        answers = []
        for k, i in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else len(lines)
            answers.append("\n".join(lines[i:end]).rstrip())
        blocks[heading] = answers
    return blocks


def resolve_target(school: str) -> Path:
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == school:
            return ACTIVE / cells[2]
    raise SystemExit(f"索引中找不到学校：{school}")


def id_positions(aid: str) -> list[str]:
    hits: list[str] = []
    for d in (ACTIVE, ARCHIVE_ACTIVE):
        for p in d.glob("*.md"):
            if re.search(rf"^- {aid}:", p.read_text(encoding="utf-8"), re.M):
                hits.append(p.name)
    return hits


def insert_source_line(text: str, entry: tuple[str, str, str]) -> str:
    """按提交时间把来源行插入 <ul> 内。"""
    aid, ident, date = entry
    m = re.search(r"<ul>\n(.*?)\n</ul>", text, re.S)
    if not m:
        raise SystemExit("找不到 <ul> 来源列表")
    existing = SOURCE_RE.findall(m.group(1))
    rows = [(a, i, d) for a, i, d in existing] + [entry]

    def key(row: tuple[str, str, str]) -> tuple[str, str]:
        _a, _i, d = row
        mm = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月", d)
        return (f"{mm.group(1)}{int(mm.group(2)):02d}" if mm else "000000"), _a

    rows.sort(key=key)
    new_list = "\n".join(f"<li>{a}: {i} ({d})</li>" for a, i, d in rows)
    return text[: m.start(1)] + new_list + text[m.end(1):]


def insert_answers(text: str, answers: dict[str, list[str]]) -> tuple[str, list[str]]:
    """把每个区块的回答插到该区块最后一条回答之后（原地、逐条插入）。"""
    missing: list[str] = []
    for heading, items in answers.items():
        if not items:
            continue
        # 定位区块
        hm = re.search(rf"^## {re.escape(heading)}$", text, re.M)
        if not hm:
            missing.append(heading)
            continue
        # 区块结束：下一个 "## " 所在行首，或文件末尾
        nxt = text.find("\n## ", hm.end())
        end = nxt + 1 if nxt != -1 else len(text)
        segment = text[hm.end():end]
        # 区块内最后一条回答行（用行首偏移量定位，避免漏掉结尾换行）
        last_match = None
        for m in re.finditer(r"(?m)^(?:- )?A\d+:", segment):
            last_match = m
        if last_match is None:
            missing.append(heading + "（区块内无回答）")
            continue
        # 在该行之后、终止换行之前插入
        line_end = segment.find("\n", last_match.end())
        line_end = len(segment) if line_end == -1 else line_end + 1
        at = hm.end() + line_end
        inserted = "".join(
            (answer if answer.startswith("- ") else "- " + answer) + "\n"
            for answer in items
        )
        # 区块以 EOF 结束且原文末尾无换行时，补一个换行，避免拼接成同一行
        if at >= len(text) and not text.endswith("\n"):
            inserted = "\n" + inserted
        text = text[:at] + inserted + text[at:]
    return text, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    done = 0
    for bad_name, school in MERGE_MAP.items():
        bad_path = ACTIVE / bad_name
        if not bad_path.exists():
            print(f"[跳过] 错放文件已不存在：{bad_name[:36]}…（可能已归并）")
            continue

        target = resolve_target(school)
        bad_text = bad_path.read_text(encoding="utf-8")
        aids = [a for a, _i, _d in SOURCE_RE.findall(bad_text)]
        print(f"\n错放文件：{bad_name[:44]}…")
        print(f"  目标：{school} -> {target.name}")
        print(f"  来源 id：{aids}")
        if len(aids) != 1:
            print("  [中止] 预期恰好 1 个来源 id，需人工确认")
            continue

        aid = aids[0]
        positions = id_positions(aid)
        if positions and positions != [bad_path.name]:
            print(f"  [中止] {aid} 同时出现在 {positions}，存在重复计数风险")
            continue

        tgt_text = target.read_text(encoding="utf-8")
        if re.search(rf"^- {aid}:", tgt_text, re.M) or f"<li>{aid}:" in tgt_text:
            print(f"  [跳过] 目标文件已含 {aid}（幂等）")
            continue

        entry = parse_source_entry(bad_path, aid)
        if entry is None:
            print("  [中止] 错放文件中找不到该 id 的来源行")
            continue
        answers = parse_answers(bad_path)
        total = sum(len(v) for v in answers.values())
        print(f"  将插入：来源行 1 条、回答 {total} 条、覆盖区块 {len(answers)} 个")

        if args.check:
            print("  [check] 可以安全归并（未改动）")
            continue

        new_text = insert_source_line(tgt_text, entry)
        new_text, missing = insert_answers(new_text, answers)
        if missing:
            print(f"  [中止] 目标文件缺少区块：{missing}")
            continue
        target.write_text(new_text, encoding="utf-8")

        bad_path.unlink()
        idx = INDEX.read_text(encoding="utf-8")
        INDEX.write_text(
            "\n".join(l for l in idx.splitlines() if not (l.startswith("| ") and bad_name in l)) + "\n",
            encoding="utf-8",
        )
        print(f"  [完成] {aid} 已归并进「{school}」，错放文件已删除，索引行已移除")
        done += 1

    print(f"\n共归并 {done} 个错放条目")
    return 0


if __name__ == "__main__":
    sys.exit(main())
