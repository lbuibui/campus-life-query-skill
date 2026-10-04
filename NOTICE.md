# NOTICE

This project contains adapted material from the following open-source dataset:

## Original data source

- Project: CollegesChat / university-information
- Repository: https://github.com/CollegesChat/university-information
- Generated data branch: https://github.com/CollegesChat/university-information/tree/generated
- License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International, CC BY-NC-SA 4.0

The university life quality data in `data/` is derived from and adapted from the above project.

## Modifications

This repository reorganizes and adapts the original dataset for use as an Agent Skill, including:

- creating `SKILL.md` as the Agent instruction entry point;
- mirroring the upstream `generated` branch data into `data/` (`universities/`,
  `archived/universities/` and the two `nav.txt` navigation files) **as-is**, byte for
  byte — including the upstream's own quirks (misplaced entries, sentence-like school
  names, missing free-form sections, missing trailing newlines), which are kept rather
  than rewritten so provenance stays diffable against upstream;
- adding `data/index.sqlite`, a query index built from the mirror by
  `tools/build_db.py`: schools (name / province / file / active-or-archived), the 25
  canonical questions, every answer with its questionnaire ID and submission date, the
  data-source lists, the free-form supplements, and an alias table. The build is
  deterministic (fixed insertion order, no wall-clock values), so repeated builds
  produce byte-identical databases; `tools/build_db.py --check` rebuilds and compares
  a content digest that is independent of the sqlite version;
- **building the polarity classifier into the index**: every answer is classified at
  build time as `yes / no / mixed / unknown` against a per-question semantic spec
  (`tools/polarity.py`), instead of a single question-agnostic keyword lexicon that
  misread negations ("不断电" as an affirmation of "断电"), affirm-vs-negate pairs
  ("不贵" as "贵"; "是上下铺" as "是"), and quality questions. The classifier strips
  negated spans before testing affirmative ones and biases a wrong answer towards
  `unknown` rather than a confident mistake; `tools/query.py --selftest` prints its
  regression samples and each query result prints the decision rule it used;
- adding `tools/query.py`, the single structured-query entry point (single school,
  cross-school comparison, province browsing, data-source listing, and reverse
  filtering such as "which schools do not cut power at night"), which aggregates
  results per school when a keyword matches several questions and reports unique
  school counts rather than inflated row counts;
- adding an alias / abbreviation / former-name lookup (`tools/alias_seed.py`, a
  hand-maintained seed table plus suffix-stripping derivation, stored in the
  `aliases` table). The generator guarantees that no alias equals another real
  school's full name, so a nickname can never hijack a full-name query; nicknames
  that genuinely point at several schools (`地大`, `华师`, `华农`, `中国地质大学`,
  `中国石油大学`) are stored as multi-row ambiguous aliases and `tools/query.py`
  lists the candidates and exits instead of guessing;
- merging one misplaced upstream entry at index-build time: a file named after a
  school-rename note (questionnaire respondent `A33177`, 2026-02, 25 answers plus a
  free-form supplement) is attributed to 广东轻工职业技术大学 in the query index.
  The data file itself is not modified;
- adding `tools/verify.py`, a database-integrity regression check (referential
  consistency, inventory parity with `nav.txt` and the filesystem, content-digest
  drift, alias hijack protection, per-school question coverage), plus `tests/` and
  `.github/workflows/ci.yml` (unit tests on Python 3.10-3.13, a pytest run, and a
  data-integrity job).

Data last refreshed from upstream on 2026-09-19 (generated branch `0abf14dfc897`,
commit date 2026-09-19). Includes both active data (3,448 schools, responses from
2023-2026) and archived data (2,705 schools, responses from 2021-2022, i.e. submitted
before 2023-01-01).

## Privacy

`data/` mirrors the upstream generated data **unchanged**, including the identifiers
that questionnaire respondents voluntarily left in the "数据来源" (`<li>`) lists at the
top of each school file and in their answer bodies / free-form supplements (mostly
e-mail addresses, occasionally phone numbers, QQ / WeChat / Telegram handles, and in a
few cases base64-encoded contact details). This repository does not redact or
pseudonymize them, so that the mirror stays byte-identical to upstream and remains
diffable for future syncs.

If you are the author of an upstream questionnaire response and want your entry
removed or anonymized, please open an issue here or report it upstream to
CollegesChat/university-information.

## License inheritance

Because the underlying university-information dataset is licensed under CC BY-NC-SA 4.0, this repository is also released under CC BY-NC-SA 4.0. The `LICENSE` file is copied from the upstream generated branch's full license text.

You may share and adapt this repository for non-commercial purposes, provided that attribution is preserved and derivative works are shared under the same or a compatible license.

## Disclaimer

The data is not official university information. It is based on anonymous student responses and may contain subjective, outdated, conflicting, or campus-specific experiences. Please use it as reference only.
