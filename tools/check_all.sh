#!/usr/bin/env bash
# 本地一键校验：单元测试 + 极性回归 + 索引与数据一致性。
# CI（.github/workflows/ci.yml）跑同样的步骤；在提交前本地跑一遍可提前发现回归。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/4 单元测试 =="
python3 -m unittest discover -s tests

echo "== 2/4 极性回归样例 =="
python3 tools/query.py --selftest

echo "== 3/4 索引与镜像一致（重建比对内容摘要）=="
python3 tools/build_db.py --check

echo "== 4/4 数据库完整性 =="
python3 tools/verify.py --quiet

echo "== 全部通过 =="
