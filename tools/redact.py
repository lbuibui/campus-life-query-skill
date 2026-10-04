#!/usr/bin/env python3
"""脱敏 references/ 中学校文件「数据来源」列表里的个人信息。

背景：上游 CollegesChat/university-information 的生成数据把问卷填写者留下的
邮箱原样写进了每所学校文件的 <details> 来源列表（活跃库 1,501 个文件、2,672
个邮箱；归档库 1,026 个文件、1,965 个）。项目以 CC BY-NC-SA 4.0 公开发布，
个人邮箱属于不该随数据集二次分发的信息。

处理方式：
  - 只动来源列表里的「标识」字段，<li> 的问卷编号与时间戳保持原样；
  - 每个不同的标识映射为稳定的「实名反馈者 N」，同一标识在全库得到同一编号，
    因此同一人的多条回答仍可辨认为同一来源；
  - 幂等：重复运行不会改变结果，也不会重复插入提示行。

用法：
    python3 tools/redact.py --check    # 只统计，不写入
    python3 tools/redact.py            # 执行脱敏
    python3 tools/redact.py --dry-run  # 打印将要替换的内容
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [
    ROOT / "references" / "universities",
    ROOT / "references" / "archived" / "universities",
]

# <li>A12345: 标识 (2025 年 06 月)</li>
LI_RE = re.compile(r"<li>(A\d+):\s*(.*?)\s*\(([^)]*)\)</li>")
ANON = "匿名"
REDACTED = "实名反馈者"
NOTE = "> 数据来源中的个人信息已匿名化处理（原始标识已替换为“实名反馈者 N”）。"

# 匹配任何像邮箱 / 手机号 / 社交账号的标识，用于 --check 兜底扫描
SENSITIVE_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|\b1[3-9]\d{9}\b"
    r"|\b\d{5,12}\b"
)


def split_head(text: str) -> tuple[str, str]:
    """拆出第一个 "## " 之前的头部与之后的主体。"""
    idx = text.find("\n## ")
    if idx == -1:
        return text, ""
    return text[:idx], text[idx:]


def collect_identifiers() -> dict[str, str]:
    """全库扫描一次，为每个非匿名标识分配稳定编号。"""
    seen: list[str] = []
    for d in TARGET_DIRS:
        for path in sorted(d.glob("*.md")):
            head, _ = split_head(path.read_text(encoding="utf-8"))
            for _aid, ident, _date in LI_RE.findall(head):
                ident = ident.strip()
                if ANON in ident or ident.startswith(REDACTED):
                    continue
                if ident not in seen:
                    seen.append(ident)
    return {ident: f"{REDACTED} {i + 1}" for i, ident in enumerate(seen)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只统计，不写文件")
    ap.add_argument("--dry-run", action="store_true", help="打印替换内容，不写文件")
    args = ap.parse_args()

    mapping = collect_identifiers()
    print(f"扫描到 {len(mapping)} 个不同的非匿名标识")

    if args.check:
        files_with_pii = 0
        leftover: list[tuple[str, str]] = []
        for d in TARGET_DIRS:
            for path in sorted(d.glob("*.md")):
                head, _ = split_head(path.read_text(encoding="utf-8"))
                idents = [i.strip() for _a, i, _d in LI_RE.findall(head)]
                non_anon = [i for i in idents if ANON not in i and not i.startswith(REDACTED)]
                if non_anon:
                    files_with_pii += 1
                for i in non_anon:
                    if SENSITIVE_RE.search(i):
                        leftover.append((str(path.relative_to(ROOT)), i))
        print(f"仍含非匿名标识的文件：{files_with_pii}")
        print(f"其中匹配邮箱/手机号等敏感模式的标识：{len(leftover)}")
        if leftover[:10]:
            print("示例：")
            for f, i in leftover[:10]:
                print(f"  {f}: {i}")
        return 1 if leftover else 0

    if args.dry_run:
        for ident, repl in list(mapping.items())[:20]:
            print(f"  {ident!r} -> {repl!r}")
        print(f"  … 共 {len(mapping)} 条")
        return 0

    stats = {"files": 0, "replaced": 0}
    for d in TARGET_DIRS:
        for path in sorted(d.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            head, body = split_head(text)
            if not LI_RE.search(head):
                continue

            count = 0

            def sub(m: re.Match[str]) -> str:
                nonlocal count
                aid, ident, date = m.group(1), m.group(2).strip(), m.group(3)
                if ANON in ident or ident.startswith(REDACTED):
                    return m.group(0)
                count += 1
                return f"<li>{aid}: {mapping[ident]} ({date})</li>"

            new_head = LI_RE.sub(sub, head)
            if count == 0:
                continue
            if NOTE not in new_head:
                # 插到第一个空行之后（免责声明块之后），保持排版
                marker = "\n\n"
                at = new_head.find(marker)
                if at != -1:
                    new_head = new_head[: at + len(marker)] + NOTE + "\n\n" + new_head[at + len(marker) :]
                else:
                    new_head = new_head.rstrip() + "\n\n" + NOTE + "\n\n"

            tmp = path.with_suffix(".md.tmp")
            tmp.write_text(new_head + body, encoding="utf-8")
            tmp.replace(path)
            stats["files"] += 1
            stats["replaced"] += count

    print(f"已处理 {stats['files']} 个文件，替换 {stats['replaced']} 处标识")
    return 0


if __name__ == "__main__":
    sys.exit(main())
