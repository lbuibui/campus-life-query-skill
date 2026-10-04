#!/usr/bin/env python3
"""对上游生成的索引施加本项目的本地修正（幂等）。

为什么需要它：`references/index.md` 是上游生成物，但本项目对其有两类必要
修正——(1) 上游数据瑕疵（校名前导点号、无法识别的原始简称需要标注）；
(2) 本地事实（学校总数、日期戳、上游 SHA、口径说明）。做数据同步时若用
`git checkout` 回退索引，这些修正会一并丢失。本脚本把它们固化下来，任何
时候重跑都能恢复到正确状态。

用法：
    python3 tools/patch_index.py           # 施加修正（幂等）
    python3 tools/patch_index.py --check   # 只检查是否需要修正
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIVE = ROOT / "references" / "index.md"
ARCH = ROOT / "references" / "archived" / "index.md"
ALIASES = ROOT / "references" / "aliases.md"

UP_SHA = "0abf14dfc897838b5e9b11231766f64719a1bdf2"
UP_DATE = "2026-09-19"

# 学校名前导点号（上游数据瑕疵）
DOT_FIX = (
    "| .山东省德州市庆云县云天职业技术学院 | 其他 |",
    "| 山东省德州市庆云县云天职业技术学院 | 其他 |",
)

# 上游原始简称：无法识别为学校，需在索引里标注（加备注列）
ABBREV = ["swpu", "tj", "xn"]
ABBREV_NOTE = "上游原始简称，未识别出学校，数据仅 1 条回答"


def fix_active(text: str, n_active: int, n_alias: int, n_other: int) -> tuple[str, int]:
    changes = 0

    if DOT_FIX[0] in text:
        text = text.replace(DOT_FIX[0], DOT_FIX[1], 1)
        changes += 1

    for ab in ABBREV:
        # 只匹配前三列，避免把已带备注列的行再改一次（幂等）
        pattern = rf"^\| {re.escape(ab)} \| 其他 \| {re.escape(ab)}\.md \|(?![^\n]*{re.escape(ABBREV_NOTE)})"
        new_text, n = re.subn(
            pattern, lambda m: f"| {ab} | 其他 | {ab}.md | {ABBREV_NOTE} |", text, count=1, flags=re.M
        )
        if n:
            text = new_text
            changes += n

    # 日期戳 + 上游 SHA
    text = re.sub(
        r"数据更新日期：\d{4}-\d{2}-\d{2}\n(?:上游版本（generated 分支）：[0-9a-f]+\n)?",
        f"数据更新日期：{UP_DATE}\n上游版本（generated 分支）：{UP_SHA[:12]}\n",
        text,
        count=1,
    )

    # 覆盖范围表述
    text = re.sub(
        r"共 \d+ 所学校（含分校区）[^\n]*\n",
        f"共 {n_active} 所学校（含分校区）：中国大陆 31 个省级行政区，"
        f"另有 {n_other} 所标为「其他」（多为海外院校或上游未能归类的学校）。\n",
        text,
        count=1,
    )

    # 检索说明（含别名索引指引与本地修正说明）
    if "先用 `references/aliases.md` grep" not in text:
        text = re.sub(
            r"当用户提到[^\n]*先在本索引中用 grep 搜索确定文件名，再读取对应目录下文件。\n",
            "当用户提到学校名称时，先用 `references/aliases.md` grep 简称/别名；"
            "本索引只收录中文全称，可用全称或关键词 grep 确定文件名，再读取对应目录下文件。\n",
            text,
            count=1,
        )
    note = (
        "\n> 说明：本文件的「数据来源」列表已脱敏，原问卷填写者留下的邮箱等标识统一替换为「实名反馈者 N」。\n"
        "> 索引中标注「上游原始简称，未识别出学校」的条目（`tj`、`xn`、`swpu`）保留上游原始标识，未做猜测性改名。\n"
        "> 上游曾有 1 个 69 字符乱码文件名（问卷者把校名变更说明填进校名字段），其 2026 年回答已归并进"
        "「广东轻工职业技术大学」，详见 `tools/consolidate.py`。\n"
    )
    if "乱码文件名" not in text:
        anchor = "再读取对应目录下文件。\n"
        text = text.replace(anchor, anchor + note, 1)
        changes += 1

    return text, changes


def fix_archived(text: str, n_arch: int, n_other: int) -> tuple[str, int]:
    changes = 0
    text = re.sub(
        r"数据更新日期：\d{4}-\d{2}-\d{2}\n(?:上游版本（generated 分支）：[0-9a-f]+\n)?",
        f"数据更新日期：{UP_DATE}\n上游版本（generated 分支）：{UP_SHA[:12]}\n",
        text,
        count=1,
    )
    text = re.sub(
        r"共 \d+ 所已归档学校（含分校区）[^\n]*\n",
        f"共 {n_arch} 所已归档学校（含分校区），覆盖 31 个省级行政区"
        f"（另有 {n_other} 所标为「其他」）。\n",
        text,
        count=1,
    )
    if "已脱敏（见 `tools/redact.py`）" not in text:
        anchor = "目录下对应文件。\n"
        text = text.replace(
            anchor,
            anchor + "\n> 说明：本目录文件的「数据来源」列表已脱敏（见 `tools/redact.py`），"
            "答复时仍需注明数据为 2023 年前、条件可能已过时。\n",
            1,
        )
        changes += 1
    return text, changes


def count_rows(path: Path, layout: str) -> tuple[int, int]:
    """返回 (行数, 「其他」行数)。"""
    a = other = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("学校名", "别名 / 简称", "简称"):
            continue
        if set(cells[0]) <= set("-: "):
            continue
        a += 1
        if layout == "school" and cells[1] == "其他":
            other += 1
    return a, other


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    n_active, n_other_a = count_rows(ACTIVE, "school")
    n_arch, n_other_ar = count_rows(ARCH, "school")
    n_alias = count_rows(ALIASES, "alias")[0] if ALIASES.exists() else 0

    total_changes = 0
    for path, fn, args_ in (
        (ACTIVE, fix_active, (n_active, n_alias, n_other_a)),
        (ARCH, fix_archived, (n_arch, n_other_ar)),
    ):
        text = path.read_text(encoding="utf-8")
        new, changes = fn(text, *args_)
        total_changes += changes
        if changes and not args.check:
            path.write_text(new, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {'需修正' if changes else '已是最新'}（{changes} 处）")

    if args.check:
        print(f"[check] 共需修正 {total_changes} 处")
        return 1 if total_changes else 0
    print(f"共修正 {total_changes} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
