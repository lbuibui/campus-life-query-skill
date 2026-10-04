#!/usr/bin/env bash
# 本地一键校验：单元测试 + 极性回归 + 维护脚本幂等 + 数据完整性。
# CI（.github/workflows/ci.yml）跑同样的步骤；在提交前本地跑一遍可提前发现回归。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/6 单元测试 =="
python3 -m unittest discover -s tests

echo "== 2/6 极性回归样例 =="
python3 tools/query.py --selftest

echo "== 3/6 归并脚本幂等 =="
python3 tools/consolidate.py --check

echo "== 4/6 脱敏幂等 =="
python3 tools/redact.py --check

echo "== 5/6 别名表与索引修正 =="
python3 tools/build_aliases.py --check
python3 tools/patch_index.py --check

echo "== 6/6 数据完整性 =="
python3 tools/verify.py --quiet

echo "== 全部通过 =="
