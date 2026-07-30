---
name: create-golden-bull-award
description: Create or extend a Golden Bull Award project from the caller's written workflow, supplied scheme documents, application workbooks, case files, and explicitly named reference awards. Use when Codex is asked to add a new 金牛奖奖项, register it in the scheduler, design its project and raw-data storage structure, build a workspace blueprint, run setup.py, draft step code from the current default_code.py, add safe data/scoring gates, or prepare initial step DOCX instructions.
---

# Create Golden Bull Award

Build a runnable, reviewable award workspace without assuming that one award's
step structure applies to another.

## Governing rules

1. Treat the caller's written description as the authority for workflow, step
   count, names, and scope.
2. Use reference awards only for the aspect the caller names. If the caller
   says "原始数据结构参考分析师、券商资管", copy only that storage pattern;
   do not copy their processing steps.
3. Inspect the current project before designing anything. Never rely on a
   remembered scheduler flow, workbook schema, or default template.
4. Derive every step Python file from the current
   `_必备代码/_默认代码/default_code.py`. Insert award-specific logic into the
   template body; preserve its bootstrap and closing conventions.
5. Do not invent scoring rules. Encode confirmed facts and make unresolved
   items explicit blocking gates.
6. Build one award for user review before turning a specific example into a
   more specialized skill or template.

Read [requirements-contract.md](references/requirements-contract.md) before
choosing the step structure. Read
[workspace-blueprint.md](references/workspace-blueprint.md) before creating or
editing `文件结构.xlsx`.

## Workflow

### 1. Establish scope

- Resolve the project root and scheduler entry point.
- Inventory the supplied scheme, application table, data dictionary, prior
  case, and any named reference awards.
- Extract confirmed award names, target entities, fields, units, weights,
  qualitative dimensions, submission channel, and known manual actions.
- Record contradictions separately. A contradiction is a gate, not permission
  to choose a convenient interpretation.
- Translate the caller's text into an exact ordered step list. Do not add
  scoring, visualization, publication, or feedback steps unless requested or
  required by inspected code.

### 2. Register the award

- Inspect `award_config.py` and the scheduler code that consumes it.
- Add the smallest new config entry that matches existing schema.
- Use a stable ASCII project folder name and the user-facing Chinese award
  label expected by the scheduler.
- Validate config import and award resolution before creating the workspace.

### 3. Create project-level storage

- Create the award project folder, year-scoped scheme-material folder, and
  raw-data root.
- Preserve supplied source files unchanged.
- When data is not available, create an explicit waiting location and a short
  receipt note; do not manufacture sample submissions.
- Keep source materials out of the raw-submission directory.

### 4. Build the workspace blueprint

- Use the `spreadsheets` skill to create or edit
  `资料/代码/工作区设置/文件结构.xlsx`.
- Follow the exact steps derived from the caller's text.
- Add only the shared folders and files that downstream code actually uses.
- Map source names under `资料` to deployed names under each `step_N_...`
  folder.
- Validate sheet names, required columns, run order, duplicate destinations,
  and source-file existence before setup.

### 5. Run setup and inspect deployment

- Run the workspace `setup.py`.
- Confirm every requested step directory exists and no unrequested step was
  created.
- Confirm code, DOCX instructions, `run.bat`, and any template-required helper
  such as `flush_buffer.py` were deployed.
- Re-run setup once to verify idempotence. Existing reviewed files must not be
  silently overwritten.

### 6. Draft code from the live default template

- Write only the award-specific body into a temporary UTF-8 Python file.
- Run `scripts/rebase_step_script.py` with the live `default_code.py`, the body,
  and every source/deployed output path.
- Keep the `资料/代码` source and deployed step file byte-identical.
- Use `find_rel`, `get_year`, `insert_bookmark`, `重要文件`, `原始数据集`, and
  the template's output/copy conventions instead of standalone path logic.
- For missing data, emit traceable inventories or clear diagnostics and stop
  before fabricating cleaned data.
- For unresolved scoring, store a status file with confirmed facts and
  `pending_items`; exit nonzero before any score, rank, or winner output.

### 7. Write initial step instructions by calling another skill

Use the available `write-golden-bull-step-docs` skill after the deployed code
exists. That skill must inspect the actual code and create or update the
workspace DOCX instructions. Also use its required document skill and
render/audit gate.

The first documentation pass may be concise, but it must state:

- the corresponding code;
- purpose, inputs, lookup behavior, and outputs;
- confirmed scheme facts;
- automatic versus manual actions;
- empty-data and failure behavior;
- unresolved cleaning or scoring rules.

### 8. Validate

Run:

```powershell
python skills/create-golden-bull-award/scripts/verify_award_workspace.py `
  --project-root "<project-root>" `
  --workspace "<workspace>" `
  --default-code "<project-root>/_必备代码/_默认代码/default_code.py" `
  --step "资料/代码/1_data_extraction.py|step_1_数据提取/1_数据提取.py"
```

Repeat `--step` for each source/deployed pair.

Also verify:

- scheduler config imports;
- blueprint manifest matches the caller's steps exactly;
- setup completes and is idempotent;
- source/deployed scripts compile and match;
- empty data does not create fake clean data;
- unresolved scoring does not create results;
- final DOCX audit has no blocking errors.

## Completion report

Report the scheduler label, project folder, workspace path, exact step list,
setup outcome, code test outcomes, document audit/render outcome, and every
remaining business-rule gate. Link the deployed scripts and final DOCX files.
