import {connectToken, disconnectToken, request, mutate, subscribeSnapshot, ApiError} from "./api.js";

const $ = id => document.getElementById(id);
const labels = {work_location_description:"作业位置", work_object_description:"作业对象", work_method_description:"作业方式", attachment_description:"附件说明"};
const statuses = {idle:"空闲", pending_confirmation:"等待确认", active_hot_work:"任务进行中", paused:"已暂停", waiting_input:"待补充材料", awaiting_review:"待人工复核", analyzing:"分析中", completed:"核查完成", failed:"核查失败", current:"当前有效", stale_material:"材料已变化"};
const kinds = {helmet_missing:"未戴安全帽", gas_abnormal:"气体浓度异常"};
const state = {info:null, conversations:[], snapshot:null, busy:false, stream:null, streamId:null, events:[], event:null, reviews:[], review:null};

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
  $("helmet-event").disabled = $("gas-event").disabled = state.busy || !canSimulate;
  $("run-review").disabled = state.busy || !state.event || !state.info?.simulation_enabled;
  $("send-feedback").disabled = state.busy || !state.review;
}

async function action(work) {
  if (state.busy) return;
  state.busy = true; clearNotices(); updateButtons();
  try { await work(); }
  catch (error) {
    showNotice(error instanceof ApiError ? error.message : "操作未完成，请刷新核对服务端状态。", true);
    if (error.status === 401) disconnect();
  } finally { state.busy = false; updateButtons(); }
}

function renderMode() {
  if (!state.info) { text("model-mode", "连接后读取模型模式"); return; }
  const mode = state.info.model_mode === "deepseek_live" ? `DeepSeek · ${state.info.model}` : "脚本替身（仅验证控制流）";
  text("model-mode", `${mode} · SYNTHETIC · 不提供作业批准`);
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
  if (fields.length) {
    const list = node("dl");
    for (const [name, value] of fields) { list.append(node("dt", labels[name] || name), node("dd", value)); }
    card.append(list);
  } else card.append(node("p", "当前候选没有可展示的结构化字段，请核对对话内容。", "muted"));
  const actions = node("div", undefined, "card-actions");
  const confirm = node("button", pending.kind === "switch_or_create_task" ? "新建另一项任务" : "确认申请", "primary"); confirm.type = "button";
  const reject = node("button", "不是，继续聊", "quiet"); reject.type = "button";
  confirm.addEventListener("click", () => action(() => sendText(confirm.textContent)));
  reject.addEventListener("click", () => action(() => sendText(reject.textContent)));
  actions.append(confirm, reject); card.append(actions); item.append(card); target.append(item);
}

function renderMessages() {
  const target = $("message-list"); target.replaceChildren();
  const messages = state.snapshot?.messages || [];
  if (!messages.length) {
    const empty = node("li", undefined, "welcome");
    empty.append(node("strong", "从一句自然语言开始"), node("p", "我会区分普通对话与动火申请；创建任务前一定请你确认。"));
    target.append(empty);
  } else messages.forEach(message => target.append(messageBubble(message)));
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
  setPill("task-summary", statuses[task.status] || task.status, task.status === "waiting_input" ? "warn" : "good");
  const heading = node("div", undefined, "task-heading"); heading.append(node("strong", "动火材料任务"), node("span", `v${task.revision}`, "pill")); target.append(heading);
  target.append(node("code", task.task_id));
  const fieldList = node("dl", undefined, "field-list");
  for (const [name, value] of Object.entries(task.fields || {})) fieldList.append(node("dt", labels[name] || name), node("dd", value));
  target.append(fieldList);
  if (task.missing_fields?.length) target.append(node("p", "待补充：" + task.missing_fields.map(name => labels[name] || name).join("、"), "warning"));
  for (const question of task.issue_questions || []) target.append(node("p", question, "question"));
  const meta = node("div", undefined, "task-meta");
  meta.append(node("span", `分析：${task.analysis_mode}`), node("span", `语义：${task.semantic_status}`), node("span", `事件 ${task.event_count || 0}`), node("span", `核查 ${task.review_count || 0}`)); target.append(meta);
  if (state.snapshot.status === "active_hot_work") actions.append(taskAction("暂停引导", "暂停当前任务"), taskAction("取消引导", "取消当前任务"));
  if (state.snapshot.status === "paused") actions.append(taskAction("恢复引导", "继续任务", "primary"), taskAction("取消引导", "取消当前任务"));
  actions.append(taskAction("发起另一项", "我要发起另一项动火任务"));
  updateButtons();
}

function renderSnapshot() {
  if (!state.snapshot) return;
  text("conversation-title", conversationTitle(state.snapshot));
  renderMessages(); renderTaskProjection(); renderConversationList();
}

async function refreshConversation({quiet=false}={}) {
  if (!state.snapshot) return;
  state.snapshot = await request(`/conversations/${state.snapshot.conversation_id}`);
  renderSnapshot(); await loadEvents();
  if (!quiet) showNotice("已读取服务端最新会话和任务快照。");
}

function startStream(conversationId) {
  state.stream?.abort(); const controller = new AbortController(); state.stream = controller;
  subscribeSnapshot(`/conversations/${conversationId}/stream`, {
    signal: controller.signal,
    onSnapshot(snapshot, id) {
      if (snapshot.conversation_id !== state.snapshot?.conversation_id) return;
      state.streamId = id; state.snapshot = snapshot; renderSnapshot();
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
  state.events = projection()?.task_id ? (await request(`/console/api/tasks/${projection().task_id}/events`)).items : [];
  if (state.event) state.event = state.events.find(item => item.receipt_id === state.event.receipt_id) || null;
  if (!state.event) { state.review = null; state.reviews = []; }
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
  state.stream?.abort(); state.stream = null; state.info = state.snapshot = null; state.conversations = []; state.events = []; state.event = state.review = null; state.reviews = [];
  disconnectToken(); $("token").value = ""; $("config-file").value = ""; $("connect-panel").hidden = false; $("workbench").hidden = true; $("disconnect").hidden = true;
  setPill("connection-status", "未连接"); text("identity", ""); $("conversation-list").replaceChildren(node("p", "连接后加载会话", "muted")); renderMode();
}

async function connect(value) {
  if (!value || !/^[A-Za-z0-9._~-]{32,256}$/.test(value)) throw new ApiError("请选择有效演示配置或输入测试令牌。", 422);
  connectToken(value);
  try { state.info = await request("/console/api/info"); } catch (error) { disconnectToken(); state.info = null; throw error; }
  $("token").value = ""; $("connect-panel").hidden = true; $("workbench").hidden = false; $("disconnect").hidden = false;
  setPill("connection-status", "已连接", "good"); text("identity", `${state.info.identity.tenant_id} / ${state.info.identity.user_id}`); renderMode();
  await loadConversations(); if (!state.conversations.length) await createConversation();
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
