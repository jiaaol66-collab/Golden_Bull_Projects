(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const state = {
    connected: false,
    demo: false,
    snapshot: null,
    view: "overview",
    dataFilter: "output",
    attemptScope: "unarchived",
    logLevel: "all",
    selectedSteps: new Set(),
    selectedStepsWorkspaceId: "",
    selectedStepsDirty: false,
    selectedAttemptId: "",
    selectedWorkspaceId: "",
    pendingWorkspaceId: "",
    awardFilter: "",
    yearFilter: "",
    selectionInitialized: false,
    sessionLoaded: false,
    loadingWorkspaceId: "",
    switchingWorkspaceId: "",
    workspaceRunBusy: new Set(),
    floatingOnly: false,
    timelineRequestToken: 0,
    timelineSignature: "",
    tickBase: performance.now(),
    logLines: [],
    logStreamKey: "",
    serverLogSignatures: [],
    snapshotLogLines: [],
    logClearWatermarks: new Map(),
    logFollowPausedUntil: 0,
    logFollowTimer: null,
    logPointerActive: false,
    manualCodes: [],
    manualCodeWorkspaceId: "",
    manualCodeRunning: false,
    resourceConfig: null,
    resourceConfigWorkspaceId: "",
    resourceConfigBusyKind: "",
    resourceConfigMessage: "",
    resourceConfigError: false,
    resourceConfigRequestToken: 0,
    resourceActionBusy: "",
    pollTimer: null
  };

  const STATUS = {
    idle: { label: "空闲", icon: "·" },
    waiting: { label: "等待", icon: "·" },
    running: { label: "运行中", icon: "▶" },
    done: { label: "已完成", icon: "✓" },
    success: { label: "成功", icon: "✓" },
    failed: { label: "失败", icon: "!" },
    error: { label: "失败", icon: "!" },
    cancelled: { label: "已暂停", icon: "■" },
    skipped: { label: "已跳过", icon: "–" }
  };

  const demoSnapshot = {
    mode: "demo",
    updated_at: new Date().toISOString(),
    awards: ["私募金牛奖", "公募金牛奖", "券商分析师"],
    years: ["2026", "2025"],
    workspaces: [
      { id: "pri-2026", name: "私募金牛 · 周度评选", award: "私募金牛奖", year: "2026", created_at: "2026-08-10T10:00:00+08:00" },
      { id: "analyst-2026", name: "分析师评选工作区", award: "券商分析师", year: "2026", created_at: "2026-08-09T10:00:00+08:00" }
    ],
    loaded_workspaces: ["pri-2026", "analyst-2026"],
    workspace_summaries: [
      { id: "pri-2026", name: "私募金牛 · 周度评选", award: "私募金牛奖", year: "2026", status: "running", current_step_name: "整合参评信息", elapsed_seconds: 1213 },
      { id: "analyst-2026", name: "分析师评选工作区", award: "券商分析师", year: "2026", status: "idle", current_step_name: "等待运行", elapsed_seconds: 0 }
    ],
    selection_context: { award: "私募金牛奖", year: "2026", workspace_id: "pri-2026" },
    parallel_capability: { supported: true, caution: "不同工作区可并行；共享数据资源时请谨慎" },
    active_workspace_id: "pri-2026",
    workspace: { id: "pri-2026", name: "私募金牛 · 周度评选", display_name: "私募金牛 · 周度评选", award: "私募金牛奖", year: "2026", path: "GB_PriFund/2026工作区" },
    run: { status: "running", attempt_id: "demo-260810", attempt_name: "第 4 次尝试", total_elapsed_seconds: 1213, main_elapsed_seconds: 1041, current_step_elapsed_seconds: 188, completed_steps: 3, total_steps: 7, async_running: 1, async_total: 2 },
    steps: [
      { order: 0, name: "部署工作区", path: "step_0 / inherit.py", status: "done", selected: true, duration_seconds: 16 },
      { order: 1, name: "数据提取", path: "step_1 / 1_数据提取.py", status: "done", selected: true, duration_seconds: 386 },
      { order: 2, name: "数据清洗", path: "step_2 / 2_数据清洗.py", status: "done", selected: true, duration_seconds: 451 },
      { order: 3, name: "整合参评信息", path: "step_3 / 3_整合信息.py", status: "running", selected: true, duration_seconds: 188 },
      { order: 4, name: "计算准备", path: "step_4 / 4_计算准备.py", status: "waiting", selected: true, duration_seconds: 0 },
      { order: 5, name: "奖项计算", path: "step_5 / 5_奖项计算.py", status: "waiting", selected: true, duration_seconds: 0 },
      { order: 6, name: "输出结果", path: "step_6 / 6_输出结果.py", status: "waiting", selected: true, duration_seconds: 0 }
    ],
    timeline: [
      { label: "数据提取", axis: "main", status: "done", start: 0, duration: 18 },
      { label: "数据清洗", axis: "main", status: "done", start: 20, duration: 24 },
      { label: "整合参评信息", axis: "main", status: "running", start: 47, duration: 22 },
      { label: "净值检查", axis: "async", status: "done", start: 23, duration: 17 },
      { label: "历史数据查询", axis: "async", status: "running", start: 50, duration: 32 }
    ],
    logs: [
      { ts: "10:27:18", level: "info", source: "terminal", message: "已挂载工作区：私募金牛 · 周度评选" },
      { ts: "10:27:34", level: "info", source: "step_1", message: "数据提取完成，共读取 227 个产品" },
      { ts: "10:34:01", level: "info", source: "step_2", message: "数据清洗完成，开始整合参评信息" },
      { ts: "10:42:08", level: "warning", source: "async", message: "历史数据查询仍在运行，不计入主步骤链时间" },
      { ts: "10:44:16", level: "info", source: "step_3", message: "正在合并管理人和策略分类信息…" }
    ],
    files: {
      output: [{ name: "私募金牛产品-top1000汇总.xlsx", kind: "XLSX", path: "输出 / 私募金牛产品-top1000汇总.xlsx", modified: "今天 10:41", size: "4.8 MB" }, { name: "入围产品明细.xlsx", kind: "XLSX", path: "输出 / 入围产品明细.xlsx", modified: "今天 10:39", size: "2.1 MB" }],
      processed: [{ name: "产品净值清洗.parquet", kind: "DATA", path: "已处理 / 产品净值清洗.parquet", modified: "今天 10:34", size: "18.6 MB" }, { name: "管理人信息.xlsx", kind: "XLSX", path: "已处理 / 管理人信息.xlsx", modified: "今天 10:36", size: "985 KB" }],
      important: [{ name: "参评名单.xlsx", kind: "XLSX", path: "资料 / 重要文件 / 参评名单.xlsx", modified: "昨天 16:20", size: "176 KB" }],
      database: [{ name: "wind_private_fund.duckdb", kind: "DB", path: "数据库 / wind_private_fund.duckdb", modified: "今天 09:51", size: "1.4 GB" }]
    },
    resources: [
      { title: "评奖规则", description: "当前奖项和年份绑定的规则文件", path: "GB_PriFund/原始数据集/2026/2026私募金牛评奖规则.docx", status: "已连接", action: "select-rule" },
      { title: "原始数据集", description: "Terminal 管理的本轮数据源目录", path: "GB_PriFund/原始数据集", status: "已连接", action: "select-dataset" },
      { title: "私募年度参数", description: "当前奖项的年度计算参数配置", path: "userlib/configs/prifund_config.py", status: "可编辑", action: "open-configs" }
    ],
    results: [{ name: "私募金牛产品-top1000汇总.xlsx", kind: "XLSX", path: "计算结果 / Top1000", modified: "今天 10:41", size: "4.8 MB" }, { name: "机构评分结果.xlsx", kind: "XLSX", path: "计算结果 / 机构", modified: "今天 10:40", size: "1.3 MB" }, { name: "策略分类统计.xlsx", kind: "XLSX", path: "计算结果 / 统计", modified: "今天 10:38", size: "820 KB" }],
    attempts: [
      { id: "demo-260810", name: "第 4 次尝试", status: "running", started_at: "2026-08-10 10:27:18", duration_seconds: 1213, main_steps: 4, async_steps: 2 },
      { id: "demo-260809", name: "完整流程验证", status: "success", started_at: "2026-08-09 15:08:44", duration_seconds: 2761, main_steps: 7, async_steps: 3 },
      { id: "demo-260808", name: "净值补录后重跑", status: "failed", started_at: "2026-08-08 11:40:03", duration_seconds: 832, main_steps: 3, async_steps: 1 }
    ]
  };

  function apiAvailable() { return Boolean(window.pywebview && window.pywebview.api); }
  async function callApi(method, payload) {
    if (!apiAvailable()) throw new Error("Python API 尚未连接");
    const fn = window.pywebview.api[method];
    if (typeof fn !== "function") throw new Error(`Python API 未实现：${method}`);
    return payload === undefined ? fn() : fn(payload);
  }
  async function safeAction(method, payload, successText) {
    if (state.demo) { toast(`演示模式：已触发 ${method}，未执行真实操作`); return null; }
    try {
      const result = await callApi(method, payload);
      if (result && result.ok === false) {
        toast(result.message || `${method} 执行失败`, true);
        return result;
      }
      if (result && result.message) toast(result.message);
      else if (successText) toast(successText);
      return result;
    } catch (error) { toast(error.message || String(error), true); return null; }
  }

  function normalizeSnapshot(raw) {
    const data = raw && raw.snapshot ? raw.snapshot : raw;
    if (!data || typeof data !== "object") throw new Error("内核返回的状态不是对象");
    data.run = data.run || {};
    data.workspace = data.workspace || {};
    data.steps = Array.isArray(data.steps) ? data.steps : [];
    data.timeline = Array.isArray(data.timeline) ? data.timeline : [];
    data.logs = Array.isArray(data.logs) ? data.logs : [];
    data.files = data.files || {};
    data.resources = Array.isArray(data.resources) ? data.resources : [];
    data.results = Array.isArray(data.results) ? data.results : [];
    data.attempts = Array.isArray(data.attempts) ? data.attempts : [];
    data.workspaces = Array.isArray(data.workspaces) ? data.workspaces : [];
    data.loaded_workspaces = Array.isArray(data.loaded_workspaces) ? data.loaded_workspaces : [];
    data.workspace_summaries = Array.isArray(data.workspace_summaries) ? data.workspace_summaries : [];
    data.selection_context = data.selection_context && typeof data.selection_context === "object" ? data.selection_context : {};
    return data;
  }

  async function connect() {
    if (!apiAvailable()) return useDemo("未检测到 pywebview API");
    try {
      const bootstrap = await callApi("bootstrap");
      if (state.demo) {
        state.selectionInitialized = false;
        state.awardFilter = "";
        state.yearFilter = "";
        state.selectedWorkspaceId = "";
      }
      state.connected = true; state.demo = false; $("#demoPill").hidden = true;
      if (bootstrap.bridge && bootstrap.bridge.connected === false) {
        setConnection("online", "只读监视已连接", bootstrap.bridge.error || "检测到现有 Terminal，不重复启动内核");
      } else {
        setConnection("online", "调度内核已连接", "状态实时同步");
      }
      applySnapshot(normalizeSnapshot(bootstrap));
      schedulePoll();
    } catch (error) { useDemo(error.message || "Python API 连接失败"); }
  }
  function useDemo(reason) {
    state.connected = false; state.demo = true;
    // Explicit browser preview may explore the UI, but every write remains blocked by safeAction.
    if (new URLSearchParams(location.search).get("preview") === "1") state.sessionLoaded = true;
    $("#demoPill").hidden = false;
    setConnection("demo", "当前为演示数据", reason);
    applySnapshot(normalizeSnapshot(structuredCloneSafe(demoSnapshot)));
  }
  function structuredCloneSafe(value) { return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value)); }
  function setConnection(mode, title, detail) {
    const dot = $("#connectionDot"); dot.className = `connection-dot is-${mode}`;
    $("#connectionText").textContent = title; $("#connectionDetail").textContent = detail;
  }
  function schedulePoll() {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(async () => {
      try {
        const requestToken = state.timelineRequestToken;
        const polled = await callApi("get_state");
        if (requestToken === state.timelineRequestToken) applySnapshot(normalizeSnapshot(polled));
        if (polled.bridge && polled.bridge.connected === false) setConnection("online", "只读监视已连接", polled.bridge.error || "状态来自现有日志与尝试记录");
        else setConnection("online", "调度内核已连接", "状态实时同步");
      }
      catch (error) { setConnection("demo", "状态同步暂时中断", error.message || String(error)); }
      if (state.connected) schedulePoll();
    }, 1000);
  }

  function applySnapshot(snapshot) {
    const workspaceId = String(snapshot.workspace.id || snapshot.active_workspace_id || "");
    if (state.resourceConfigWorkspaceId && state.resourceConfigWorkspaceId !== workspaceId) closeResourceConfigModal(true);
    state.snapshot = snapshot;
    state.tickBase = performance.now();
    if (state.selectedStepsWorkspaceId !== workspaceId || !state.selectedStepsDirty) {
      state.selectedSteps = new Set(snapshot.steps.filter(s => s.selected !== false).map(s => String(s.order)));
      state.selectedStepsWorkspaceId = workspaceId;
    }
    if (state.pendingWorkspaceId && state.pendingWorkspaceId === workspaceId) state.pendingWorkspaceId = "";
    syncSnapshotLogs(snapshot.logs, `${workspaceId}::${String(snapshot.run.attempt_id || "")}`);
    renderSelectors(); renderLoadedWorkspaces(); renderHeader(); renderMetrics(); renderSteps(); renderNow(); renderTimeline(); renderFiles(); renderResources(); renderResults(); renderAttempts(); renderManagement(); renderLogs();
    updateWorkspaceGate();
    renderFloat(); renderOverview();
  }

  function renderOverview() {
    const s = state.snapshot, status = normalizeStatus(s.run.status);
    $("#overviewName").textContent = s.workspace.display_name || s.workspace.name || "等待加载工作区";
    $("#overviewContext").textContent = [s.workspace.award, s.workspace.year, status.label].filter(Boolean).join(" / ");
    const done = s.steps.filter(x => ["done", "success"].includes(String(x.status).toLowerCase())).length;
    const failed = s.steps.filter(x => ["failed", "error"].includes(String(x.status).toLowerCase())).length;
    const metrics = [["已加载工作区", s.loaded_workspaces.length, "本次会话"], ["已完成步骤", `${done} / ${s.steps.length}`, "当前工作区"], ["待处理异常", failed, failed ? "进入任务执行查看" : "当前步骤无失败记录"], ["结果文件", s.results.length, "已发现的计算产出"]];
    $("#overviewStats").innerHTML = metrics.map(([label, value, note], i) => `<article class="overview-stat"><span>${label}</span><strong class="${i === 2 && failed ? "attention-value" : ""}">${value}</strong><small>${note}</small></article>`).join("");
    const logs = state.logLines.slice(-4).reverse();
    $("#overviewActivity").innerHTML = `<div class="activity-status"><span class="mini-status is-${status.css}"><i></i>${status.label}</span><strong>${escapeHtml(currentStep()?.name || "暂无执行中的步骤")}</strong></div>` + (logs.length ? logs.map(x => `<div class="activity-item"><span class="activity-dot ${x.level === "error" ? "is-error" : ""}"></span><div><p>${escapeHtml(x.message || "")}</p><small>${escapeHtml(x.ts || "")} · ${escapeHtml(x.source || "运行日志")}</small></div></div>`).join("") : '<div class="empty-state">尚无运行记录。加载工作区后，可在任务执行页选择步骤。</div>');
  }

  function renderSelectors() {
    const s = state.snapshot;
    const allWorkspaces = workspaceCatalog(s);
    const awards = (Array.isArray(s.awards) && s.awards.length ? s.awards : unique(allWorkspaces.map(w => workspaceAwardLabel(w, [])))).map(String);
    const context = s.selection_context || {};
    if (!state.selectionInitialized) {
      const contextWorkspaceId = String(context.workspace_id || context.workspace?.id || "");
      const contextWorkspace = allWorkspaces.find(w => String(w.id) === contextWorkspaceId);
      state.awardFilter = String(context.award || contextWorkspace && workspaceAwardLabel(contextWorkspace, awards) || awards[0] || "");
      const contextYear = String(context.year || contextWorkspace && workspaceYear(contextWorkspace) || "");
      state.yearFilter = contextYear || latestYearForAward(allWorkspaces, state.awardFilter, awards);
      state.selectedWorkspaceId = contextWorkspaceId || String(latestWorkspaceForSelection(allWorkspaces, state.awardFilter, state.yearFilter, awards)?.id || "");
      state.selectionInitialized = true;
    }
    if (!awards.includes(String(state.awardFilter))) state.awardFilter = awards[0] || "";
    const years = workspaceYearsForAward(allWorkspaces, state.awardFilter, awards);
    if (!years.includes(String(state.yearFilter))) state.yearFilter = latestYearForAward(allWorkspaces, state.awardFilter, awards);
    syncSelectOptions($("#awardSelect"), awards.map(value => ({ value, label: value })), state.awardFilter);
    syncSelectOptions($("#yearSelect"), years.map(value => ({ value, label: value })), state.yearFilter);
    const workspaces = allWorkspaces.filter(w => workspaceAwardLabel(w, awards) === String(state.awardFilter) && workspaceYear(w) === String(state.yearFilter));
    const validWorkspaceIds = workspaces.map(w => String(w.id));
    let selectedId = String(state.pendingWorkspaceId || state.selectedWorkspaceId || "");
    if (!validWorkspaceIds.includes(selectedId)) selectedId = String(latestWorkspace(workspaces)?.id || "");
    if (!state.pendingWorkspaceId) state.selectedWorkspaceId = selectedId;
    const placeholder = workspaces.length ? "请选择工作区" : "暂无匹配工作区";
    syncSelectOptions($("#workspaceSelect"), [{ value: "", label: placeholder, disabled: true }, ...workspaces.map(w => ({ value: w.id, label: workspaceDisplayName(w), title: workspaceDisplayName(w) }))], selectedId);
    const selectedWorkspace = workspaces.find(w => String(w.id) === selectedId);
    $("#workspaceFullName").textContent = selectedWorkspace ? workspaceDisplayName(selectedWorkspace) : placeholder;
    $("#workspaceFullName").title = selectedWorkspace ? workspaceDisplayName(selectedWorkspace) : "";
    const loading = Boolean(state.loadingWorkspaceId);
    $("#loadWorkspaceButton").disabled = loading || !selectedId;
    $("#loadWorkspaceButton").textContent = loading ? "正在加载…" : (String(s.active_workspace_id || s.workspace.id || "") === selectedId && state.sessionLoaded ? "已加载 · 刷新" : "加载工作区");
  }
  function syncSelectOptions(el, items, selected) {
    const normalized = (items || []).map(item => ({ value: String(item.value ?? ""), label: String(item.label ?? item.value ?? ""), disabled: Boolean(item.disabled), title: String(item.title ?? item.label ?? "") }));
    const signature = JSON.stringify(normalized);
    if (el.dataset.optionsSignature !== signature) {
      el.innerHTML = "";
      normalized.forEach(item => { const option = new Option(item.label, item.value); option.disabled = item.disabled; option.title = item.title; el.add(option); });
      el.dataset.optionsSignature = signature;
    }
    if (normalized.some(item => item.value === String(selected ?? ""))) el.value = String(selected);
    el.title = normalized.find(item => item.value === el.value)?.title || "";
  }
  function unique(values) { return Array.from(new Set(values.filter(Boolean))); }
  function workspaceCatalog(snapshot) {
    const items = Array.isArray(snapshot.workspaces) ? snapshot.workspaces.slice() : [];
    const active = snapshot.workspace || {};
    if (active.id && !items.some(item => String(item.id) === String(active.id))) items.unshift(active);
    return items.filter(item => item && item.id);
  }
  function workspaceYearsForAward(workspaces, award, knownAwards) {
    return unique(workspaces.filter(w => workspaceAwardLabel(w, knownAwards) === String(award)).map(workspaceYear)).sort((a, b) => {
      const an = Number(a), bn = Number(b);
      if (Number.isFinite(an) && Number.isFinite(bn)) return bn - an;
      return String(b).localeCompare(String(a), "zh-CN", { numeric: true });
    });
  }
  function latestYearForAward(workspaces, award, knownAwards) { return workspaceYearsForAward(workspaces, award, knownAwards)[0] || ""; }
  function createdAtMillis(workspace) {
    const raw = workspace && workspace.created_at;
    if (raw === undefined || raw === null || raw === "") return NaN;
    const numeric = Number(raw);
    if (Number.isFinite(numeric) && numeric > 0) return numeric < 100000000000 ? numeric * 1000 : numeric;
    const parsed = Date.parse(String(raw));
    return Number.isFinite(parsed) ? parsed : NaN;
  }
  function latestWorkspace(workspaces) {
    const ordered = (workspaces || []).filter(Boolean);
    if (!ordered.length) return null;
    const times = ordered.map(createdAtMillis);
    if (times.some(time => !Number.isFinite(time))) return ordered[0];
    let best = ordered[0], bestTime = times[0];
    ordered.slice(1).forEach((candidate, index) => {
      const time = times[index + 1];
      if (time > bestTime) { best = candidate; bestTime = time; }
    });
    return best;
  }
  function latestWorkspaceForSelection(workspaces, award, year, knownAwards) {
    return latestWorkspace(workspaces.filter(w => workspaceAwardLabel(w, knownAwards) === String(award) && workspaceYear(w) === String(year)));
  }
  function workspaceDisplayName(workspace) { return String(workspace && (workspace.display_name || workspace.name) || "未命名工作区"); }
  function workspaceYear(workspace) {
    const explicit = String(workspace && workspace.year || "");
    if (explicit) return explicit;
    const match = workspaceDisplayName(workspace).match(/(?:19|20)\d{2}/);
    return match ? match[0] : "";
  }
  function workspaceAwardLabel(workspace, knownAwards) {
    const award = String(workspace && workspace.award || "").trim();
    if ((knownAwards || []).map(String).includes(award)) return award;
    const source = `${award} ${workspace && workspace.award_dir_name || ""} ${workspaceDisplayName(workspace)}`;
    if (/GB_PriFund|私募/i.test(source)) return "私募金牛奖";
    if (/GB_PubFund|公募/i.test(source)) return "公募金牛奖";
    if (/GB_BrokerAnalyst|GB_Analyst|分析师/i.test(source)) return "分析师金牛奖";
    if (/GB_BrokerAM|券商资管/i.test(source)) return "券商资管金牛奖";
    if (/GB_BrokerBranch|营业部/i.test(source)) return "证券公司金牛奖(营业部)";
    if (/GB_Test|测试/i.test(source)) return "测试流程";
    if (/银行理财/i.test(source) && /其他/i.test(source)) return "银行理财金牛奖(其他奖)";
    if (/GB_BankWM|银行理财/i.test(source)) return "银行理财金牛奖(产品奖)";
    return award;
  }
  function workspaceIdentity(item) { return String(item && (item.id || item.workspace_id) || ""); }
  function loadedWorkspaceSummaries(snapshot) {
    const catalog = workspaceCatalog(snapshot), catalogById = new Map(catalog.map(item => [workspaceIdentity(item), item]));
    const summaries = Array.isArray(snapshot.workspace_summaries) ? snapshot.workspace_summaries : [];
    const summariesById = new Map(summaries.map(item => [workspaceIdentity(item), item]));
    let source = Array.isArray(snapshot.loaded_workspaces) && snapshot.loaded_workspaces.length ? snapshot.loaded_workspaces : summaries;
    const activeId = String(snapshot.active_workspace_id || snapshot.workspace.id || ""), seen = new Set();
    if (!source.length && state.sessionLoaded && !state.floatingOnly && activeId) source = [activeId];
    return source.map(item => {
      const id = typeof item === "string" || typeof item === "number" ? String(item) : workspaceIdentity(item);
      if (!id || seen.has(id)) return null;
      seen.add(id);
      const merged = { ...(catalogById.get(id) || {}), ...(summariesById.get(id) || {}), ...(item && typeof item === "object" ? item : {}), id };
      if (id === activeId) {
        const current = currentStep();
        merged.status = snapshot.run.status || merged.status || merged.run_status;
        merged.current_step_name = current && (current.name || current.script_name) || merged.current_step_name || merged.step_name;
        merged.elapsed_seconds = snapshot.run.total_elapsed_seconds ?? merged.elapsed_seconds ?? merged.total_elapsed_seconds;
      }
      return merged;
    }).filter(Boolean);
  }
  function summaryStatus(summary) { return normalizeStatus(summary.status || summary.run_status || summary.run?.status || "idle"); }
  function summaryStep(summary) {
    const step = summary.current_step || {};
    return String(summary.current_step_name || summary.step_name || step.name || step.label || step.script_name || (summaryStatus(summary).css === "running" ? "运行中" : "等待运行"));
  }
  function summaryElapsed(summary) { return Number(summary.elapsed_seconds ?? summary.total_elapsed_seconds ?? summary.timers?.attempt_seconds ?? summary.run?.total_elapsed_seconds ?? 0) || 0; }
  function workspaceCanStart(summary) {
    const status = summaryStatus(summary).css, id = workspaceIdentity(summary);
    if (status === "running" || state.workspaceRunBusy.has(id) || summary.busy === true || summary.can_start === false || summary.workspace_lock?.held === true) return false;
    const capability = state.snapshot.parallel_capability;
    const perWorkspace = capability && (capability.workspaces || capability.workspace_states || capability.by_workspace);
    const entry = perWorkspace && perWorkspace[id];
    return !(entry && (entry.can_start === false || entry.busy === true));
  }
  function renderLoadedWorkspaces() {
    const items = loadedWorkspaceSummaries(state.snapshot), activeId = String(state.snapshot.active_workspace_id || state.snapshot.workspace.id || "");
    const root = $("#loadedWorkspaceList");
    $("#loadedWorkspaceCount").textContent = items.length;
    const capability = state.snapshot.parallel_capability;
    $("#parallelHint").textContent = String(capability && (capability.caution || capability.message || capability.shared_resource_warning) || "不同工作区可并行；共享数据资源时请谨慎");
    root.innerHTML = items.length ? "" : `<div class="loaded-workspace-empty">加载成功后会在这里常驻</div>`;
    items.forEach(summary => {
      const id = workspaceIdentity(summary), status = summaryStatus(summary), isActive = id === activeId;
      const row = document.createElement("div");
      row.className = `loaded-workspace-row is-${status.css}${isActive ? " is-active" : ""}`;
      const busy = state.workspaceRunBusy.has(id), canStart = workspaceCanStart(summary);
      row.innerHTML = `<button class="loaded-workspace-target" type="button" data-workspace-id="${escapeHtml(id)}" title="切换到 ${escapeHtml(workspaceDisplayName(summary))}"><strong><span class="workspace-summary-dot"></span>${escapeHtml(workspaceDisplayName(summary))}</strong><small>${escapeHtml(status.label)} · ${escapeHtml(summaryStep(summary))} · ${formatDuration(summaryElapsed(summary))}</small></button><button class="loaded-workspace-run" type="button" data-run-workspace-id="${escapeHtml(id)}" ${canStart ? "" : "disabled"}>${busy ? "发送中" : status.css === "running" ? "运行中" : "运行"}</button>`;
      root.appendChild(row);
    });
  }
  function updateWorkspaceGate() {
    const gated = !state.floatingOnly && !state.sessionLoaded;
    $("#appShell").classList.toggle("is-workspace-gated", gated);
    const main = $(".main-stage");
    if (main) main.inert = gated;
  }
  function setSelectionStatus(message, error = false) {
    const target = $("#selectionStatus");
    target.textContent = message;
    target.classList.toggle("is-error", error);
  }
  function snapshotFromActionResult(result) {
    if (!result || typeof result !== "object") return null;
    if (result.snapshot && typeof result.snapshot === "object") return result.snapshot;
    if (result.workspace && typeof result.workspace === "object") return result;
    return null;
  }
  async function activateWorkspace(workspaceId, enterWorkspace) {
    const id = String(workspaceId || "");
    if (!id) { setSelectionStatus("请先选择工作区", true); return false; }
    if (state.demo) { setSelectionStatus("演示数据未连接调度内核，不能加载工作区", true); toast("演示模式不能加载真实工作区。", true); return false; }
    const isInitialLoad = Boolean(enterWorkspace);
    if (isInitialLoad) state.loadingWorkspaceId = id;
    else state.switchingWorkspaceId = id;
    setSelectionStatus(isInitialLoad ? "正在挂载并读取工作区…" : "正在切换监控工作区…");
    renderSelectors(); renderLoadedWorkspaces(); renderFloat();
    try {
      const result = await callApi("set_active_workspace", { workspace_id: id });
      if (!result || result.ok === false) throw new Error(result && result.message || "工作区挂载失败");
      if (result.load_result && result.load_result.ok === false) throw new Error(result.load_result.message || "工作区挂载失败");
      if (isInitialLoad && result.load_result && result.load_result.loaded === false) throw new Error(result.load_result.message || "调度内核未确认工作区挂载成功");
      let payload = snapshotFromActionResult(result);
      if (!payload) payload = await callApi("get_state");
      const next = normalizeSnapshot(payload);
      const resolvedId = String(next.active_workspace_id || next.workspace.id || "");
      if (resolvedId !== id) throw new Error("内核未确认目标工作区，仍停留在选择页");
      if (isInitialLoad || state.floatingOnly) state.sessionLoaded = true;
      const selected = workspaceCatalog(next).find(item => String(item.id) === id) || next.workspace;
      const awards = (next.awards || unique(workspaceCatalog(next).map(item => workspaceAwardLabel(item, [])))).map(String);
      state.awardFilter = workspaceAwardLabel(selected, awards) || state.awardFilter;
      state.yearFilter = workspaceYear(selected) || state.yearFilter;
      state.selectedWorkspaceId = id;
      state.pendingWorkspaceId = "";
      setSelectionStatus("工作区已加载");
      applySnapshot(next);
      return true;
    } catch (error) {
      setSelectionStatus(error.message || String(error), true);
      toast(error.message || String(error), true);
      updateWorkspaceGate();
      return false;
    } finally {
      if (isInitialLoad) state.loadingWorkspaceId = "";
      else state.switchingWorkspaceId = "";
      renderSelectors(); renderLoadedWorkspaces(); renderFloat();
    }
  }
  async function startWorkspaceRun(workspaceId) {
    const id = String(workspaceId || "");
    if (!id || state.workspaceRunBusy.has(id)) return;
    state.workspaceRunBusy.add(id); renderLoadedWorkspaces();
    const activeId = String(state.snapshot.active_workspace_id || state.snapshot.workspace.id || "");
    const payload = { workspace_id: id };
    if (id === activeId) {
      payload.plan = $("#runPlanSelect").value;
      payload.selected_orders = Array.from(state.selectedSteps).map(Number);
      state.selectedAttemptId = "";
      state.timelineRequestToken += 1;
    }
    try {
      const result = await safeAction("start_run", payload, "运行指令已发送");
      const next = snapshotFromActionResult(result);
      if (next) applySnapshot(normalizeSnapshot(next));
    } finally {
      state.workspaceRunBusy.delete(id); renderLoadedWorkspaces(); renderFloat();
    }
  }
  function renderHeader() {
    const s = state.snapshot, w = s.workspace, run = s.run;
    $("#awardCrumb").textContent = `${w.award || "未选择奖项"}${w.year ? ` · ${w.year}` : ""}`;
    $("#workspaceCrumb").textContent = w.display_name || w.name || "未挂载工作区";
    $("#workspaceTitle").textContent = w.display_name || w.name || "请选择工作区";
    $("#workspacePath").textContent = w.path || "挂载工作区后即可查看步骤与运行状态";
    const status = normalizeStatus(run.status);
    const chip = $("#overallStatus"); chip.className = `status-chip is-${status.css}`; $("span", chip).textContent = status.label;
    $("#updatedAt").textContent = `同步于 ${formatClock(s.updated_at || new Date())}`;
    const activeSummary = loadedWorkspaceSummaries(s).find(item => workspaceIdentity(item) === String(s.active_workspace_id || w.id || ""));
    const running = status.css === "running", canStart = activeSummary ? workspaceCanStart(activeSummary) : !running;
    const hasSelectedSteps = state.selectedSteps.size > 0;
    $("#startButton").disabled = !canStart || !hasSelectedSteps; $("#startButton").textContent = running ? "正在运行" : state.workspaceRunBusy.has(String(w.id || "")) ? "发送中" : hasSelectedSteps ? "开始运行" : "请选择步骤";
    $("#pauseButton").disabled = !running;
  }
  function normalizeStatus(value) { const key = String(value || "idle").toLowerCase(); const meta = STATUS[key] || STATUS.idle; return { key, label: meta.label, icon: meta.icon, css: key === "done" ? "success" : key === "error" ? "failed" : key }; }
  function liveSeconds(field) {
    const run = state.snapshot.run || {}; let base = Number(run[field] || 0);
    const timerKey = { total_elapsed_seconds: "total", main_elapsed_seconds: "main", current_step_elapsed_seconds: "current_step", async_elapsed_seconds: "async" }[field];
    const timerFlags = run.timer_running || {};
    const shouldTick = timerKey && Object.prototype.hasOwnProperty.call(timerFlags, timerKey)
      ? Boolean(timerFlags[timerKey])
      : String(run.status).toLowerCase() === "running";
    if (shouldTick) base += (performance.now() - state.tickBase) / 1000;
    return base;
  }
  function renderMetrics() {
    const r = state.snapshot.run;
    $("#totalElapsed").textContent = formatDuration(liveSeconds("total_elapsed_seconds"));
    $("#mainElapsed").textContent = formatDuration(liveSeconds("main_elapsed_seconds"));
    $("#stepElapsed").textContent = formatDuration(liveSeconds("current_step_elapsed_seconds"));
    $("#asyncRunning").textContent = r.async_running || 0; $("#asyncTotal").textContent = r.async_total || 0;
    const current = currentStep(); $("#currentStepNote").textContent = current ? current.name : "暂无运行步骤";
  }
  function renderSteps() {
    const steps = state.snapshot.steps, list = $("#stepList"); list.innerHTML = "";
    steps.forEach(step => {
      const meta = normalizeStatus(step.status), row = document.createElement("label");
      row.className = `step-item is-${meta.css}`;
      row.innerHTML = `<input class="step-check" type="checkbox" value="${escapeHtml(step.order)}" ${state.selectedSteps.has(String(step.order)) ? "checked" : ""}><span class="step-order">${escapeHtml(step.order)}</span><span class="step-copy"><strong>${escapeHtml(step.name || step.script_name || `步骤 ${step.order}`)}</strong><small>${escapeHtml(step.path || step.rel_path || "")}</small></span><span class="step-duration mono">${step.duration_seconds ? formatDuration(step.duration_seconds) : "—"}</span><span class="step-state" title="${meta.label}">${meta.icon}</span>`;
      list.appendChild(row);
    });
    $$(".step-check", list).forEach(box => box.addEventListener("change", onStepSelection));
    updateProgress();
  }
  function onStepSelection(event) {
    const key = event.target.value;
    event.target.checked ? state.selectedSteps.add(key) : state.selectedSteps.delete(key);
    state.selectedStepsDirty = true;
    renderHeader(); updateProgress();
    safeAction("set_selected_steps", { workspace_id: state.snapshot.workspace.id, orders: Array.from(state.selectedSteps).map(Number) }).then(result => { if (result && result.ok !== false) state.selectedStepsDirty = false; });
  }
  function updateProgress() {
    const steps = state.snapshot.steps.filter(step => state.selectedSteps.has(String(step.order))), done = steps.filter(s => ["done", "success"].includes(String(s.status).toLowerCase())).length, total = steps.length, pct = total ? done / total * 100 : 0;
    $("#progressFill").style.width = `${pct}%`; $("#progressText").textContent = `${done} / ${total}`; $("#laneCount").textContent = state.snapshot.timeline.length;
  }
  function currentStep() { return state.snapshot.steps.find(s => String(s.status).toLowerCase() === "running") || null; }
  function renderNow() {
    const current = currentStep();
    $("#nowStepOrder").textContent = current ? current.order : "—"; $("#nowStepName").textContent = current ? current.name : "当前没有任务运行"; $("#nowStepPath").textContent = current ? (current.path || current.rel_path || "") : "选择步骤并开始运行";
    $("#nowStepElapsed").textContent = formatDuration(liveSeconds("current_step_elapsed_seconds"));
    const latest = state.logLines.at(-1); $("#latestEvent").textContent = latest ? latest.message : "等待新的运行事件";
  }
  function renderTimeline() {
    const entries = state.snapshot.timeline, chart = $("#timelineChart"), scroll = $(".timeline-scroll");
    const maxEnd = Math.max(100, ...entries.map(e => Number(e.start || 0) + Number(e.duration || 0)));
    const signature = JSON.stringify(entries.map(entry => [entry.run_id, entry.label, entry.axis, entry.status, Number(entry.start || 0), Number(entry.duration || 0)]));
    if (signature !== state.timelineSignature) {
      const previousLeft = scroll ? scroll.scrollLeft : 0;
      const previousTop = scroll ? scroll.scrollTop : 0;
      chart.innerHTML = "";
      entries.forEach((entry, index) => {
        const lane = document.createElement("div"); lane.className = "lane";
        const status = normalizeStatus(entry.status), left = Math.max(0, Number(entry.start || 0) / maxEnd * 100), width = Math.max(3, Number(entry.duration || 0) / maxEnd * 100);
        lane.innerHTML = `<div class="lane-label"><strong>${escapeHtml(entry.label || `记录 ${index + 1}`)}</strong><small>${entry.axis === "main" ? "主步骤链" : "异步任务"} · ${status.label}</small></div><div class="lane-track"><div class="lane-block ${entry.axis === "main" ? "" : "is-async"} is-${status.css}" style="left:${left}%;width:${Math.min(width, 100-left)}%" title="${escapeHtml(entry.label || "")} · ${formatDuration(entry.duration || 0)}">${escapeHtml(entry.label || "")}</div></div>`;
        chart.appendChild(lane);
      });
      const axis = document.createElement("div"); axis.className = "timeline-axis"; for (let i=0;i<9;i++) axis.innerHTML += `<span>${formatDuration(maxEnd * i / 8)}</span>`; chart.appendChild(axis);
      state.timelineSignature = signature;
      if (scroll) { scroll.scrollLeft = previousLeft; scroll.scrollTop = previousTop; }
    }
    const main = entries.filter(e => e.axis === "main").length, async = entries.length - main, run = state.snapshot.run;
    $("#timelineSummary").innerHTML = `<span>主步骤链计时 <strong class="mono">${formatDuration(liveSeconds("main_elapsed_seconds"))}</strong></span><span>主进程 <strong>${normalizeStatus(run.status).label}</strong></span><span>主步骤记录 <strong>${main}</strong></span><span>异步记录 <strong>${async}</strong></span>`;
    const attempts = state.snapshot.attempts;
    const validAttemptIds = attempts.map(a => String(a.id || "")).filter(Boolean);
    if (!state.selectedAttemptId || !validAttemptIds.includes(String(state.selectedAttemptId))) {
      state.selectedAttemptId = validAttemptIds.includes(String(run.attempt_id || "")) ? String(run.attempt_id) : (validAttemptIds[0] || "");
    }
    syncSelectOptions($("#attemptSelect"), attempts.map(a => ({ value: a.id, label: a.name || a.started_at || a.id })), state.selectedAttemptId);
  }
  function renderFiles() { renderFileGrid($("#dataGrid"), state.snapshot.files[state.dataFilter] || []); }
  function renderFileGrid(root, files) {
    root.innerHTML = files.length ? "" : `<div class="empty-state">当前分类没有可展示的文件</div>`;
    files.forEach(file => { const card = document.createElement("article"); card.className = "file-card"; card.dataset.path = file.path || ""; card.innerHTML = `<div class="file-card-top"><span class="file-kind">${escapeHtml(file.kind || "FILE")}</span><span class="file-meta">${escapeHtml(file.size || "")}</span></div><strong>${escapeHtml(file.name || "未命名文件")}</strong><small>${escapeHtml(file.path || "")}</small><small>${escapeHtml(file.modified || "")}</small>`; card.addEventListener("dblclick", () => safeAction("open_path", { path_id: file.path || file.id, kind: "file" })); root.appendChild(card); });
  }
  function renderResources() {
    const root = $("#resourceCards"); root.innerHTML = "";
    const resources = Array.isArray(state.snapshot.resources) ? state.snapshot.resources : [];
    if (!resources.length) {
      root.innerHTML = `<div class="empty-state">当前工作区没有可配置的资源</div>`;
      return;
    }
    resources.forEach(item => {
      const action = String(item.action || "");
      const selectable = action === "select-dataset" || action === "select-rule";
      const configured = Boolean(item.path && item.path !== "尚未指定" && !/^未(?:配置|接入)/.test(String(item.status || "")));
      const idleLabel = selectable ? (configured ? "更换" : "选择") : (action === "open-configs" ? "打开 configs" : "打开");
      const busy = state.resourceActionBusy === action;
      const busyLabel = action === "open-configs" ? "正在打开…" : "正在选择…";
      const disabled = Boolean(state.resourceActionBusy) || !["select-dataset", "select-rule", "open-configs"].includes(action);
      const card = document.createElement("article");
      card.className = "resource-card";
      card.innerHTML = `<p class="eyebrow">${escapeHtml(item.status || "未配置")}</p><h2>${escapeHtml(item.title || "资源")}</h2><p>${escapeHtml(item.description || "")}</p><div class="path-box">${escapeHtml(item.path || "尚未选择")}</div><div class="resource-actions"><button class="quiet-button" data-resource-action="${escapeHtml(action)}" ${disabled ? "disabled" : ""}>${busy ? busyLabel : idleLabel}</button></div>`;
      root.appendChild(card);
    });
  }
  function renderResults() { renderFileGrid($("#resultGrid"), state.snapshot.results); }
  function renderAttempts() {
    const root = $("#attemptList"), attempts = state.snapshot.attempts.filter(a => state.attemptScope === "archived" ? a.archived : !a.archived); root.innerHTML = "";
    (attempts.length ? attempts : state.snapshot.attempts).forEach(a => { const status = normalizeStatus(a.status), row = document.createElement("div"); row.className = "attempt-row"; row.innerHTML = `<div class="attempt-title"><strong>${escapeHtml(a.name || a.id)}</strong><small>${escapeHtml(a.started_at || "")}</small></div><div class="attempt-cell"><span class="mini-status is-${status.css}"><i></i>${status.label}</span></div><div class="attempt-cell">本轮耗时<strong>${formatDuration(a.duration_seconds || 0)}</strong></div><div class="attempt-cell">主步骤<strong>${a.main_steps || 0}</strong></div><div><button class="text-button" data-attempt-id="${escapeHtml(a.id)}">查看详情</button></div>`; root.appendChild(row); });
  }
  function renderManagement() {
    const entries = [
      { icon: "+", title: "新建奖项＋首个工作区", description: "三条真实路径：新奖项走向导；当前奖项按所选年份初始化新工作区；已有工作区创建下一工作区，请运行 inherit.py 或 test.py。", action: "create-workspace", scope: "项目 / 当前奖项", button: "新建奖项向导", requiresWorkspace: false, secondary: { action: "initialize-workspace", button: "按当前奖项/年份初始化新工作区", requiresWorkspace: true } },
      { icon: "▶", title: "运行未编排代码", description: "运行当前工作区未加入主步骤链的代码；现有奖项创建下一工作区时，请选择 inherit.py 或 test.py。", action: "run-unarranged-code", scope: "当前工作区", button: "选择代码", requiresWorkspace: true },
      { icon: "⌘", title: "编辑文件结构", description: "打开文件结构编辑器，维护步骤、文件夹和说明文件的绑定关系。", action: "edit-file-structure", scope: "当前工作区", button: "打开编辑器", requiresWorkspace: true },
      { icon: "◇", title: "原始数据集 / 方案", description: "配置当前已挂载工作区所属奖项和年份使用的原始数据集、评奖规则与方案文件。", action: "configure-resources", scope: "当前工作区", button: "配置资源", requiresWorkspace: true },
      { icon: "{}", title: "configs", description: "打开当前已挂载工作区对应的年度参数及奖项配置入口。", action: "open-configs", scope: "当前工作区", button: "打开 configs", requiresWorkspace: true }
    ];
    const root = $("#managementGrid"); root.innerHTML = "";
    entries.forEach(entry => {
      const card = document.createElement("article");
      card.className = "management-card management-entry";
      const secondary = entry.secondary ? `<button class="management-secondary" data-management-action="${entry.secondary.action}" data-requires-workspace="${entry.secondary.requiresWorkspace}">${entry.secondary.button}</button>` : "";
      card.innerHTML = `<div class="management-card-top"><div class="management-icon">${entry.icon}</div><span class="management-scope">${entry.scope}</span></div><h3>${entry.title}</h3><p>${entry.description}</p><div class="management-action-stack"><button class="management-primary" data-management-action="${entry.action}" data-requires-workspace="${entry.requiresWorkspace}">${entry.button}<span aria-hidden="true">→</span></button>${secondary}</div>`;
      root.appendChild(card);
    });
  }
  async function requestManualCodeSelection(workspaceId) {
    if (state.demo) { toast("演示模式不能运行工作区代码。", true); return; }
    try {
      const result = await callApi("management_action", { action: "run-unarranged-code", workspace_id: workspaceId, award: state.awardFilter, year: state.yearFilter });
      if (!result || result.ok === false) { toast(result && result.message || "未能读取未编排代码清单。", true); return; }
      if (result.requires_selection !== true || !Array.isArray(result.manual_codes)) { toast("后端未返回受控代码清单，本次未执行任何代码。", true); return; }
      openManualCodePicker(result.manual_codes, workspaceId);
    } catch (error) { toast(error.message || String(error), true); }
  }
  function openManualCodePicker(codes, workspaceId) {
    state.manualCodes = (codes || []).filter(code => code && String(code.id || "").trim()).map(code => ({
      id: String(code.id),
      label: /(?:^|[\\/])inherit\.py$/i.test(String(code.rel_path || code.label || "")) ? "继承 / 创建下一工作区" : String(code.label || code.rel_path || code.id),
      rel_path: String(code.rel_path || ""),
      group: String(code.group || "未分组"),
      exists: code.exists !== false
    }));
    state.manualCodeWorkspaceId = String(workspaceId || "");
    state.manualCodeRunning = false;
    $("#manualCodeSearch").value = "";
    $("#manualCodeModal").hidden = false;
    renderManualCodePicker();
    requestAnimationFrame(() => $("#manualCodeSearch").focus());
  }
  function closeManualCodePicker() {
    if (state.manualCodeRunning) return;
    $("#manualCodeModal").hidden = true;
    state.manualCodes = [];
    state.manualCodeWorkspaceId = "";
    $("#manualCodeSearch").value = "";
  }
  function renderManualCodePicker() {
    const root = $("#manualCodeList");
    const query = $("#manualCodeSearch").value.trim().toLocaleLowerCase("zh-CN");
    const visible = state.manualCodes.filter(code => !query || `${code.label} ${code.rel_path} ${code.group}`.toLocaleLowerCase("zh-CN").includes(query));
    const available = visible.filter(code => code.exists).length;
    $("#manualCodeSummary").textContent = state.manualCodes.length
      ? `显示 ${visible.length} 项 · ${available} 项可运行`
      : "当前工作区没有可运行的未编排代码";
    root.innerHTML = "";
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "manual-code-empty";
      empty.textContent = state.manualCodes.length ? "没有匹配的代码，请调整搜索条件。" : "后端返回的未编排代码清单为空。";
      root.appendChild(empty);
      return;
    }
    const groups = new Map();
    visible.forEach(code => { if (!groups.has(code.group)) groups.set(code.group, []); groups.get(code.group).push(code); });
    groups.forEach((items, group) => {
      const section = document.createElement("section");
      section.className = "manual-code-group";
      section.innerHTML = `<div class="manual-code-group-title"><strong>${escapeHtml(group)}</strong><span>${items.length}</span></div>`;
      items.forEach(code => {
        const row = document.createElement("div");
        row.className = `manual-code-row${code.exists ? "" : " is-missing"}`;
        row.innerHTML = `<div class="manual-code-copy"><strong>${escapeHtml(code.label)}</strong><small>${escapeHtml(code.rel_path || "未提供相对路径")}</small></div><button type="button" data-manual-code-id="${escapeHtml(code.id)}" ${!code.exists || state.manualCodeRunning ? "disabled" : ""}>${code.exists ? (state.manualCodeRunning ? "处理中" : "运行") : "文件不存在"}</button>`;
        section.appendChild(row);
      });
      root.appendChild(section);
    });
  }
  async function runManualCode(codeId) {
    if (state.manualCodeRunning) return;
    const code = state.manualCodes.find(item => item.id === String(codeId));
    if (!code || !code.exists) { toast("该代码不在当前可运行清单中。", true); return; }
    if (!state.manualCodeWorkspaceId || state.manualCodeWorkspaceId !== String(state.snapshot.workspace.id || "")) { toast("工作区已经变化，请关闭后重新选择代码。", true); return; }
    state.manualCodeRunning = true;
    renderManualCodePicker();
    const result = await safeAction("run_manual_code", { workspace_id: state.manualCodeWorkspaceId, code_id: code.id });
    state.manualCodeRunning = false;
    if (result && result.ok !== false) closeManualCodePicker();
    else renderManualCodePicker();
  }
  async function requestResourceConfiguration(workspaceId) {
    const selectedWorkspaceId = String(workspaceId || "");
    if (!selectedWorkspaceId) { toast("请先选择并挂载工作区。", true); return; }
    if (state.demo) { toast("演示模式不能修改工作区资源。", true); return; }
    const token = ++state.resourceConfigRequestToken;
    try {
      const result = await callApi("management_action", { action: "configure-resources", workspace_id: selectedWorkspaceId, award: state.snapshot.workspace.award || state.awardFilter, year: state.snapshot.workspace.year || state.yearFilter });
      if (token !== state.resourceConfigRequestToken || selectedWorkspaceId !== String(state.snapshot.workspace.id || "")) return;
      if (!result || result.ok === false) { toast(result && result.message || "未能读取资源配置。", true); return; }
      if (result.requires_resource_config !== true || !result.resource_config || typeof result.resource_config !== "object") { toast("后端未返回受控资源配置，本次未修改任何路径。", true); return; }
      openResourceConfigModal(result.resource_config, selectedWorkspaceId, result.message || "");
    } catch (error) { if (token === state.resourceConfigRequestToken) toast(error.message || String(error), true); }
  }
  function normalizeResourceConfig(config) {
    return {
      dataset_path: String(config && config.dataset_path || ""),
      rule_path: String(config && config.rule_path || ""),
      config_path: String(config && config.config_path || "")
    };
  }
  function openResourceConfigModal(config, workspaceId, message) {
    closeManualCodePicker();
    state.resourceConfig = normalizeResourceConfig(config);
    state.resourceConfigWorkspaceId = String(workspaceId || "");
    state.resourceConfigBusyKind = "";
    state.resourceConfigMessage = String(message || "");
    state.resourceConfigError = false;
    $("#resourceConfigModal").hidden = false;
    renderResourceConfigModal();
  }
  function closeResourceConfigModal(force = false) {
    if (state.resourceConfigBusyKind && !force) return;
    state.resourceConfigRequestToken += 1;
    $("#resourceConfigModal").hidden = true;
    state.resourceConfig = null;
    state.resourceConfigWorkspaceId = "";
    state.resourceConfigBusyKind = "";
    state.resourceConfigMessage = "";
    state.resourceConfigError = false;
  }
  function renderResourceConfigModal() {
    const config = state.resourceConfig || normalizeResourceConfig({});
    const values = [["#resourceDatasetPath", config.dataset_path, "尚未选择原始数据集目录"], ["#resourceRulePath", config.rule_path, "尚未选择方案/规则文件"], ["#resourceConfigPath", config.config_path, "未提供配置文件路径"]];
    values.forEach(([selector, value, fallback]) => { const element = $(selector); element.textContent = value || fallback; element.title = value || ""; element.classList.toggle("is-empty", !value); });
    const message = $("#resourceConfigMessage");
    message.hidden = !state.resourceConfigMessage;
    message.textContent = state.resourceConfigMessage;
    message.classList.toggle("is-error", state.resourceConfigError);
    $$("[data-resource-kind]", $("#resourceConfigModal")).forEach(button => {
      const kind = button.dataset.resourceKind;
      const idleLabel = kind === "dataset" ? "选择原始数据集目录" : "选择方案/规则文件";
      button.disabled = Boolean(state.resourceConfigBusyKind);
      button.textContent = state.resourceConfigBusyKind === kind ? "正在选择…" : idleLabel;
    });
    $("#resourceConfigClose").disabled = Boolean(state.resourceConfigBusyKind);
    $("#resourceConfigCancel").disabled = Boolean(state.resourceConfigBusyKind);
  }
  async function chooseResource(kind) {
    if (!['dataset', 'rule'].includes(kind) || state.resourceConfigBusyKind) return;
    const workspaceId = state.resourceConfigWorkspaceId;
    if (!workspaceId || workspaceId !== String(state.snapshot.workspace.id || "")) { state.resourceConfigMessage = "工作区已经变化，请关闭后重新打开资源配置。"; state.resourceConfigError = true; renderResourceConfigModal(); return; }
    const token = ++state.resourceConfigRequestToken;
    state.resourceConfigBusyKind = kind;
    state.resourceConfigMessage = "";
    state.resourceConfigError = false;
    renderResourceConfigModal();
    try {
      const result = await callApi("choose_resource", { workspace_id: workspaceId, kind });
      if (token !== state.resourceConfigRequestToken || workspaceId !== state.resourceConfigWorkspaceId || workspaceId !== String(state.snapshot.workspace.id || "")) return;
      state.resourceConfigBusyKind = "";
      if (!result || result.ok === false) {
        state.resourceConfigMessage = String(result && result.message || "资源选择失败。即使取消了系统选择器，原配置也未改变。");
        state.resourceConfigError = true;
        renderResourceConfigModal();
        return;
      }
      if (!result.resource_config || typeof result.resource_config !== "object") {
        state.resourceConfigMessage = "后端未返回更新后的资源配置，本次无法确认路径变更。";
        state.resourceConfigError = true;
        renderResourceConfigModal();
        return;
      }
      state.resourceConfig = normalizeResourceConfig(result.resource_config);
      state.resourceConfigMessage = String(result.message || "");
      state.resourceConfigError = false;
      renderResourceConfigModal();
      try {
        const refreshed = await callApi("get_state");
        if (token === state.resourceConfigRequestToken && workspaceId === state.resourceConfigWorkspaceId) applySnapshot(normalizeSnapshot(refreshed));
      } catch (error) {
        if (token === state.resourceConfigRequestToken) { state.resourceConfigMessage = String(error.message || error); state.resourceConfigError = true; renderResourceConfigModal(); }
      }
    } catch (error) {
      if (token !== state.resourceConfigRequestToken) return;
      state.resourceConfigBusyKind = "";
      state.resourceConfigMessage = String(error.message || error);
      state.resourceConfigError = true;
      renderResourceConfigModal();
    }
  }
  async function handleResourceAction(action) {
    const supported = ["select-dataset", "select-rule", "open-configs"];
    if (!supported.includes(action) || state.resourceActionBusy) return;
    const workspaceId = String(state.snapshot.workspace.id || "");
    if (!workspaceId) { toast("请先选择并挂载工作区。", true); return; }
    if (state.demo) { toast("演示模式不能修改或打开工作区资源。", true); return; }
    state.resourceActionBusy = action;
    renderResources();
    try {
      const result = await callApi("management_action", {
        action,
        workspace_id: workspaceId,
        award: state.snapshot.workspace.award || state.awardFilter,
        year: state.snapshot.workspace.year || state.yearFilter
      });
      if (!result || result.ok === false) {
        toast(result && result.message || "资源操作失败，原配置未改变。", !(result && result.cancelled));
        return;
      }
      if (result.snapshot && typeof result.snapshot === "object") {
        applySnapshot(normalizeSnapshot(result.snapshot));
      }
      if (result.message) toast(result.message);
    } catch (error) {
      toast(error.message || String(error), true);
    } finally {
      state.resourceActionBusy = "";
      renderResources();
    }
  }
  function renderLogs() {
    const root = $("#logStream"), previousScrollTop = root.scrollTop;
    const shouldFollow = $("#autoFollow").checked && performance.now() >= state.logFollowPausedUntil;
    root.innerHTML = "";
    state.logLines.forEach(line => { const div = document.createElement("div"); div.className = "log-line"; div.dataset.level = line.level || "info"; div.hidden = state.logLevel !== "all" && div.dataset.level !== state.logLevel; div.innerHTML = `<time>${escapeHtml(line.ts || formatClock(new Date()))}</time><span class="log-level">${escapeHtml(line.source || line.level || "INFO")}</span><span>${escapeHtml(line.message || "")}</span>`; root.appendChild(div); });
    const latest = state.logLines.at(-1); const text = latest ? `${latest.ts || ""} ${latest.message || ""}` : "等待日志"; $("#latestLogInline").textContent = text;
    root.scrollTop = shouldFollow ? root.scrollHeight : previousScrollTop;
  }
  function pauseLogAutoFollow() {
    if (!$("#autoFollow").checked) return;
    state.logFollowPausedUntil = performance.now() + 3000;
    clearTimeout(state.logFollowTimer);
    state.logFollowTimer = setTimeout(() => {
      if (!$("#autoFollow").checked || performance.now() < state.logFollowPausedUntil) return;
      const root = $("#logStream");
      root.scrollTo({ top: root.scrollHeight, behavior: "smooth" });
    }, 3050);
  }
  function logSignature(line) {
    return JSON.stringify([line && line.ts || "", line && line.level || "info", line && line.source || "", line && line.message || ""]);
  }
  function suffixPrefixOverlap(previous, current) {
    const limit = Math.min(previous.length, current.length);
    for (let size = limit; size > 0; size -= 1) {
      let matches = true;
      for (let index = 0; index < size; index += 1) {
        if (previous[previous.length - size + index] !== current[index]) { matches = false; break; }
      }
      if (matches) return size;
    }
    return 0;
  }
  function syncSnapshotLogs(lines, streamKey) {
    const incoming = Array.isArray(lines) ? lines.slice(-500) : [];
    state.snapshotLogLines = incoming;
    const hasStableCursors = incoming.length > 0 && incoming.every(line => line && line.stream_id && Number.isFinite(Number(line.cursor)));
    if (hasStableCursors) {
      state.logStreamKey = streamKey;
      state.logLines = incoming.filter(line => Number(line.cursor) > Number(state.logClearWatermarks.get(String(line.stream_id)) || -1));
      state.serverLogSignatures = incoming.map(logSignature);
      return;
    }
    const signatures = incoming.map(logSignature);
    if (state.logStreamKey !== streamKey) {
      state.logStreamKey = streamKey;
      state.serverLogSignatures = signatures;
      state.logLines = incoming;
      return;
    }
    if (!signatures.length) {
      state.serverLogSignatures = [];
      return;
    }
    const overlap = suffixPrefixOverlap(state.serverLogSignatures, signatures);
    const added = overlap ? incoming.slice(overlap) : incoming;
    if (added.length) {
      const visibleSignatures = state.logLines.map(logSignature);
      const visibleOverlap = suffixPrefixOverlap(visibleSignatures, added.map(logSignature));
      state.logLines = state.logLines.concat(added.slice(visibleOverlap)).slice(-500);
    }
    state.serverLogSignatures = signatures;
  }
  function clearVisibleLogs() {
    state.snapshotLogLines.forEach(line => {
      if (!line || !line.stream_id || !Number.isFinite(Number(line.cursor))) return;
      const streamId = String(line.stream_id);
      state.logClearWatermarks.set(streamId, Math.max(Number(state.logClearWatermarks.get(streamId) || -1), Number(line.cursor)));
    });
    state.logLines = [];
    renderLogs(); renderNow(); renderFloat(); renderOverview();
  }
  function renderFloat() {
    if (!state.snapshot) return;
    const s = state.snapshot, current = currentStep(), run = s.run, done = s.steps.filter(x => ["done","success"].includes(String(x.status).toLowerCase())).length, total = s.steps.length, pct = total ? done/total*100 : 0, latest = state.logLines.at(-1);
    const summaries = loadedWorkspaceSummaries(s), activeId = String(s.active_workspace_id || s.workspace.id || ""), runningCount = summaries.filter(item => summaryStatus(item).css === "running").length;
    $("#floatRunningCount").textContent = `${runningCount} 运行`;
    $("#floatWorkspace").textContent = s.workspace.display_name || s.workspace.name || "Golden Bull Terminal"; $("#floatOrder").textContent = current ? current.order : "—"; $("#floatStep").textContent = current ? current.name : "当前没有任务运行"; $("#floatStatus").textContent = normalizeStatus(run.status).label; $("#floatTime").textContent = formatDuration(liveSeconds("current_step_elapsed_seconds")); $("#floatProgressFill").style.width = `${pct}%`; $("#floatProgressText").textContent = `${done} / ${total}`; $("#floatLatestLog").textContent = latest ? latest.message : "等待运行"; $("#floatTotalTime").textContent = formatDuration(liveSeconds("total_elapsed_seconds")); $("#floatMainTime").textContent = formatDuration(liveSeconds("main_elapsed_seconds")); $("#floatAsync").textContent = run.async_running || 0; $("#floatLog").textContent = latest ? `${latest.ts || ""}  ${latest.message}` : "等待日志";
    const workspaceList = $("#floatWorkspaceList"); workspaceList.innerHTML = summaries.length ? "" : `<div class="float-workspace-empty">暂无已加载工作区</div>`;
    summaries.forEach(summary => {
      const id = workspaceIdentity(summary), meta = summaryStatus(summary), button = document.createElement("button");
      button.type = "button"; button.className = `float-workspace-row is-${meta.css}${id === activeId ? " is-active" : ""}`; button.dataset.floatWorkspaceId = id;
      button.innerHTML = `<strong><span class="workspace-summary-dot"></span>${escapeHtml(workspaceDisplayName(summary))}</strong><small>${escapeHtml(meta.label)} · ${formatDuration(summaryElapsed(summary))}</small>`;
      workspaceList.appendChild(button);
    });
    const lanes = $("#miniLanes"); lanes.innerHTML = ""; s.timeline.slice(-3).forEach(e => { lanes.innerHTML += `<div class="mini-lane"><span>${escapeHtml(e.axis === "main" ? "主步骤" : "异步")}</span><div class="mini-lane-track"><span style="width:${Math.min(100, Math.max(8, e.duration || 20))}%"></span></div></div>`; });
    const statusCss = normalizeStatus(run.status).css, dot = $(".float-status-dot"); dot.style.background = statusCss === "failed" ? "var(--danger)" : statusCss === "success" ? "var(--success)" : statusCss === "running" ? "var(--running)" : "#9ba8a2";
  }

  function switchView(view) {
    state.view = view; $$("[data-view-panel]").forEach(p => p.classList.toggle("is-active", p.dataset.viewPanel === view)); $$(".nav-item[data-view]").forEach(n => n.classList.toggle("is-active", n.dataset.view === view));
    if (["timeline","data","resources","results","attempts"].includes(view)) {
      const requestedAttemptId = state.selectedAttemptId;
      const requestToken = state.timelineRequestToken;
      safeAction("get_panel_data", { panel: view, workspace_id: state.snapshot.workspace.id, attempt_id: requestedAttemptId }).then(data => {
        if (data && typeof data === "object" && (view !== "timeline" || (requestedAttemptId === state.selectedAttemptId && requestToken === state.timelineRequestToken))) applyPartialPanel(view, data);
      });
    }
  }
  function applyPartialPanel(view, data) { if (view === "timeline") { state.snapshot.timeline = data.timeline || data.records || state.snapshot.timeline; renderTimeline(); } else if (view === "data") { state.snapshot.files = data.files || data; renderFiles(); } else if (view === "resources") { state.snapshot.resources = data.resources || data; renderResources(); } else if (view === "results") { state.snapshot.results = data.results || data; renderResults(); } else if (view === "attempts") { state.snapshot.attempts = data.attempts || data; renderAttempts(); } }
  async function selectAttempt(attemptId) {
    const selectedId = String(attemptId || "");
    if (!selectedId) return;
    state.selectedAttemptId = selectedId;
    syncSelectOptions($("#attemptSelect"), state.snapshot.attempts.map(a => ({ value: a.id, label: a.name || a.started_at || a.id })), selectedId);
    if (state.demo) {
      const index = Math.max(0, state.snapshot.attempts.findIndex(a => String(a.id) === selectedId));
      const attempt = state.snapshot.attempts[index];
      state.snapshot.run = { ...state.snapshot.run, attempt_id: selectedId, attempt_name: attempt && attempt.name || selectedId, status: attempt && attempt.status || "idle" };
      state.snapshot.timeline = demoSnapshot.timeline.map((entry, laneIndex) => ({ ...entry, start: entry.start + index * (laneIndex + 2), duration: Math.max(5, entry.duration - index * 2) }));
      state.timelineSignature = "";
      renderTimeline(); renderHeader();
      return;
    }
    const token = ++state.timelineRequestToken;
    const result = await safeAction("select_attempt", { attempt_id: selectedId, workspace_id: state.snapshot.workspace.id });
    if (token !== state.timelineRequestToken || selectedId !== state.selectedAttemptId || !result) return;
    const nextSnapshot = result.snapshot && typeof result.snapshot === "object" ? result.snapshot : (result.workspace && result.run ? result : null);
    if (nextSnapshot) applySnapshot(normalizeSnapshot(nextSnapshot));
  }
  function handleAction(action) {
    if (!state.snapshot) { toast("正在连接调度内核，请稍候"); return; }
    const w = state.snapshot.workspace || {};
    if (action === "refresh") return state.demo ? applySnapshot(structuredCloneSafe(demoSnapshot)) : safeAction("get_state").then(x => x && x.ok !== false && applySnapshot(normalizeSnapshot(x)));
    if (action === "open-legacy") return safeAction("launch_legacy_terminal");
    if (action === "load-workspace") return activateWorkspace(state.selectedWorkspaceId || $("#workspaceSelect").value, true);
    if (action === "select-all" || action === "select-none") { state.selectedSteps = action === "select-all" ? new Set(state.snapshot.steps.map(s => String(s.order))) : new Set(); state.selectedStepsDirty = true; renderSteps(); renderHeader(); return safeAction("set_selected_steps", { workspace_id: w.id, orders: Array.from(state.selectedSteps).map(Number) }).then(result => { if (result && result.ok !== false) state.selectedStepsDirty = false; return result; }); }
    if (action === "start") return startWorkspaceRun(w.id);
    if (action === "pause") return safeAction("pause_run", { workspace_id: w.id }, "暂停指令已发送；确认规则由内核处理");
    if (action === "toggle-log") { const drawer = $("#logDrawer"); drawer.classList.toggle("is-open"); $(".log-handle").setAttribute("aria-expanded", drawer.classList.contains("is-open")); return; }
    if (action === "clear-log") { clearVisibleLogs(); return; }
    if (action === "close-manual-code") { closeManualCodePicker(); return; }
    if (action === "close-resource-config") { closeResourceConfigModal(); return; }
    if (action === "toggle-float") return safeAction("show_floating_monitor", { visible: true, mode: "mini" }, "悬浮监视器已打开");
    if (action === "float-close") { safeAction("close_floating_monitor").finally(() => window.close()); return; }
    if (action === "float-collapse") { $("#floatingMonitor").classList.add("is-collapsed"); return safeAction("set_floating_mode", { mode: "mini" }); }
    if (action === "float-expand") { $("#floatingMonitor").classList.remove("is-collapsed"); return safeAction("set_floating_mode", { mode: "expanded" }); }
    if (action === "float-pause") return safeAction("pause_run", { workspace_id: w.id }, "暂停指令已发送；确认规则由内核处理");
    if (action === "open-main") { if (!document.body.classList.contains("floating-only")) switchView("dashboard"); return safeAction("focus_main_window"); }
    if (action === "configure-resources") { switchView("resources"); return; }
    const map = { "open-workspace": ["open_path", { path_id: "workspace", kind: "workspace" }], "open-logs": ["open_path", { path_id: "logs", kind: "logs" }], "open-results": ["open_path", { path_id: "results", kind: "results" }], "open-attempt": ["open_path", { path_id: $("#attemptSelect").value || "attempt", kind: "attempt" }] };
    if (map[action]) return safeAction(map[action][0], map[action][1]);
  }

  function bindEvents() {
    document.addEventListener("click", event => {
      const workspaceRun = event.target.closest("[data-run-workspace-id]"); if (workspaceRun) { event.preventDefault(); event.stopPropagation(); startWorkspaceRun(workspaceRun.dataset.runWorkspaceId); return; }
      const workspaceTarget = event.target.closest("[data-workspace-id]"); if (workspaceTarget) { event.preventDefault(); activateWorkspace(workspaceTarget.dataset.workspaceId, false); return; }
      const floatWorkspace = event.target.closest("[data-float-workspace-id]"); if (floatWorkspace) { event.preventDefault(); activateWorkspace(floatWorkspace.dataset.floatWorkspaceId, false); return; }
      const viewButton = event.target.closest("[data-view]"); if (viewButton) switchView(viewButton.dataset.view);
      const actionButton = event.target.closest("[data-action]"); if (actionButton) handleAction(actionButton.dataset.action);
      const mgmt = event.target.closest("[data-management-action]"); if (mgmt) { const workspaceId = String(state.snapshot.workspace.id || ""); if (mgmt.dataset.requiresWorkspace === "true" && !workspaceId) toast("请先选择并挂载工作区。", true); else if (mgmt.dataset.managementAction === "run-unarranged-code") requestManualCodeSelection(workspaceId); else if (mgmt.dataset.managementAction === "configure-resources") switchView("resources"); else safeAction("management_action", { action: mgmt.dataset.managementAction, workspace_id: workspaceId, award: state.snapshot.workspace.award || state.awardFilter, year: state.snapshot.workspace.year || state.yearFilter }); }
      const manualCode = event.target.closest("[data-manual-code-id]"); if (manualCode) runManualCode(manualCode.dataset.manualCodeId);
      const resourceKind = event.target.closest("[data-resource-kind]"); if (resourceKind) chooseResource(resourceKind.dataset.resourceKind);
      const resource = event.target.closest("[data-resource-action]"); if (resource) handleResourceAction(String(resource.dataset.resourceAction || ""));
      const attempt = event.target.closest("[data-attempt-id]"); if (attempt) { state.selectedAttemptId = String(attempt.dataset.attemptId || ""); switchView("timeline"); selectAttempt(state.selectedAttemptId); }
    });
    $("#workspaceSelect").addEventListener("change", e => { closeManualCodePicker(); closeResourceConfigModal(true); state.pendingWorkspaceId = ""; state.selectedWorkspaceId = String(e.target.value || ""); $("#workspaceFullName").textContent = e.target.selectedOptions[0]?.textContent || ""; setSelectionStatus(state.selectedWorkspaceId ? "已选择，点击加载工作区" : "请选择工作区"); renderSelectors(); });
    $("#awardSelect").addEventListener("change", e => {
      const all = workspaceCatalog(state.snapshot), awards = (state.snapshot.awards || unique(all.map(w => workspaceAwardLabel(w, [])))).map(String);
      state.awardFilter = String(e.target.value || ""); state.yearFilter = latestYearForAward(all, state.awardFilter, awards);
      state.selectedWorkspaceId = String(latestWorkspaceForSelection(all, state.awardFilter, state.yearFilter, awards)?.id || ""); state.pendingWorkspaceId = "";
      setSelectionStatus(state.selectedWorkspaceId ? "已预选该奖项最新年份与最新工作区，点击加载" : "该奖项暂无可用工作区", !state.selectedWorkspaceId); renderSelectors();
    });
    $("#yearSelect").addEventListener("change", e => {
      const all = workspaceCatalog(state.snapshot), awards = (state.snapshot.awards || unique(all.map(w => workspaceAwardLabel(w, [])))).map(String);
      state.yearFilter = String(e.target.value || ""); state.selectedWorkspaceId = String(latestWorkspaceForSelection(all, state.awardFilter, state.yearFilter, awards)?.id || ""); state.pendingWorkspaceId = "";
      setSelectionStatus(state.selectedWorkspaceId ? "已预选该年份最新工作区，点击加载" : "该年份暂无可用工作区", !state.selectedWorkspaceId); renderSelectors();
    });
    $("#attemptSelect").addEventListener("change", e => selectAttempt(e.target.value));
    $("#dataFilter").addEventListener("click", e => { const button = e.target.closest("[data-filter]"); if (!button) return; state.dataFilter = button.dataset.filter; $$("button", e.currentTarget).forEach(x => x.classList.toggle("is-active", x === button)); renderFiles(); });
    $("#attemptScope").addEventListener("click", e => { const button = e.target.closest("[data-scope]"); if (!button) return; state.attemptScope = button.dataset.scope; $$("button", e.currentTarget).forEach(x => x.classList.toggle("is-active", x === button)); renderAttempts(); safeAction("set_attempt_scope", { scope: state.attemptScope }); });
    $("#manualCodeSearch").addEventListener("input", renderManualCodePicker);
    $("#manualCodeModal").addEventListener("click", e => { if (e.target === e.currentTarget) closeManualCodePicker(); });
    $("#resourceConfigModal").addEventListener("click", e => { if (e.target === e.currentTarget) closeResourceConfigModal(); });
    document.addEventListener("keydown", e => { if (e.key !== "Escape") return; if (!$("#resourceConfigModal").hidden) closeResourceConfigModal(); else if (!$("#manualCodeModal").hidden) closeManualCodePicker(); });
    $(".log-filters").addEventListener("click", e => { const button = e.target.closest("[data-log-level]"); if (!button) return; state.logLevel = button.dataset.logLevel; $$("button", e.currentTarget).forEach(x => x.classList.toggle("is-active", x === button)); renderLogs(); });
    const logStream = $("#logStream");
    logStream.addEventListener("wheel", pauseLogAutoFollow, { passive: true });
    logStream.addEventListener("touchstart", pauseLogAutoFollow, { passive: true });
    logStream.addEventListener("keydown", pauseLogAutoFollow);
    logStream.addEventListener("pointerdown", () => { state.logPointerActive = true; pauseLogAutoFollow(); });
    logStream.addEventListener("pointermove", () => { if (state.logPointerActive) pauseLogAutoFollow(); });
    document.addEventListener("pointerup", () => { if (state.logPointerActive) pauseLogAutoFollow(); state.logPointerActive = false; });
    $("#autoFollow").addEventListener("change", event => {
      clearTimeout(state.logFollowTimer);
      if (!event.target.checked) return;
      state.logFollowPausedUntil = 0;
      logStream.scrollTo({ top: logStream.scrollHeight, behavior: "smooth" });
    });
    $(".float-mini-body").addEventListener("click", e => { if (e.target.closest("button")) return; handleAction($("#floatingMonitor").classList.contains("is-collapsed") ? "float-expand" : "float-collapse"); });
    enableFloatingDrag();
  }
  function enableFloatingDrag() {
    const monitor = $("#floatingMonitor"), handle = $("[data-drag-region]", monitor); let drag = null;
    handle.addEventListener("pointerdown", e => { if (e.target.closest("button")) return; const rect = monitor.getBoundingClientRect(); drag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top }; handle.setPointerCapture(e.pointerId); });
    handle.addEventListener("pointermove", e => { if (!drag || document.body.classList.contains("floating-only")) return; monitor.style.left = `${Math.max(0, Math.min(innerWidth-monitor.offsetWidth, e.clientX-drag.dx))}px`; monitor.style.top = `${Math.max(0, Math.min(innerHeight-monitor.offsetHeight, e.clientY-drag.dy))}px`; monitor.style.right = "auto"; });
    handle.addEventListener("pointerup", () => { drag = null; safeAction("save_floating_position", { left: monitor.offsetLeft, top: monitor.offsetTop }); });
  }

  function appendLog(entry) {
    if (entry && entry.stream_id && Number.isFinite(Number(entry.cursor))) {
      const watermark = Number(state.logClearWatermarks.get(String(entry.stream_id)) || -1);
      if (Number(entry.cursor) <= watermark) return;
    }
    state.logLines.push(entry);
    state.logLines = state.logLines.slice(-500);
    renderLogs(); renderNow(); renderFloat();
  }
  function formatDuration(seconds) { const total = Math.max(0, Math.floor(Number(seconds) || 0)), h = Math.floor(total / 3600), m = Math.floor(total % 3600 / 60), s = total % 60; return [h,m,s].map(v => String(v).padStart(2,"0")).join(":"); }
  function formatClock(value) { const d = value instanceof Date ? value : new Date(value); return Number.isNaN(d.getTime()) ? String(value || "") : d.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" }[char])); }
  function toast(message, error = false) { const item = document.createElement("div"); item.className = `toast${error ? " is-error" : ""}`; item.textContent = message; $("#toastRegion").appendChild(item); setTimeout(() => item.remove(), 3200); }
  function startClock() { setInterval(() => { if (!state.snapshot) return; renderMetrics(); renderNow(); renderFloat(); }, 1000); }

  window.TerminalUI = { applySnapshot: data => applySnapshot(normalizeSnapshot(data)), appendLog, showFloating: mode => { $("#floatingMonitor").classList.remove("is-hidden"); $("#floatingMonitor").classList.toggle("is-collapsed", mode === "mini"); }, hideFloating: () => $("#floatingMonitor").classList.add("is-hidden"), switchView };
  document.addEventListener("DOMContentLoaded", () => {
    const queryView = new URLSearchParams(location.search).get("view");
    const queryMode = new URLSearchParams(location.search).get("mode");
    const fragmentView = new URLSearchParams(location.hash.replace(/^#/, "")).get("view");
    if (queryView === "floating" || fragmentView === "floating") {
      state.floatingOnly = true;
      state.sessionLoaded = true;
      document.body.classList.add("floating-only");
      $("#floatingMonitor").classList.remove("is-hidden");
      $("#floatingMonitor").classList.toggle("is-collapsed", queryMode !== "expanded");
    }
    updateWorkspaceGate();
    bindEvents();
    startClock();
    connect();
  });
  window.addEventListener("pywebviewready", connect);
})();
