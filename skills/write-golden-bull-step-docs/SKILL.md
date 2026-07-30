---
name: write-golden-bull-step-docs
description: Maintain and audit project-local Word step instructions for Golden Bull Award workspaces by deriving inputs, outputs, external data sources, manual actions, failure handling, and code links from the current workspace code. Use when Codex is asked to create, rewrite, update, standardize, or review 金牛奖步骤说明、原始数据说明、评分排名说明、流程总览 or similar DOCX documentation across GB_BrokerAM, GB_PriFund, or other Golden Bull projects.
---

# Write Golden Bull Step Docs

Update only the selected workspace documents. Exclude every path containing `资料` unless the user explicitly includes it. Edit existing DOCX files in place unless the user asks for new files.

## Required companion skill

Use the available DOCX/document skill for editing and render verification. Follow its render-inspect-iterate gate. If no renderer works, perform the structural audit below and disclose the missing visual QA.

## Workflow

1. Identify the workspace root and evaluation year mechanism. Use `{YR}` in prose; do not use a concrete year as an example unless requested.
2. Inventory step DOCX files outside `资料`.
3. Match each instruction to the next numbered code file in the same folder. If one instruction covers a chained pair such as `1_计算.py` and `2_排名.py`, document both and state their order.
4. Read the full corresponding code or all relevant notebook code cells. Also trace shared CFG, database helpers, path resolvers, and downstream consumers that materially affect the step.
5. Record evidence before editing:
   - inputs and lookup priority;
   - exact filenames, sheets, columns, aliases, units, and formats;
   - outputs and retained formats;
   - manual actions before and after execution;
   - missing-file behavior and error messages;
   - screening versus scoring semantics;
   - code and genuine external-source links.
6. Read [content-standard.md](references/content-standard.md), then update the DOCX in place.
7. Run the author self-review and the independent audit pass below. Fix every blocking finding.
8. Render every final DOCX and inspect all pages. Do not deliver intermediate PNG/PDF files unless requested.

## Writing rules

- Lead with the step purpose and corresponding code.
- Use action-oriented headings, not phrases such as “手把手”.
- Default to the compact operator-guide style defined in [content-standard.md](references/content-standard.md): dark-blue title with a restrained rule, muted code subtitle, blue heading ladder, concise body paragraphs, and light warning/key-conclusion callouts.
- Make headings visibly hierarchical: title 18–20 pt bold, heading 1 about 15–16 pt bold, heading 2 about 12.5–14 pt bold, body about 10.5–11 pt. Increase subheading size and weight enough that scanning does not depend on numbering alone.
- Prefer a continuous 2–5 page operating guide over a decorative cover page. Keep page one immediately useful: title, corresponding code, purpose, and the most important data/business conclusion.
- Use tables only for genuinely repeated mappings or comparable records. Prefer labeled paragraphs for paths, processing rules, outputs, and troubleshooting.
- Put high-risk business or data distinctions in a restrained callout close to the relevant instruction. Examples include index-code identity, scale units, screening-versus-scoring semantics, and “do not substitute” warnings.
- Describe paths generically with `{YR}`. Link to code and true external websites. Do not add convenience links whose only purpose is opening `已处理/{YR}` or public-year folders.
- Make every hyperlink to project-local code or files relative to the DOCX directory. Store the relationship target with forward slashes and `TargetMode="External"` (for example, `1_计算.py` or `../../../userlib/configs/broker_am_config.py`). Never write `file:///` URIs, drive-letter paths, UNC paths, or workspace-absolute paths; HTTP(S) external-source links remain absolute.
- After saving, reopen the DOCX package and resolve each local relationship target against the DOCX directory. The resolved target must exist. Moving or copying the workspace must not leave a link pointing to the source workspace.
- Keep required storage paths in prose when they affect program lookup.
- Distinguish automatic work from manual work. State exactly what a person edits, where it is saved, how to confirm success, and what to do after a failure.
- Prefer exact field names and log messages over screenshots. Add screenshots only when they show current UI-only actions that cannot be expressed more reliably as text.
- Preserve user-authored notes unless contradicted by current code; reconcile conflicts explicitly.
- Do not invent data sources, sheets, columns, thresholds, or business meaning.

## Duplicate-control pass

Before saving, normalize each paragraph by removing numbering, punctuation, whitespace, and path-year variations. Merge paragraphs that express the same instruction. Keep detailed instructions in one section and replace later repetitions with a short cross-reference.

Do not repeat all of these in both overview and step documents. The overview owns sequence and cross-step gates; each step document owns file-level details and troubleshooting for that step.

## Audit side

Treat review as a separate pass from authoring:

1. Re-open the final DOCX from disk; do not review an in-memory draft.
2. Re-read the corresponding code and verify every filename, sheet, field, directory priority, and output.
3. Check that manual instructions are executable by a new operator without guessing.
4. Check that screening reasons are not incorrectly described as pre-score deletion when the code only annotates them.
5. Check for repeated paragraphs and contradictory lookup orders.
6. Inspect every hyperlink relationship. Project-local targets must be relative to the DOCX directory, use forward slashes, resolve to an existing file, and contain no `file:///`, drive letter, UNC prefix, or workspace-absolute path.
7. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".codex/skills/write-golden-bull-step-docs/scripts/audit_step_docs.ps1" -WorkspaceRoot "<workspace>"
```

The audit must report no blocking errors. Review warnings manually; do not silence them merely to pass.

8. Visually confirm the operator-guide hierarchy: title and subtitle are distinct; heading levels are obvious; callouts are not clipped; paths wrap cleanly; no heading is stranded at a page bottom; and no page is dominated by decorative whitespace.

## Completion report

Report which documents changed, the important content corrections, audit outcome, and render outcome. Link only to final DOCX deliverables. State clearly if visual rendering was unavailable.
