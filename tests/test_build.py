#!/usr/bin/env python3
"""build_db.py 的构建层测试：确定性构建、归并条目、内容摘要。

用临时目录里的迷你数据集构建，不读真实 data/（全量构建由 CI 的
`build_db.py --check` 覆盖）。
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_db  # noqa: E402

NAV = """    - 北京:
      - 示例大学: universities/sample.md
      - 示例大学医学部: universities/sample-yi-xue-bu.md
      - 原校名：示例大学学院学校升本了，校名改为示例大学: universities/misplaced.md
"""

NAV_ARCHIVED = """    - 北京:
      - 归档大学 (已归档): archived/universities/archived.md
"""

SCHOOL = """# 示例大学

> 数据来源：

<details><summary>点击展开</summary>
<ul>
<li>A10001: 匿名 (2024 年 06 月)</li>
</ul>
</details>

## Q: 教室和宿舍有没有空调？

- A10001: 有空调

## 自由补充部分

A10001: 无
"""

# 上游错放条目形态：校名字段是一整句说明，回答其实属于另一所学校
MISPLACED = """# 原校名：示例大学学院

学校升本了，校名改为示例大学

> 数据来源：

<details><summary>点击展开</summary>
<ul>
<li>A10002: 匿名 (2026 年 02 月)</li>
</ul>
</details>

## Q: 教室和宿舍有没有空调？

- A10002: 没有空调

## 自由补充部分

A10002: 补充
"""

OTHER = SCHOOL.replace("# 示例大学", "# 示例大学医学部").replace("A10001", "A10003")
ARCHIVED = SCHOOL.replace("# 示例大学", "# 归档大学").replace("A10001", "A10004")


class BuildFixture(unittest.TestCase):
    """搭一个 3 校 + 1 错放条目的迷你数据集并构建数据库。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "universities").mkdir()
        (self.root / "archived" / "universities").mkdir(parents=True)
        (self.root / "nav.txt").write_text(NAV, encoding="utf-8")
        (self.root / "archived" / "nav.txt").write_text(NAV_ARCHIVED,
                                                        encoding="utf-8")
        (self.root / "universities" / "sample.md").write_text(SCHOOL,
                                                              encoding="utf-8")
        (self.root / "universities" / "sample-yi-xue-bu.md").write_text(
            OTHER, encoding="utf-8")
        (self.root / "archived" / "universities" / "archived.md").write_text(
            ARCHIVED, encoding="utf-8")
        self._old_data = build_db.DATA
        self._old_merge = dict(build_db.MERGED_ENTRIES)
        build_db.DATA = self.root
        build_db.MERGED_ENTRIES = {
            "universities/misplaced.md": "示例大学",
        }
        (self.root / "universities" / "misplaced.md").write_text(
            MISPLACED, encoding="utf-8")

    def tearDown(self):
        build_db.DATA = self._old_data
        build_db.MERGED_ENTRIES = self._old_merge
        self.tmp.cleanup()

    def build(self, name: str = "index.sqlite") -> Path:
        out = self.root / name
        build_db.build(out)
        return out


class TestBuild(BuildFixture):
    def test_counts_and_merge(self):
        db = self.build()
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        # 归并条目不占学校行：3 校（活跃 2 + 归档 1）
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0], 3)
        row = conn.execute(
            "SELECT COUNT(*) FROM answers WHERE school_id ="
            " (SELECT id FROM schools WHERE name = '示例大学')").fetchone()[0]
        # 示例大学自身 2 条（空调 + 自由补充）+ 错放条目 2 条 = 4
        self.assertEqual(row, 4)
        pol = conn.execute(
            "SELECT polarity FROM answers WHERE body = '没有空调'").fetchone()[0]
        self.assertEqual(pol, "no")
        conn.close()

    def test_build_is_deterministic(self):
        a, b = self.build("a.sqlite"), self.build("b.sqlite")
        ha = hashlib.sha256(a.read_bytes()).hexdigest()
        hb = hashlib.sha256(b.read_bytes()).hexdigest()
        self.assertEqual(ha, hb, "两次构建的数据库字节应一致")

    def test_content_digest_stable_and_detects_tamper(self):
        db = self.build()
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        stored = conn.execute(
            "SELECT value FROM meta WHERE key='content_digest'").fetchone()[0]
        self.assertEqual(build_db.content_digest(conn), stored)
        conn.execute(
            "UPDATE answers SET body = 'tampered' WHERE school_id = 1 AND qid = 2 AND seq = 0")
        conn.commit()
        self.assertNotEqual(build_db.content_digest(conn), stored)
        conn.close()

    def test_alias_guard_no_hijack(self):
        db = self.build()
        conn = sqlite3.connect(db)
        # 「示例大学医学部」去后缀派生的「示例大学」会劫持真实校名，必须被丢弃
        rows = conn.execute(
            "SELECT COUNT(*) FROM aliases WHERE alias = '示例大学'").fetchone()[0]
        self.assertEqual(rows, 0)
        conn.close()

    def test_check_mode_accepts_fresh_build(self):
        db = self.build()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = build_db.main(["--check", "--out", str(db)])
        self.assertEqual(rc, 0)
        self.assertIn("一致", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
