import {connectToken, disconnectToken, request, mutate, ApiError} from "./api.js";

const $ = id => document.getElementById(id);
const fields = ["work_location_description", "work_object_description", "work_method_description", "attachment_description"];
const labels = {work_location_description:"作业位置", work_object_description:"作业对象", work_method_description:"作业方式", attachment_description:"附件说明"};
const kinds = {helmet_missing:"未戴安全帽", gas_abnormal:"气体浓度异常"};
const statusNames = {waiting_input:"待补充材料", awaiting_review:"待人工复核", analyzing:"分析中", completed:"核查完成", failed:"核查失败", stale:"结果过时", interrupted:"执行中断", cancelled:"已取消", linked:"已关联", pending:"待关联", stale_material:"材料已变化", current:"当前有效", superseded_event:"已有较新事件", expired_event:"事件过期"};
const steps = {verify_event_on_site:"现场核实该事件", review_evidence_with_safety_manager:"与安全管理人员共同复核依据", complete_material:"补充缺失的作业材料"};
const decisions = {confirmed_event:"确认事件", disputed_event:"对事件有异议", needs_verification:"需要继续核实"};
const state = {info:null, task:null, taskId:null, events:[], event:null, reviews:[], review:null, busy:false};
const text = (id, value) => { $(id).textContent = value ?? ""; };
const json = value => JSON.stringify(value, null, 2);
function node(tag, value, className) {
  const n = document.createElement(tag); if (value !== undefined) n.textContent = value;
  if (className) n.className = className; return n;
}
function message(value, failed = false) {
  text(failed ? "error" : "notice", value); $(failed ? "error" : "notice").hidden = false;
}
function setPill(id, value, variant = "") { text(id, value); $(id).className = "pill " + variant; }
function canFeedback() { return state.review?.currentness === "current" && state.review?.result?.status === "completed"; }
function buttons() {
  document.querySelectorAll("[data-action], .task-item, .event-item, .review-history button").forEach(b => b.disabled = state.busy);
  $("submit-material").disabled = state.busy || !state.info || (state.taskId && !state.task);
  const simulate = state.task && state.info?.simulation_enabled;
  $("helmet-event").disabled = $("gas-event").disabled = state.busy || !simulate;
  $("run-review").disabled = state.busy || !state.event || !state.info?.simulation_enabled;
  $("send-feedback").disabled = state.busy || !canFeedback();
  $("recover-task").disabled = state.busy || !state.taskId;
  $("refresh").disabled = state.busy || !state.info;
  $("connect").disabled = state.busy; $("config-file").disabled = state.busy;
}
async function action(work) {
  if (state.busy) return;
  state.busy = true; buttons(); $("error").hidden = $("notice").hidden = true;
  try { await work(); }
  catch (error) {
    message(error instanceof ApiError ? error.message : "操作未完成，请刷新核对服务端状态。", true);
    if (error.status === 401) disconnect();
  } finally { state.busy = false; buttons(); }
}
function formValues() { return Object.fromEntries(fields.map(f => [f, $(f).value.trim()])); }
function fill(value) { fields.forEach(f => $(f).value = value?.[f] || ""); }
function renderTask() {
  const task = state.task;
  setPill("task-status", task ? (statusNames[task.status] || task.status) : "草稿", task?.status === "waiting_input" ? "warn" : task ? "good" : "");
  text("revision", task ? "材料版本 v" + task.revision : "尚未创建");
  text("task-id", state.taskId || "创建后显示任务标识");
  if (state.taskId && !task) setPill("task-status", "快照待读取或恢复", "warn");
  text("submit-material", !task ? "创建并分析材料" : task.status === "waiting_input" ? "提交补充并再分析" : "修订材料并重新分析");
  text("material-action-hint", task ? "仅提交已修改字段；版本由服务端校验" : "提交后查看缺项与追问");
  text("task-json", task ? json(task) : "暂无状态");
  $("recover-task").hidden = !state.taskId;
  const issues = task?.analysis?.issues || [];
  text("issue-count", task ? issues.length + " 项" : ""); $("issues").replaceChildren();
  if (!task) $("issues").append(node("p", "提交材料后，追问会出现在这里。", "empty-small"));
  else if (!issues.length) $("issues").append(node("p", "当前材料未发现缺项。离线规则尚未检查内容语义，仍需人工复核。", "empty-small"));
  else issues.forEach(issue => {
    const card = node("div", undefined, "issue");
    card.append(node("strong", labels[issue.field] || issue.field), node("p", issue.question), node("p", issue.reason));
    const focus = node("button", "去补充此字段"); focus.type = "button";
    focus.addEventListener("click", () => $(issue.field)?.focus()); card.append(focus); $("issues").append(card);
  });
  if (task?.analysis?.error) $("issues").append(node("p", "分析未完成：" + task.analysis.error, "unknown"));
  text("event-scope", task ? state.info?.references ? "模拟对象：" + state.info.references.area_id + " · 自动绑定材料 v" + task.revision : "当前身份未配置事件模拟；可查看已有记录。" : "先创建或选择一个任务。");
}
async function loadTasks() {
  const result = await request("/console/api/tasks"); $("task-list").replaceChildren();
  if (!result.items.length) $("task-list").append(node("p", "暂无任务，创建第一份材料。", "sidebar-muted"));
  result.items.forEach(task => {
    const b = node("button", undefined, "task-item" + (state.task?.task_id === task.task_id ? " active" : ""));
    const title = task.initial_fields?.work_object_description || "材料任务";
    b.append(node("span", title.length > 20 ? title.slice(0, 20) + "…" : title), node("small", task.task_id.slice(0, 12) + " · " + new Date(task.created_at).toLocaleDateString()));
    b.addEventListener("click", () => action(() => chooseTask(task.task_id))); $("task-list").append(b);
  }); buttons(); return result.items;
}
function clearReview() { state.reviews = []; state.review = null; renderReview(); }
function renderEvents() {
  text("event-count", state.events.length + " 条"); $("event-list").replaceChildren();
  if (!state.events.length) { const empty = node("div", "暂无事件", "empty"); empty.append(node("span", "生成合成事件，开始核查链路")); $("event-list").append(empty); }
  state.events.forEach(event => {
    const b = node("button", undefined, "event-item" + (state.event?.receipt_id === event.receipt_id ? " active" : ""));
    const top = node("div", undefined, "event-top");
    top.append(node("span", kinds[event.raw.kind] || event.raw.kind), node("span", "原始报警：active", "alarm"));
    const note = event.raw.kind === "gas_abnormal" ? event.raw.value + " %LEL（合成读数）" : "置信信息 " + event.raw.confidence + "（模拟算法事件）";
    b.append(top, node("small", note), node("small", "材料 v" + event.binding?.revision + " · " + new Date(event.received_at).toLocaleTimeString() + " · " + (statusNames[event.result?.status || event.admission] || event.result?.status || event.admission)));
    b.addEventListener("click", () => action(() => chooseEvent(event.receipt_id))); $("event-list").append(b);
  });
  text("event-json", state.event ? json(state.event) : "暂无事件"); buttons();
}
async function loadEvents() {
  state.events = state.task ? (await request("/console/api/tasks/" + state.task.task_id + "/events")).items : [];
  if (state.event) state.event = state.events.find(e => e.receipt_id === state.event.receipt_id) || null;
  renderEvents();
}
async function chooseTask(id) {
  state.taskId = id; state.task = null; state.events = []; state.event = null;
  clearReview(); fill({}); renderTask(); renderEvents();
  state.task = await request("/tasks/" + id); fill(state.task.fields);
  renderTask(); await loadTasks(); await loadEvents();
}
async function chooseEvent(receipt, preferredReview) {
  state.event = null; clearReview(); renderEvents();
  const event = state.events.find(e => e.receipt_id === receipt) || await request("/events/" + receipt);
  const reviews = (await request("/console/api/events/" + receipt + "/reviews")).items;
  const selected = reviews.find(r => r.review_id === preferredReview) || reviews[0];
  const review = selected ? await request("/reviews/" + selected.review_id) : null;
  state.event = event; state.reviews = reviews; state.review = review;
  renderEvents(); renderReview();
}
function renderReview() {
  $("review-history").replaceChildren();
  state.reviews.forEach(r => {
    const b = node("button", "核查 " + r.review_id.slice(0, 8), r.review_id === state.review?.review_id ? "active" : "");
    b.addEventListener("click", () => action(async () => { state.review = await request("/reviews/" + r.review_id); renderReview(); }));
    $("review-history").append(b);
  });
  $("review-result").replaceChildren(); $("feedback-panel").hidden = !state.review;
  text("review-json", state.review ? json(state.review) : "暂无核查");
  if (!state.review) { const empty = node("div", "等待事件核查", "empty"); empty.append(node("span", "这里展示关注项、依据和未知信息")); $("review-result").append(empty); buttons(); return; }
  const review = state.review, result = review.result, report = result?.report;
  const target = $("review-result"), summary = node("div", undefined, "review-summary");
  summary.append(node("span", statusNames[result?.status] || "待完成", "pill"), node("span", statusNames[review.currentness] || review.currentness, "pill " + (review.currentness === "current" ? "good" : "warn")), node("span", "绑定材料 v" + review.material_revision, "muted"));
  target.append(summary);
  if (review.currentness !== "current") target.append(node("p", "该结果已不适用于当前材料或事件。请核对最新条件，生成新的合成事件后重新核查。", "unknown"));
  if (!report?.candidate) target.append(node("p", "未生成有效候选：" + (report?.stop_reason || "执行未完成") + "。原始报警继续保留。", "unknown"));
  if (report?.candidate) {
    const concerns = node("div", undefined, "review-section"); concerns.append(node("h3", "关注项与引用"));
    report.candidate.concerns.forEach(c => concerns.append(node("div", (kinds[c.category] || {evidence_gap:"依据缺失",context_for_review:"需复核的知识依据"}[c.category] || c.category) + " · " + c.evidence_ids.join(" / "), "concern")));
    target.append(concerns);
    if (report.candidate.unknown_observation_ids.length) target.append(node("p", "未知或不可用依据：" + report.candidate.unknown_observation_ids.join("、") + "。不能将未知视为安全。", "unknown"));
    const next = node("div", undefined, "review-section"); next.append(node("h3", "下一步需人工完成"));
    report.candidate.next_steps.forEach(s => next.append(node("div", steps[s] || s, "next-step"))); target.append(next);
  }
  const evidence = node("div", undefined, "review-section"); evidence.append(node("h3", "本轮事实与知识查询"));
  (report?.observations || []).forEach((o, i) => {
    const row = node("div", undefined, "evidence");
    row.append(node("strong", "o" + (i+1) + " · " + ({query_worker_qualification:"人员资质",query_area_status:"区域状态",query_knowledge:"示例制度"}[o.tool] || o.tool)), node("p", "查询结果：" + o.outcome + (o.reason ? " / " + o.reason : "")));
    if (o.facts) row.append(node("pre", json(o.facts)));
    (o.citations || []).forEach(c => row.append(node("p", "引用：" + c.quote)));
    if (o.source) row.append(node("pre", json(o.source)));
    evidence.append(row);
  }); target.append(evidence);
  text("feedback-status", review.feedback ? "已保存：" + decisions[review.feedback.decision] + " · 反馈版本 v" + review.revision : "反馈只记录人工意见，不改变原始报警或批准作业。");
  if (review.feedback) $("feedback-decision").value = review.feedback.decision;
  buttons();
}
function draft() { state.taskId = null; state.task = null; state.event = null; state.events = []; clearReview(); fill({}); renderTask(); renderEvents(); }
function disconnect() {
  disconnectToken(); state.taskId = null; state.info = state.task = state.event = state.review = null; state.events = []; state.reviews = [];
  $("token").value = ""; $("config-file").value = ""; $("connect-panel").hidden = false; $("workbench").hidden = true;
  $("disconnect").hidden = true; setPill("connection-status", "未连接"); text("identity", "");
  $("task-list").replaceChildren(node("p", "连接后加载任务", "sidebar-muted")); fill({}); renderTask(); renderEvents(); renderReview();
}
async function connect(value) {
  if (!value || !/^[A-Za-z0-9._~-]{32,256}$/.test(value)) throw new ApiError("请选择有效演示配置或输入测试令牌。", 422);
  connectToken(value);
  try { state.info = await request("/console/api/info"); }
  catch (error) { disconnectToken(); state.info = null; throw error; }
  $("token").value = ""; $("connect-panel").hidden = true; $("workbench").hidden = false; $("disconnect").hidden = false;
  setPill("connection-status", "已连接", "good"); text("identity", state.info.identity.tenant_id + " / " + state.info.identity.user_id);
  renderTask(); const tasks = await loadTasks(); if (tasks.length) await chooseTask(tasks[0].task_id);
}
$("connect").addEventListener("click", () => action(() => connect($("token").value.trim())));
$("config-file").addEventListener("change", () => action(async () => {
  const file = $("config-file").files[0]; if (!file || file.size > 262144) throw new ApiError("配置文件无效或过大。", 422);
  let cfg; try { cfg = JSON.parse(await file.text()); } catch { throw new ApiError("配置文件不是有效 JSON。", 422); }
  if (cfg.schema_version !== "local-service-v1") throw new ApiError("请选择本地服务配置文件。", 422);
  const token = cfg.tokens?.[0]?.token; cfg = null; $("config-file").value = ""; await connect(token);
}));
$("disconnect").addEventListener("click", () => { if (!state.busy) disconnect(); });
$("new-task").addEventListener("click", () => action(async () => { draft(); await loadTasks(); message("新任务草稿已就绪，请填写合成材料。"); }));
$("sample").addEventListener("click", () => action(async () => {
  draft(); fill({work_object_description:"SYNTHETIC：演示试件 A 接缝",attachment_description:"SYNTHETIC：试件 A 的位置标记示意图"});
  await loadTasks(); message("示例故意留空位置与方式，提交后观察两条追问。");
}));
$("material-form").addEventListener("submit", event => { event.preventDefault(); action(async () => {
  const value = formValues();
  const receipt = state.event?.receipt_id, previousReview = state.review?.review_id;
  clearReview();
  if (!state.task) {
    try { state.task = await mutate("/tasks", {fields:value}); }
    catch (error) { if (error.taskId) { state.taskId = error.taskId; renderTask(); } throw error; }
  }
  else {
    const patch = Object.fromEntries(fields.filter(f => value[f] !== state.task.fields[f]).map(f => [f,value[f]]));
    if (!Object.keys(patch).length) { message("材料没有改动，修改字段后再提交。"); return; }
    const method = state.task.status === "waiting_input" ? "resume" : "revise";
    state.task = await mutate("/tasks/" + state.task.task_id + "/" + method, {expected_revision:state.task.revision,fields:patch});
  }
  state.taskId = state.task.task_id;
  fill(state.task.fields); renderTask(); await loadTasks(); await loadEvents();
  if (receipt) await chooseEvent(receipt, previousReview);
  message("材料已保存，当前版本 v" + state.task.revision + "。");
}); });
$("refresh").addEventListener("click", () => action(async () => {
  const receipt = state.event?.receipt_id, review = state.review?.review_id;
  clearReview();
  if (state.task) { state.task = await request("/tasks/" + state.task.task_id); fill(state.task.fields); }
  renderTask(); await loadTasks(); await loadEvents(); if (receipt) await chooseEvent(receipt, review);
  message("已读取服务端最新状态。");
}));
$("recover-task").addEventListener("click", () => action(async () => {
  const receipt = state.event?.receipt_id, review = state.review?.review_id;
  clearReview();
  state.task = await request("/tasks/" + state.taskId + "/recover", {method:"POST"});
  fill(state.task.fields); renderTask(); await loadTasks(); await loadEvents();
  if (receipt) await chooseEvent(receipt, review);
  message("已读取或恢复待完成的材料操作。");
}));
for (const [id, kind] of [["helmet-event","helmet_missing"],["gas-event","gas_abnormal"]]) $(id).addEventListener("click", () => action(async () => {
  state.event = null; clearReview(); renderEvents();
  const event = await mutate("/console/api/tasks/" + state.task.task_id + "/events", {kind,expected_revision:state.task.revision});
  await loadEvents(); await chooseEvent(event.receipt_id); message("合成事件已保存，原始报警为 active。请显式发起核查。");
}));
$("run-review").addEventListener("click", () => action(async () => {
  const review = await mutate("/console/api/events/" + state.event.receipt_id + "/reviews");
  await loadEvents(); await chooseEvent(state.event.receipt_id, review.review_id);
  message(review.result?.status === "completed" ? "模型替身核查已完成，请查看依据并记录人工反馈。" : "核查没有完成，请查看失败原因。");
}));
$("send-feedback").addEventListener("click", () => action(async () => {
  await mutate("/reviews/" + state.review.review_id + "/feedback", {expected_revision:state.review.revision,decision:$("feedback-decision").value});
  await chooseEvent(state.event.receipt_id, state.review.review_id); message("人工反馈已保存；原始报警保持不变。");
}));
buttons();
