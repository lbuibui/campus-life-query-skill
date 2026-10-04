#!/usr/bin/env python3
"""query.py 测试：学校解析、维度路由、汇总渲染 + CLI 冒烟。

解析 / 路由 / 汇总用迷你库做纯函数测试；CLI 冒烟在真实 data/index.sqlite
上只读执行（库不存在时跳过）。
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import build_db  # noqa: E402
import polarity  # noqa: E402
import query  # noqa: E402

NAV = """    - 北京:
      - 示例科技大学: universities/sample.md
      - 示例科技大学医学部: universities/sample-yi-xue-bu.md
      - 中国地质大学北京: universities/cug-bj.md
      - 中国地质大学武汉: universities/cug-wh.md
"""

SCHOOL = """# {title}

> 数据来源：

<details><summary>点击展开</summary>
<ul>
<li>A10001: 匿名 (2024 年 06 月)</li>
<li>A10002: 匿名 (2025 年 06 月)</li>
</ul>
</details>

## Q: 教室和宿舍有没有空调？

- A10001: 有空调

- A10002: 没有空调

## Q: 每天断电断网吗，几点开始断？

- A10001: 不断电

- A10002: 部分宿舍会断

## 自由补充部分

A10001: 补充一句
"""


def build_fixture(root: Path) -> None:
    (root / "universities").mkdir(parents=True, exist_ok=True)
    (root / "archived" / "universities").mkdir(parents=True, exist_ok=True)
    (root / "nav.txt").write_text(NAV, encoding="utf-8")
    (root / "archived" / "nav.txt").write_text("    - 北京:\n", encoding="utf-8")
    files = {
        "sample.md": "示例科技大学",
        "sample-yi-xue-bu.md": "示例科技大学医学部",
        "cug-bj.md": "中国地质大学北京",
        "cug-wh.md": "中国地质大学武汉",
    }
    for f, title in files.items():
        (root / "universities" / f).write_text(
            SCHOOL.format(title=title), encoding="utf-8")


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        build_fixture(cls.root)
        cls._old_data = build_db.DATA
        cls._old_merge = dict(build_db.MERGED_ENTRIES)
        build_db.DATA = cls.root
        build_db.MERGED_ENTRIES = {}  # 迷你数据集不攬真实归并条目
        cls.db = cls.root / "index.sqlite"
        build_db.build(cls.db)
        cls.conn = query.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        build_db.DATA = cls._old_data
        build_db.MERGED_ENTRIES = cls._old_merge
        cls.tmp.cleanup()


class TestResolve(Fixture):
    def test_alias_resolves_uniquely(self):
        # 「示例科技大学」去后缀派生的「示例科技」是唯一别名
        hits, ambiguous = query.resolve(self.conn, "示例科技")
        self.assertEqual(ambiguous, [])
        self.assertEqual(hits[0]["name"], "示例科技大学")

    def test_full_name_prefers_exact(self):
        hits, ambiguous = query.resolve(self.conn, "示例科技大学")
        self.assertEqual(ambiguous, [])
        self.assertEqual(hits[0]["name"], "示例科技大学")

    def test_prefix_query_shows_longer_candidates(self):
        # 「示例科技大学」同时是「…医学部」的前缀：全名全等优先，其余作提示
        hits, _ = query.resolve(self.conn, "示例科技大学")
        self.assertEqual(hits[0]["name"], "示例科技大学")
        self.assertIn("示例科技大学医学部", [h["name"] for h in hits[1:]])

    def test_ambiguous_abbreviation_lists_candidates(self):
        hits, ambiguous = query.resolve(self.conn, "地大")
        self.assertEqual(hits, [])
        self.assertEqual(set(ambiguous),
                         {"中国地质大学北京", "中国地质大学武汉"})

    def test_unknown_returns_empty(self):
        hits, ambiguous = query.resolve(self.conn, "不存在的大学")
        self.assertEqual((hits, ambiguous), ([], []))


class TestMatchQids(Fixture):
    def test_number_maps_exactly(self):
        self.assertEqual(query.match_qids("12"), [12])

    def test_out_of_range_is_none(self):
        self.assertIsNone(query.match_qids("0"))
        self.assertIsNone(query.match_qids("99"))

    def test_keyword_routes_to_question(self):
        qids = query.match_qids("断电")
        self.assertIn(12, qids)

    def test_all_returns_25(self):
        self.assertEqual(len(query.match_qids("all")), 25)

    def test_unmatched_keyword_is_none(self):
        self.assertIsNone(query.match_qids("一个不存在的维度词"))


class TestSummarizeRender(Fixture):
    def test_polarity_counts_and_years(self):
        rows = query.fetch_answers(self.conn, 1, 2)  # 空调题
        s = query.summarize(rows)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["counts"], {"no": 1, "yes": 1})
        self.assertEqual(s["years"], {"2024": 1, "2025": 1})

    def test_render_shows_decision_rule(self):
        rows = query.fetch_answers(self.conn, 1, 2)
        out = query.render_question(2, rows, 5, ("yes", "no"))
        self.assertIn("判定口径", out)
        self.assertIn("有空调", out)
        self.assertIn("A10001", out)

    def test_freeform_has_no_verdict(self):
        rows = query.fetch_answers(self.conn, 1, 0)
        out = query.render_question(0, rows, 5, ("unknown",))
        self.assertNotIn("判定口径", out)


class TestCliSmoke(unittest.TestCase):
    """真实库上的只读冒烟；库不存在（如纯源码环境）时跳过。"""

    DB = ROOT / "data" / "index.sqlite"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOLS / "query.py"), *args],
            capture_output=True, text=True, cwd=ROOT)

    def setUp(self):
        if not self.DB.exists():
            self.skipTest("data/index.sqlite 不存在")

    def test_selftest_exit_zero(self):
        proc = self._run("--selftest")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("通过", proc.stdout)

    def test_single_school_query(self):
        proc = self._run("北邮", "--q", "断电", "--limit", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("北京邮电大学", proc.stdout)
        self.assertIn("判定口径", proc.stdout)

    def test_json_output(self):
        proc = self._run("北邮", "--q", "2", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"questions"', proc.stdout)

    def test_unknown_school_exit_two(self):
        proc = self._run("这所学校一定不存在大学", "--q", "2")
        self.assertEqual(proc.returncode, 2)

    def test_ambiguous_nickname_exit_two(self):
        proc = self._run("地大", "--q", "2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("中国地质大学", proc.stderr)

    def test_out_of_range_qid_exit_two(self):
        proc = self._run("北邮", "--q", "99")
        self.assertEqual(proc.returncode, 2)

    def test_reverse_filter(self):
        proc = self._run("--reverse", "断电", "--polarity", "no", "--limit", "3")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("反向筛选", proc.stdout)
        self.assertIn("| 学校 |", proc.stdout)

    def test_compare_two_schools(self):
        proc = self._run("--compare", "北邮", "华科", "--q", "空调", "--limit", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("北京邮电大学", proc.stdout)
        self.assertIn("华中科技大学", proc.stdout)

    def test_province_listing(self):
        proc = self._run("--province", "海南")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("所学校", proc.stdout)

    def test_sources_listing(self):
        proc = self._run("--sources", "北邮")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("回答者", proc.stdout)


class TestPolarityRegression(unittest.TestCase):
    def test_selftest_cases_all_pass(self):
        bad = [(qid, t, w) for qid, t, w in polarity.SELFTEST_CASES
               if polarity.classify(t, polarity.spec_for_qid(qid)) != w]
        self.assertEqual(bad, [], f"极性回归失败：{bad}")


if __name__ == "__main__":
    unittest.main()
