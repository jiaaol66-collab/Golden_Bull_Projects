# Content standard

## Document structure

Use the smallest structure that makes the step executable:

1. Title
2. Corresponding-code subtitle
3. Purpose and key conclusion
4. External data preparation, if any
5. Inputs and lookup priority
6. Automatic processing
7. Database/file outputs
8. Manual run procedure
9. Common failures and recovery
10. Pre-run or post-run audit checklist

Omit sections that truly do not apply. Do not leave empty headings.

## Default operator-guide style

Use this style for step-level operating instructions unless the existing document has a deliberate, stronger house style.

- Page: portrait, balanced margins, no standalone decorative cover.
- Title: 18–20 pt bold, dark navy, followed by one restrained blue rule.
- Subtitle: 10–11 pt muted gray, naming the exact corresponding code and the step's scope.
- Heading 1: 15–16 pt bold blue with generous space before and compact space after.
- Heading 2: 12.5–14 pt bold dark blue. It must be visibly subordinate to Heading 1 but clearly larger/heavier than body text.
- Body: 10.5–11 pt, about 1.2–1.25 line spacing, short action-oriented paragraphs.
- Key conclusion: light blue callout with dark-blue bold text.
- Blocking warning: light red or pale amber callout with restrained dark warning text. State both the prohibited substitution/action and its consequence.
- Paths and identifiers: preserve exact spelling and separators; let long paths wrap naturally rather than shrinking the entire document.
- Tables: avoid for prose. Use only for repeated field mappings, lookup priority matrices, or other true row/column comparisons.
- Footer/header: quiet or absent. Do not add decorative furniture that competes with the operating content.

The opening section should answer, without searching: what the step does, which code it documents, and the most important business/data distinction. For example, when several similar market indices exist, state the correct code and explicitly reject the confusable code next to the input requirement.

Prefer these reusable section labels when applicable:

- 步骤作用
- 外部数据准备
- 文件搜索顺序
- 处理逻辑
- 数据库输出 / 文件输出
- 运行方法
- 常见问题
- 运行前审核 / 结果审核

These labels are a menu, not a mandatory template. Omit irrelevant sections and merge very short adjacent sections.

## Evidence checklist

For every external or manually maintained file, verify from code:

- canonical filename and accepted aliases;
- search directories in actual order;
- Parquet versus Excel priority;
- sheet name, `skiprows`, `usecols`, and required columns;
- date range, units, numeric representation, and null behavior;
- behavior when absent;
- behavior when present but malformed;
- destination and whether the program copies, converts, or only reads it.

For every output, verify:

- exact location and filename pattern;
- file format and sheet naming;
- whether it is intermediate, human-review, screening evidence, or final delivery;
- whether downstream visualization or comparison reads it.

## Manual-action standard

Write manual actions as a closed loop:

1. prerequisite;
2. file to open;
3. field or worksheet to inspect;
4. permitted edit;
5. save location;
6. rerun point;
7. success signal;
8. escalation path if still failing.

Avoid vague instructions such as “检查一下”“按需处理” or “修改错误” without naming the evidence and acceptance condition.

## Golden Bull semantics

- Keep quantitative scoring separate from later business inclusion decisions.
- If scale, product count, liquidation, missingness, or other rules are annotations in current code, document them as reasons/notes rather than silent deletion.
- Explain whether a blank rank means not ranked, missing source data, failed matching, or a later inclusion decision.
- Treat CFG as authoritative when code resolves weights, names, thresholds, and year profiles through CFG.

## De-duplication rubric

Two paragraphs are duplicates when they have the same operator action and acceptance condition even if filenames contain different years or wording differs.

Keep the version that is:

- closest to the relevant heading;
- most exact about files and fields;
- explicit about success/failure;
- consistent with current code.

The overview may mention a manual gate once. The step document contains the detailed procedure. Do not copy the detailed procedure into the overview.

## Blocking review findings

- concrete year used as a supposedly reusable example;
- placeholder content;
- broken DOCX/OOXML;
- missing corresponding-code link or nonexistent code target;
- invented or outdated external source details;
- wrong search order or format priority;
- duplicated paragraphs that can cause conflicting actions;
- instructions to edit `资料` when only workspace code/documents are in scope;
- wording that filters an entity before scoring when current logic only appends a reason.

## Visual review warnings

Treat these as warnings that must be reviewed manually even when structural audit passes:

- title, subtitle, and Heading 1 look nearly identical;
- Heading 2 is indistinguishable from body text;
- a critical code/field distinction appears only in ordinary prose rather than near the relevant action;
- a path or filename is clipped, shrunk excessively, or split into an unreadable table cell;
- a heading is stranded at the bottom of a page;
- large blank areas are caused by decorative layout rather than content flow;
- multiple adjacent tables package ordinary prose.
