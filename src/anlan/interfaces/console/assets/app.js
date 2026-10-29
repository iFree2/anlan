import {connectToken, disconnectToken, request, mutate, subscribeSnapshot, ApiError} from "./api.js";

const $ = id => document.getElementById(id);
const labels = {work_location_description:"作业位置", work_object_description:"作业对象", work_method_description:"作业方式", attachment_description:"附件说明"};
const statuses = {idle:"空闲", pending_confirmation:"等待确认", active_hot_work:"任务进行中", paused:"已暂停", waiting_input:"待补充材料", awaiting_review:"待人工复核", analyzing:"分析中", completed:"核查完成", failed:"核查失败", current:"当前有效", stale_material:"材料已变化"};
const kinds = {helmet_missing:"未戴安全帽", gas_abnormal:"气体浓度异常"};
const state = {info:null, conversations:[], snapshot:null, busy:false, stream:null, streamId:null, events:[], event:null, reviews:[], review:null, applications:[], notifications:new Map(), notificationCursor:0, pollTimer:null, epoch:0, businessDrafts:new Map(), preflightCatalogs:new Map(), preflightDrafts:new Map()};
const businessLabels = {submit:"提交申请", request_changes:"要求补充", resubmit:"重新提交", complete_review:"材料核查完成", run_event_review:"发起事件核查", record_event_feedback:"保存人工反馈"};
const applicationStatuses = {draft:"草稿", under_review:"待安全人员核查", changes_requested:"待申请人补充", review_completed:"材料核查完成"};

const text = (id, value) => { $(id).textContent = value ?? ""; };
function node(tag, value, className) { const element = document.createElement(tag); if (value !== undefined) element.textContent = value; if (className) element.className = className; return element; }
function showNotice(value, failed=false) { text(failed ? "error" : "notice", value); $(failed ? "error" : "notice").hidden = false; }
function clearNotices() { $("error").hidden = $("notice").hidden = true; }
function setPill(id, value, variant="") { text(id, value); $(id).className = "pill " + variant; }
function projection() { return state.snapshot?.task_projection || null; }

function updateButtons() {
  document.querySelectorAll("[data-action], .conversation-item, .confirmation-card button, .task-actions button, .event-item").forEach(button => button.disabled = state.busy);
  $("connect").disabled = state.busy; $("config-file").disabled = state.busy;
  $("send-message").disabled = state.busy || !state.snapshot;
  const canSimulate = projection() && projection().status !== "unavailable" && state.info?.simulation_enabled;
  const allowed = projection()?.collaboration?.allowed_actions || [];
  const canReview = canSimulate && (!state.info?.collaboration_role || allowed.includes("run_event_review"));
  $("helmet-event").disabled = $("gas-event").disabled = state.busy || !canReview;
  $("helmet-event").hidden = $("gas-event").hidden = $("run-review").hidden = !!state.info?.collaboration_role && !canReview;
  $("run-review").disabled = state.busy || !state.event || !canReview;
  const canFeedback = !state.info?.collaboration_role || allowed.includes("record_event_feedback");
  $("send-feedback").hidden = !canFeedback; $("feedback-panel").hidden = !state.review || !canFeedback;
  $("send-feedback").disabled = state.busy || !state.review || !canFeedback;
  document.querySelectorAll(".collaboration-actions button, .application-list button").forEach(button => button.disabled = state.busy);
}

async function action(work) {
  if (state.busy) return;
  state.busy = true; clearNotices(); updateButtons();
  try { await work(); }
  catch (error) {
    if (error.stale) return;
    showNotice(error instanceof ApiError ? error.message : "操作未完成，请刷新核对服务端状态。", true);
    if (error.status === 401) disconnect();
  } finally { state.busy = false; updateButtons(); }
}

function renderMode() {
  if (!state.info) { text("model-mode", "连接后读取模型模式"); return; }
  const mode = state.info.model_mode === "deepseek_live" ? `DeepSeek · ${state.info.model}` : "脚本替身（仅验证控制流）";
  const credentialMode = state.info.demo_short_token ? " · 演示短口令（弱安全，勿用于真实数据）" : "";
  const quotaMode = state.info.budget?.status === "audit_only" ? " · 项目调用次数不限（保留记录）" : "";
  text("model-mode", `${mode} · SYNTHETIC · 不提供作业批准${credentialMode}${quotaMode}`);
}

function conversationTitle(snapshot) {
  const first = snapshot.messages?.find(message => message.role === "user")?.text;
  return first ? (first.length > 22 ? first.slice(0, 22) + "…" : first) : "新会话";
}

function renderConversationList() {
  const target = $("conversation-list"); target.replaceChildren();
  if (!state.conversations.length) { target.append(node("p", "暂无会话。", "muted")); return; }
  for (const conversation of state.conversations) {
    const button = node("button", undefined, "conversation-item" + (conversation.conversation_id === state.snapshot?.conversation_id ? " active" : ""));
    button.type = "button";
    button.append(node("span", conversationTitle(conversation)), node("small", `${statuses[conversation.status] || conversation.status} · r${conversation.revision}`));
    button.addEventListener("click", () => action(() => selectConversation(conversation.conversation_id)));
    target.append(button);
  }
  updateButtons();
}

function messageBubble(message) {
  const item = node("li", undefined, `message-row ${message.role}`);
  const bubble = node("div", message.text, "bubble");
  bubble.append(node("small", message.role === "user" ? "你" : message.role === "assistant" ? "安澜" : "系统"));
  if (message.status === "failed") bubble.append(node("span", "发送已保存，但处理失败，可刷新后重试。", "message-state"));
  item.append(bubble); return item;
}

function renderConfirmation(target) {
  const pending = state.snapshot?.pending_intent;
  if (!pending) return;
  const item = node("li", undefined, "message-row assistant");
  const card = node("div", undefined, "confirmation-card");
  card.append(node("strong", pending.kind === "switch_or_create_task" ? "选择任务去向" : "请确认安澜的理解"));
  const fields = Object.entries(pending.fields || {});
  if (pending.collaboration) {
    const frozen = pending.collaboration, body = frozen.payload;
    card.append(node("p", `${businessLabels[frozen.action]} · ${frozen.task_id}`));
    card.append(node("p", `申请版本 ${body.expected_application_version} / 材料版本 ${body.expected_material_revision}`));
    if (body.expected_binding_revision || body.expected_check_id) card.append(node("p", `绑定版本 ${body.expected_binding_revision ?? "未提供"} / 预核查 ${body.expected_check_id ?? "未提供"}`));
    if (body.applied_knowledge_citation_ids?.length) card.append(node("p", `人工采用引用：${body.applied_knowledge_citation_ids.join("、")}`));
    for (const key of ["reviewer_user_id", "questions", "reply", "conclusion"]) if (body[key]) card.append(node("p", Array.isArray(body[key]) ? body[key].join("；") : body[key]));
  }
  if (fields.length) {
    const list = node("dl");
    for (const [name, value] of fields) { list.append(node("dt", labels[name] || name), node("dd", value)); }
    card.append(list);
  } else if (!pending.collaboration) card.append(node("p", "当前候选没有可展示的结构化字段，请核对对话内容。", "muted"));
  const actions = node("div", undefined, "card-actions");
  const confirm = node("button", pending.kind === "switch_or_create_task" ? "新建另一项任务" : "确认申请", "primary"); confirm.type = "button";
  const reject = node("button", "不是，继续聊", "quiet"); reject.type = "button";
  if (pending.collaboration) confirm.textContent = "确认";
  confirm.addEventListener("click", () => action(() => sendText(confirm.textContent)));
  reject.addEventListener("click", () => action(() => sendText(reject.textContent)));
  actions.append(confirm, reject); card.append(actions); item.append(card); target.append(item);
}

function renderMessages() {
  const target = $("message-list"); target.replaceChildren();
  const messages = state.snapshot?.messages || [];
  if (!messages.length) {
    const empty = node("li", undefined, "welcome");
    const manager = state.info?.collaboration_role === "safety_manager";
    empty.append(node("strong", manager ? "从分配待办开始" : "从一句自然语言开始"), node("p", manager ? "选择分配给本人的申请，核对共享材料并提出补充要求或完成人工材料核查。这里的私聊仅本人可见。" : "我会区分普通对话与动火申请；创建任务前一定请你确认。"));
    target.append(empty);
  } else messages.forEach(message => target.append(messageBubble(message)));
  for (const event of state.snapshot?.business_messages || []) {
    const item = node("li", undefined, "message-row system_event");
    item.dataset.eventId = event.event_id; item.append(businessCard(event)); target.append(item);
  }
  renderConfirmation(target);
  requestAnimationFrame(() => { target.scrollTop = target.scrollHeight; });
}

function taskAction(label, value, variant="quiet") {
  const button = node("button", label, variant); button.type = "button";
  button.addEventListener("click", () => action(() => sendText(value))); return button;
}

function renderTaskProjection() {
  const target = $("task-projection"), actions = $("task-actions"), task = projection();
  target.replaceChildren(); actions.replaceChildren();
  $("collaboration-actions").replaceChildren(); $("business-timeline").replaceChildren();
  if (!task) {
    setPill("task-summary", state.snapshot?.status === "pending_confirmation" ? "等待确认" : "未绑定", state.snapshot?.status === "pending_confirmation" ? "warn" : "");
    target.append(node("p", "对话确认后，任务状态会显示在这里。", "empty"));
    renderEvents(); return;
  }
  if (task.status === "unavailable") {
    setPill("task-summary", "暂不可用", "warn");
    target.append(node("p", "任务快照暂不可用；任务标识和对话消息已保留，请刷新恢复。", "warning"));
    target.append(node("code", task.task_id)); renderEvents(); return;
  }
  setPill("task-summary", applicationStatuses[task.collaboration?.application?.status] || statuses[task.status] || task.status, task.status === "waiting_input" ? "warn" : "good");
  const heading = node("div", undefined, "task-heading"); heading.append(node("strong", "动火材料任务"), node("span", `v${task.revision}`, "pill")); target.append(heading);
  target.append(node("code", task.task_id));
  const fieldList = node("dl", undefined, "field-list");
  for (const [name, value] of Object.entries(task.fields || {})) fieldList.append(node("dt", labels[name] || name), node("dd", value));
  target.append(fieldList);
  if (task.missing_fields?.length) target.append(node("p", "待补充：" + task.missing_fields.map(name => labels[name] || name).join("、"), "warning"));
  for (const question of task.issue_questions || []) target.append(node("p", question, "question"));
  const meta = node("div", undefined, "task-meta");
  if (task.collaboration) {
    const analysisLabel = task.semantic_status === "failed" ? "材料分析未完成，请核对后重试" : task.semantic_status === "shared_materials" ? "共享材料供人工核对，分析详情由申请人本人查看" : task.semantic_status === "offline_not_checked" ? "离线示例：未做模型语义核查" : task.issue_questions?.length ? "材料仍需澄清，请补充具体信息" : "材料语义核查已完成，仍需人工核对";
    meta.append(node("span", analysisLabel), node("span", "事件与核查结果见下方详情"));
  }
  else meta.append(node("span", `分析：${task.analysis_mode}`), node("span", `语义：${task.semantic_status}`), node("span", `事件 ${task.event_count || 0}`), node("span", `核查 ${task.review_count || 0}`)); target.append(meta);
  if (state.snapshot.status === "active_hot_work") actions.append(taskAction("暂停引导", "暂停当前任务"), taskAction("取消引导", "取消当前任务"));
  if (state.snapshot.status === "paused") actions.append(taskAction("恢复引导", "继续任务", "primary"), taskAction("取消引导", "取消当前任务"));
  if (state.info?.collaboration_role !== "safety_manager") actions.append(taskAction("发起另一项", "我要发起另一项动火任务"));
  renderCollaboration(task);
  updateButtons();
}

function renderSnapshot() {
  if (!state.snapshot) return;
  text("conversation-title", conversationTitle(state.snapshot));
  renderMessages(); renderTaskProjection(); renderConversationList();
}

function snapshotKey(snapshot) {
  return JSON.stringify(snapshot, (_key, value) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]]));
    }
    return value;
  });
}

async function refreshConversation({quiet=false}={}) {
  if (!state.snapshot) return;
  const selected = state.snapshot;
  const latest = await request(`/conversations/${selected.conversation_id}`);
  if (state.snapshot !== selected) return;
  if (snapshotKey(latest) !== snapshotKey(state.snapshot)) { state.snapshot = latest; renderSnapshot(); }
  await loadEvents();
  if (!quiet) showNotice("已读取服务端最新会话和任务快照。");
}

function startStream(conversationId) {
  state.stream?.abort(); state.stream = null; state.streamId = null;
  // Collaboration already polls authenticated snapshots/inbox every three seconds.
  // A second fast reader competes for the same task lock and causes transient card churn.
  if (state.info?.collaboration_role) return;
  const controller = new AbortController(); state.stream = controller;
  subscribeSnapshot(`/conversations/${conversationId}/stream`, {
    signal: controller.signal,
    onSnapshot(snapshot, id) {
      if (snapshot.conversation_id !== state.snapshot?.conversation_id) return;
      state.streamId = id;
      if (snapshotKey(snapshot) !== snapshotKey(state.snapshot)) { state.snapshot = snapshot; renderSnapshot(); }
    },
    onError(error) { if (!controller.signal.aborted) showNotice(error.message, true); },
  });
}

async function selectConversation(conversationId) {
  state.snapshot = await request(`/conversations/${conversationId}`);
  state.events = []; state.event = state.review = null; state.reviews = [];
  renderSnapshot(); await loadEvents(); startStream(conversationId);
}

async function loadConversations(preferredId=null) {
  state.conversations = await request("/conversations");
  renderConversationList();
  const selected = preferredId || state.snapshot?.conversation_id || state.conversations[0]?.conversation_id;
  if (selected) await selectConversation(selected);
}

async function createConversation() {
  const created = await mutate("/conversations");
  await loadConversations(created.conversation_id); $("message-input").focus();
}

async function sendText(value) {
  const input = $("message-input"), draft = value.trim();
  if (!draft || !state.snapshot) return;
  const result = await mutate(`/conversations/${state.snapshot.conversation_id}/messages`, {expected_revision:state.snapshot.revision, text:draft});
  if (result.error_category) {
    await refreshConversation({quiet:true});
    input.value = draft;
    throw new ApiError("消息已保留，但本次处理未完成。请核对快照后重试。", 503);
  }
  state.snapshot = result;
  if (input.value.trim() === draft) input.value = "";
  const found = state.conversations.findIndex(item => item.conversation_id === result.conversation_id);
  if (found >= 0) state.conversations[found] = result; else state.conversations.unshift(result);
  renderSnapshot(); await loadEvents();
}

async function loadEvents() {
  const taskId = projection()?.task_id;
  const events = taskId ? (await request(`/console/api/tasks/${taskId}/events`)).items : [];
  if (projection()?.task_id !== taskId) return;
  state.events = events;
  if (state.event) state.event = state.events.find(item => item.receipt_id === state.event.receipt_id) || null;
  if (!state.event) { state.review = null; state.reviews = []; }
  else {
    const receiptId = state.event.receipt_id, previousReviewId = state.review?.review_id;
    const reviews = (await request(`/console/api/events/${receiptId}/reviews`)).items;
    if (projection()?.task_id !== taskId || state.event?.receipt_id !== receiptId || state.review?.review_id !== previousReviewId) return;
    const selected = reviews.find(item => item.review_id === previousReviewId) || reviews[0];
    const review = selected ? await request(`/reviews/${selected.review_id}`) : null;
    if (projection()?.task_id !== taskId || state.event?.receipt_id !== receiptId || state.review?.review_id !== previousReviewId) return;
    state.reviews = reviews; state.review = review;
  }
  renderEvents(); renderReview();
}

function renderEvents() {
  const target = $("event-list"); target.replaceChildren();
  if (!state.events.length) { target.append(node("p", projection() ? "暂无事件。" : "绑定任务后加载事件。", "empty")); updateButtons(); return; }
  for (const event of state.events) {
    const button = node("button", undefined, "event-item" + (event.receipt_id === state.event?.receipt_id ? " active" : "")); button.type = "button";
    button.append(node("strong", kinds[event.raw.kind] || event.raw.kind), node("small", `原始报警：${event.raw.alarm_state} · 材料 v${event.binding.revision}`));
    button.addEventListener("click", () => action(() => chooseEvent(event.receipt_id))); target.append(button);
  }
  updateButtons();
}

async function chooseEvent(receiptId, preferredReview=null) {
  state.event = state.events.find(item => item.receipt_id === receiptId) || await request(`/events/${receiptId}`);
  state.reviews = (await request(`/console/api/events/${receiptId}/reviews`)).items;
  const selected = state.reviews.find(item => item.review_id === preferredReview) || state.reviews[0];
  state.review = selected ? await request(`/reviews/${selected.review_id}`) : null;
  renderEvents(); renderReview();
}

function renderReview() {
  const target = $("review-result"); target.replaceChildren(); $("feedback-panel").hidden = !state.review;
  if (!state.event) { target.append(node("p", "选择事件并发起核查。", "empty")); updateButtons(); return; }
  target.append(node("p", `${kinds[state.event.raw.kind] || state.event.raw.kind} · 原始报警 ${state.event.raw.alarm_state}`, "warning"));
  if (!state.review) { target.append(node("p", "尚无核查记录。", "empty")); updateButtons(); return; }
  const report = state.review.result?.report;
  target.append(node("p", `核查状态：${statuses[state.review.result?.status] || state.review.result?.status} · ${statuses[state.review.currentness] || state.review.currentness}`));
  for (const concern of report?.candidate?.concerns || []) target.append(node("p", `关注项：${concern.category} · ${concern.evidence_ids.join(" / ")}`, "question"));
  for (const observation of report?.observations || []) target.append(node("p", `依据：${observation.tool} · ${observation.outcome}`, "muted"));
  text("feedback-status", state.review.feedback ? `已保存：${state.review.feedback.decision}` : "反馈只记录人工意见，不改变原始报警。");
  if (state.review.feedback) $("feedback-decision").value = state.review.feedback.decision;
  updateButtons();
}

function disconnect() {
  resetIdentityState();
  disconnectToken(); $("token").value = ""; $("config-file").value = ""; $("connect-panel").hidden = false; $("workbench").hidden = true; $("disconnect").hidden = true;
  setPill("connection-status", "未连接"); text("identity", ""); $("conversation-list").replaceChildren(node("p", "连接后加载会话", "muted")); renderMode();
}

async function connect(value) {
  if (!value || !/^[A-Za-z0-9._~-]{7,256}$/.test(value)) throw new ApiError("请选择有效演示配置或输入测试令牌。短口令须由服务端显式启用。", 422);
  resetIdentityState(); connectToken(value);
  try { state.info = await request("/console/api/info"); } catch (error) { disconnectToken(); state.info = null; throw error; }
  $("token").value = ""; $("connect-panel").hidden = true; $("workbench").hidden = false; $("disconnect").hidden = false;
  setPill("connection-status", "已连接", "good"); text("identity", `${state.info.identity.tenant_id} / ${state.info.identity.user_id}`); renderMode();
  text("trusted-role", {applicant:"申请人（演示身份）", safety_manager:"安全人员（演示身份）"}[state.info.collaboration_role] || "原私有身份");
  $("message-input").placeholder = state.info.collaboration_role === "safety_manager" ? "选择本人待办后，可以讨论材料或提出补充要求" : "例如：明天去罐区补焊";
  text("application-heading", state.info.collaboration_role === "safety_manager" ? "分配给我的待办" : "我的申请");
  await loadConversations(); if (!state.conversations.length) await createConversation();
  await refreshBusiness(); scheduleBusinessPoll();
}

function resetIdentityState() {
  state.epoch++; state.stream?.abort(); clearTimeout(state.pollTimer);
  state.stream = state.streamId = state.pollTimer = null;
  state.info = state.snapshot = state.event = state.review = null;
  state.conversations = []; state.events = []; state.reviews = []; state.applications = [];
  state.notifications.clear(); state.notificationCursor = 0; state.businessDrafts.clear(); state.preflightCatalogs.clear(); state.preflightDrafts.clear();
  for (const id of ["application-list", "business-inbox", "business-timeline", "message-list", "collaboration-actions", "task-projection", "task-actions", "event-list", "review-result", "conversation-list"]) $(id).replaceChildren();
  $("message-input").value = ""; text("trusted-role", ""); clearNotices();
}

function businessCard(event) {
  const card = node("div", undefined, "business-card"); card.dataset.eventId = event.event_id;
  card.append(node("strong", businessLabels[event.action] || event.action), node("small", ` · ${event.actor_user_id} · 材料 v${event.material_revision}`));
  for (const value of Object.values(event.payload || {})) card.append(node("p", Array.isArray(value) ? value.join("；") : String(value)));
  return card;
}

function renderCollaboration(task) {
  const shared = task.collaboration; if (!shared) return;
  const app = shared.application;
  $("task-projection").append(node("p", `${applicationStatuses[app.status]} · 申请版本 ${app.version} · 核查人 ${app.reviewer_user_id || "待选择"}`));
  renderPreflight(task, shared);
  for (const event of shared.events || []) $("business-timeline").append(businessCard(event));
  const candidates = {submit:["submit_application", "提交给安全人员"], request_changes:["request_changes", "提出补充要求"], resubmit:["resubmit_application", "重新提交申请"], complete_review:["complete_material_review", "完成人工材料核查"]};
  for (const name of shared.allowed_actions || []) {
    if (name === "complete_review" && shared.precheck?.required) continue;
    if (!candidates[name]) continue;
    const [intent, label] = candidates[name], form = node("form");
    const input = node(name === "submit" ? "select" : "textarea"); input.required = true;
    input.setAttribute("aria-label", label); input.maxLength = 500;
    if (name === "submit") for (const user of state.info.collaboration_reviewers || []) { const option = node("option", user); option.value = user; input.append(option); }
    else input.placeholder = name === "request_changes" ? "填写具体补充要求，每行一条" : "填写本轮说明";
    const draftKey = `${task.task_id}:${name}`;
    if (state.businessDrafts.has(draftKey)) input.value = state.businessDrafts.get(draftKey);
    input.addEventListener("input", () => state.businessDrafts.set(draftKey, input.value));
    const button = node("button", label + "（先确认）", "secondary"); button.type = "submit";
    form.append(input, button); form.addEventListener("submit", event => { event.preventDefault(); action(async () => {
      const detail = name === "submit" ? {reviewer_user_id:input.value} : name === "request_changes" ? {questions:input.value.split(/\n/).filter(s => s.trim())} : name === "resubmit" ? {reply:input.value} : {conclusion:input.value};
      state.snapshot = await mutate(`/conversations/${state.snapshot.conversation_id}/collaboration-candidates`, {expected_revision:state.snapshot.revision, intent, collaboration:detail}); state.businessDrafts.delete(draftKey); renderSnapshot();
    }); }); $("collaboration-actions").append(form);
  }
}

function renderPreflight(task, shared) {
  const precheck = shared.precheck || {}, app = shared.application, evidence = precheck.evidence;
  const card = node("section", undefined, "preflight-card");
  if (precheck.legacy_completed) {
    card.append(node("h3", "作业前依据"), node("p", "历史材料核查：未执行本版作业前预核查。", "muted"));
    $("task-projection").append(card); return;
  }
  const failed = precheck.execution_status === "failed", label = failed ? "核查执行失败" : ({unbound:"待确认对象", not_checked:"待核查", queued:"核查排队中", running:"核查中", ready:"依据可供人工核对", gap:"依据有缺口", stale:"依据已过时"}[precheck.status] || precheck.status || "待核查");
  card.append(node("h3", "作业前依据"), node("p", `${label} · ${precheck.current ? "当前" : "非当前"}${precheck.stale ? " · 输入或来源已变" : ""}`, precheck.status === "ready" ? "good" : "warning"));
  card.append(node("p", `查谁/哪个区域：绑定 v${precheck.binding_revision ?? "未确认"} · 材料 v${task.revision} · 核查 ${precheck.check_id || "尚未产生"}`));
  if (precheck.binding?.references) { const refs = precheck.binding.references, labels = precheck.binding.labels || {}; card.append(node("p", `人员 ${labels.worker || refs.worker_id}（${refs.worker_id}）· 资质 ${labels.qualification || refs.qualification_type}（${refs.qualification_type}）· 区域 ${labels.area || refs.area_id}（${refs.area_id}）`, "muted")); }
  card.append(node("p", `查询时间：${evidence?.queried_at || precheck.as_of || "服务端实时钟"}（${precheck.clock_mode === "fixed_replay" ? "合成固定时钟" : "服务端时钟"}）· 有效至 ${evidence?.valid_until || "尚未取得"}`, "muted"));
  if (failed) card.append(node("p", `来源查询失败：${(precheck.issues || ["source_unavailable"]).join("、")}；请核对来源后显式重查。`, "warning"));
  else if (precheck.issues?.length) card.append(node("p", `缺口/异常：${precheck.issues.join("、")}`, "warning"));
  if (evidence) {
    for (const [key, title] of [["worker", "人员资质"], ["area", "区域状态"]]) { const value = evidence[key] || {}, facts = value.facts || {}; card.append(node("p", `${title}：查询 ${value.outcome || "unknown"} · 业务状态 ${facts.status || "未知"} · 来源 ${value.source?.version || "未提供"} · 观察 ${value.source?.observed_at || "未提供"} · 有效至 ${value.source?.valid_until || "未提供"}`, facts.status === "active" || facts.status === "normal" ? "muted" : "warning")); }
    const citations = evidence.knowledge?.citations || [];
    for (const citation of citations) card.append(node("p", `知识：${citation.quote || citation.chunk_id} · 来源 ${citation.source || "未提供"} · v${citation.version || "?"} · ${citation.chunk_id}`, "muted"));
    if (!citations.length) card.append(node("p", "没有当前知识引用；不能以文字补造。", "warning"));
  }
  const role = state.info?.collaboration_role, allowed = shared.allowed_actions || [];
  if (role === "applicant" && allowed.includes("edit_materials")) renderBinding(card, task, precheck);
  if ((role === "safety_manager" && app.status !== "review_completed") || (role === "applicant" && ["draft", "changes_requested"].includes(app.status))) {
    const recheck = node("button", "显式重查依据", "secondary"); recheck.type = "button"; recheck.disabled = !precheck.binding_revision;
    recheck.addEventListener("click", () => action(async () => { await mutate(`/collaboration/applications/${task.task_id}/prechecks`, {expected_material_revision:task.revision, expected_binding_revision:precheck.binding_revision, expected_application_version:app.version, reason:"本人请求重新核对当前合成依据"}); await refreshConversation({quiet:true}); })); card.append(recheck);
  }
  if (role === "safety_manager" && allowed.includes("complete_review") && precheck.current && precheck.status === "ready" && evidence?.citation_ids?.length) renderCitations(card, task, app, precheck, evidence);
  $("task-projection").append(card);
}
async function loadCatalog(taskId) { if (state.preflightCatalogs.has(taskId)) return; const epoch = state.epoch; try { const catalog = await request(`/collaboration/applications/${taskId}/object-catalog`); if (epoch === state.epoch && projection()?.task_id === taskId) { state.preflightCatalogs.set(taskId, catalog); renderSnapshot(); } } catch (error) { if (!error.stale) showNotice(error.message, true); } }
function renderBinding(card, task, precheck) { const catalog = state.preflightCatalogs.get(task.task_id); if (!catalog) { card.append(node("p", "正在读取当前身份的授权对象目录…", "muted")); queueMicrotask(() => loadCatalog(task.task_id)); return; } if (!catalog.workers?.length || !catalog.areas?.length) { card.append(node("p", "未配置或无授权对象；系统不会默认选择。", "warning")); return; } const key = `${task.task_id}:${task.revision}:${precheck.binding_revision || 0}`, draft = state.preflightDrafts.get(key)?.binding || {}, form = node("form"), worker = node("select"), type = node("select"), area = node("select"); const choose = (select, label) => { const option = node("option", label); option.value = ""; option.disabled = option.selected = true; select.append(option); select.required = true; }; choose(worker, "选择作业人员"); choose(area, "选择作业区域"); for (const value of catalog.workers) { const option = node("option", value.label); option.value = value.worker_id; worker.append(option); } for (const value of catalog.areas) { const option = node("option", value.label); option.value = value.area_id; area.append(option); } const fill = () => { type.replaceChildren(); choose(type, "选择资质类型"); for (const value of catalog.workers.find(item => item.worker_id === worker.value)?.qualification_types || []) { const option = node("option", value.label); option.value = value.qualification_type; type.append(option); } if (draft.qualification_type) type.value = draft.qualification_type; }; if (draft.worker_id) worker.value = draft.worker_id; if (draft.area_id) area.value = draft.area_id; worker.addEventListener("change", fill); fill(); for (const input of [worker, type, area]) input.addEventListener("input", () => state.preflightDrafts.set(key, {binding:{worker_id:worker.value, qualification_type:type.value, area_id:area.value}})); const submit = node("button", "确认本申请对象", "secondary"); submit.type = "submit"; form.append(worker, type, area, submit); form.addEventListener("submit", event => { event.preventDefault(); action(async () => { await mutate(`/collaboration/applications/${task.task_id}/binding`, {expected_material_revision:task.revision, expected_binding_revision:precheck.binding_revision || 0, worker_id:worker.value, qualification_type:type.value, area_id:area.value}); state.preflightDrafts.delete(key); await refreshConversation({quiet:true}); }); }); card.append(form); }
function renderCitations(card, task, app, precheck, evidence) { const form = node("form"), key = `${task.task_id}:${task.revision}:${precheck.binding_revision}:${precheck.check_id}`, draft = state.preflightDrafts.get(key)?.citation || {}; form.append(node("p", "请勾选本轮实际采用的知识引用；模型不会代选。")); for (const citation of evidence.citation_ids) { const label = node("label"), box = document.createElement("input"); box.type = "checkbox"; box.value = citation; box.checked = draft.citations?.includes(citation); box.addEventListener("change", () => state.preflightDrafts.set(key, {citation:{citations:Array.from(form.querySelectorAll("input:checked"), item => item.value), conclusion:conclusion.value}})); label.append(box, document.createTextNode(citation)); form.append(label); } const conclusion = node("textarea"); conclusion.required = true; conclusion.maxLength = 500; conclusion.placeholder = "填写人工适用性结论"; conclusion.value = draft.conclusion || ""; conclusion.addEventListener("input", () => state.preflightDrafts.set(key, {citation:{citations:Array.from(form.querySelectorAll("input:checked"), item => item.value), conclusion:conclusion.value}})); const submit = node("button", "冻结采用引用并确认", "primary"); submit.type = "submit"; form.append(conclusion, submit); form.addEventListener("submit", event => { event.preventDefault(); action(async () => { const citations = Array.from(form.querySelectorAll("input:checked"), item => item.value); if (!citations.length) throw new ApiError("请先勾选本轮实际采用的知识引用。", 422); state.snapshot = await mutate(`/conversations/${state.snapshot.conversation_id}/preflight-citation-candidates`, {expected_revision:state.snapshot.revision, expected_check_id:precheck.check_id, expected_material_revision:task.revision, expected_binding_revision:precheck.binding_revision, expected_application_version:app.version, conclusion:conclusion.value, applied_knowledge_citation_ids:citations}); state.preflightDrafts.delete(key); renderSnapshot(); }); }); card.append(form); }

async function refreshBusiness() {
  if (!state.info?.collaboration_role) return;
  const epoch = state.epoch;
  const [applications, inbox] = await Promise.all([request("/collaboration/applications"), request(`/collaboration/notifications?after=${state.notificationCursor}&limit=100`)]);
  if (epoch !== state.epoch) return;
  const applicationsChanged = JSON.stringify(state.applications) !== JSON.stringify(applications.items);
  state.applications = applications.items; state.notificationCursor = inbox.next_cursor;
  const visible = new Set(state.applications.map(app => app.task_id));
  for (const [key, event] of state.notifications) if (!visible.has(event.task_id)) state.notifications.delete(key);
  for (const item of inbox.items) state.notifications.set(item.event.event_id, item.event);
  while (state.notifications.size > 200) state.notifications.delete(state.notifications.keys().next().value);
  $("business-inbox").replaceChildren(...Array.from(state.notifications.values(), businessCard));
  if (applicationsChanged) $("application-list").replaceChildren();
  for (const app of applicationsChanged ? state.applications : []) {
    const button = node("button", undefined, "conversation-item"); button.type = "button";
    button.append(node("span", app.task_id), node("small", `${applicationStatuses[app.status]} · v${app.version}`));
    button.addEventListener("click", () => action(async () => {
      state.snapshot = await request(`/conversations/${state.snapshot.conversation_id}/task`, {method:"POST", body:{task_id:app.task_id, expected_revision:state.snapshot.revision}});
      state.events = []; state.event = state.review = null; state.reviews = []; renderSnapshot(); await loadEvents();
    })); $("application-list").append(button);
  }
  updateButtons();
}

function scheduleBusinessPoll() {
  const epoch = state.epoch; clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    if (epoch !== state.epoch || !state.info) return;
    try { if (!state.busy) { await refreshBusiness(); if (state.snapshot && state.info.collaboration_role) await refreshConversation({quiet:true}); } }
    catch (error) { if (!error.stale && epoch === state.epoch) showNotice(error.message, true); }
    if (epoch === state.epoch) scheduleBusinessPoll();
  }, 3000);
}

$("connect").addEventListener("click", () => action(() => connect($("token").value.trim())));
$("config-file").addEventListener("change", () => action(async () => {
  const file = $("config-file").files[0]; if (!file || file.size > 262144) throw new ApiError("配置文件无效或过大。", 422);
  let config; try { config = JSON.parse(await file.text()); } catch { throw new ApiError("配置文件不是有效 JSON。", 422); }
  if (config.schema_version !== "local-service-v1") throw new ApiError("请选择本地服务配置文件。", 422);
  const value = config.tokens?.[0]?.token; config = null; $("config-file").value = ""; await connect(value);
}));
$("disconnect").addEventListener("click", () => { if (!state.busy) disconnect(); });
$("new-conversation").addEventListener("click", () => action(createConversation));
$("refresh-conversation").addEventListener("click", () => action(refreshConversation));
$("message-composer").addEventListener("submit", event => { event.preventDefault(); action(() => sendText($("message-input").value)); });
$("message-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("message-composer").requestSubmit(); } });
for (const [id, kind] of [["helmet-event", "helmet_missing"], ["gas-event", "gas_abnormal"]]) $(id).addEventListener("click", () => action(async () => {
  const task = projection(); if (!task) return;
  const event = await mutate(`/console/api/tasks/${task.task_id}/events`, {expected_revision:task.revision, kind});
  await loadEvents(); await chooseEvent(event.receipt_id); showNotice("合成事件已保存；原始报警保持 active。");
}));
$("run-review").addEventListener("click", () => action(async () => {
  const review = await mutate(`/console/api/events/${state.event.receipt_id}/reviews`);
  await loadEvents(); await chooseEvent(state.event.receipt_id, review.review_id); showNotice("核查已完成，请查看依据并记录人工反馈。");
}));
$("send-feedback").addEventListener("click", () => action(async () => {
  await mutate(`/reviews/${state.review.review_id}/feedback`, {expected_revision:state.review.revision, decision:$("feedback-decision").value});
  await chooseEvent(state.event.receipt_id, state.review.review_id); showNotice("人工反馈已保存；原始报警保持不变。");
}));
updateButtons();
