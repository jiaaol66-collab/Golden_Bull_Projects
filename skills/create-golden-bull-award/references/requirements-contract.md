# Requirements contract

Use this contract before selecting folders, steps, or code.

## Authority order

Apply evidence in this order:

1. The caller's current written instructions.
2. Current scheme, application workbook, data dictionary, and case files named
   by the caller.
3. Current scheduler and workspace code.
4. A named reference award, limited to the specific aspect the caller asked to
   reuse.
5. General Golden Bull conventions.

Lower-ranked evidence cannot override higher-ranked evidence.

## Translate instructions into a build contract

Record these items before editing:

- user-facing award label;
- stable project folder name;
- evaluation year and workspace naming convention;
- exact ordered steps;
- which reference award is used and for what;
- supplied source-material paths;
- raw-data status: available, partial, or waiting;
- confirmed scheme facts;
- unresolved business rules;
- requested stopping point: structure only, setup, initial code, documents, or
  full execution.

Use the smallest workflow that satisfies the contract.

## Reference-award boundary

Examples:

- "原始数据结构参考分析师、券商资管" permits inspecting and adapting their
  project-level raw-data folders and year partitioning.
- It does not permit copying their cleaning, scoring, visualization, review, or
  publication steps.
- "文件结构类似" is still subordinate to an explicit step list from the caller.
- If the caller gives `step_0` through `step_3`, do not create `step_4`.

State the chosen boundary in the award design note.

## Scheme evidence

Extract exact:

- award and category names;
- target entity and submission unit;
- quantitative fields and units;
- qualitative dimensions;
- weights that are explicitly stated;
- eligibility or disqualification wording;
- expert-review and manual-review actions;
- output or publication requirements.

Keep contradictions verbatim. Common contradictions include scheme category
names not matching application-workbook sheet names.

## Assumptions

Make an assumption only when it:

- is reversible;
- does not change the requested workflow;
- does not create a business rule;
- is labeled in the design note.

Safe assumptions include an ASCII project-folder name or a temporary waiting
folder. Unsafe assumptions include score direction, standardization method,
missing-value substitution, award quota, or ranking tie-breaks.

## Stopping rules

Stop before producing:

- cleaned records when real input structure is unknown;
- scores when formula details are unresolved;
- rankings or winner lists from draft weights;
- scheduler entries whose label/folder mapping cannot be verified.

Prefer a useful gate artifact: file inventory, rule-status JSON, pending-items
list, or explicit receipt note.
