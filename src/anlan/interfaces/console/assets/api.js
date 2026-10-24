// Credential and retry intents live only in this module's memory.
let token = "";
let connectionEpoch = 0;
const controllers = new Set();
const intents = new Map();
const modulePath = new URL(import.meta.url).pathname;
const apiPrefix = modulePath.slice(0, modulePath.lastIndexOf("/console/assets/api.js"));
function clearConnection() { connectionEpoch++; for (const controller of controllers) controller.abort(); controllers.clear(); intents.clear(); }
export function connectToken(value) { clearConnection(); token = value; }
export function disconnectToken() { clearConnection(); token = ""; }
export class ApiError extends Error {
  constructor(message, status, taskId = null) {
    super(message); this.status = status; this.taskId = taskId;
  }
}
export async function request(path, {method = "GET", body} = {}) {
  if (!token) throw new ApiError("请先连接本地服务。", 401);
  const controller = new AbortController();
  const epoch = connectionEpoch; controllers.add(controller);
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(apiPrefix + path, {
      method, credentials: "omit", cache: "no-store", signal: controller.signal,
      headers: {Authorization: "Bearer " + token, ...(body ? {"Content-Type": "application/json"} : {})},
      ...(body ? {body: JSON.stringify(body)} : {}),
    });
    const result = await response.json();
    if (epoch !== connectionEpoch) { const error = new ApiError("连接身份已变化。", 0); error.stale = true; throw error; }
    if (!response.ok) {
      const messages = {
        401: "访问令牌无效或已失效，请重新连接。",
        404: "记录不存在，或当前身份没有访问/模拟权限。",
        409: "材料、事件或反馈版本已变化，或任务仍在执行。请刷新后核对，不会自动重试。",
        422: "输入格式无效，请检查字段。",
        503: "本地服务或数据库暂时不可用；已有记录保持在服务端。",
      };
      const taskId = typeof result.task_id === "string" && /^[A-Za-z0-9._:-]{1,100}$/.test(result.task_id) ? result.task_id : null;
      throw new ApiError(messages[response.status] || "请求失败，请检查本地服务。", response.status, taskId);
    }
    return result;
  } catch (error) {
    if (epoch !== connectionEpoch) { const stale = new ApiError("连接身份已变化。", 0); stale.stale = true; throw stale; }
    if (error instanceof ApiError) throw error;
    throw new ApiError("连接中断或请求超时，结果可能已保存。请刷新核对，或使用相同输入再次提交；不会自动重发。", 0);
  } finally { clearTimeout(timeout); controllers.delete(controller); }
}
export async function mutate(path, fields = {}) {
  const key = JSON.stringify([path, fields]);
  if (!intents.has(key)) {
    // getRandomValues also works on an IP-based HTTP learning deployment.
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    intents.set(key, Array.from(bytes, b => b.toString(16).padStart(2, "0")).join(""));
  }
  try {
    const result = await request(path, {method: "POST", body: {...fields, request_id: intents.get(key)}});
    intents.delete(key);
    return result;
  } catch (error) {
    if (error.status && error.status !== 409 && error.status !== 503) intents.delete(key);
    throw error;
  }
}

export async function subscribeSnapshot(path, {onSnapshot, onError, signal, lastEventId} = {}) {
  if (!token) throw new ApiError("请先连接本地服务。", 401);
  const headers = {Authorization: "Bearer " + token, Accept: "text/event-stream"};
  if (lastEventId) headers["Last-Event-ID"] = lastEventId;
  const epoch = connectionEpoch, controller = new AbortController(); controllers.add(controller);
  const abort = () => controller.abort(); signal?.addEventListener("abort", abort, {once:true});
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(apiPrefix + path, {
      method: "GET", credentials: "omit", cache: "no-store", headers, signal:controller.signal,
    });
    if (!response.ok || !response.body) throw new ApiError("会话更新流暂时不可用。", response.status);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {value, done} = await reader.read();
      if (epoch !== connectionEpoch || controller.signal.aborted) break;
      if (done) break;
      buffer += decoder.decode(value, {stream: true}).replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        if (!block || block.startsWith(":")) continue;
        let event = "message", id = ""; const data = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("id:")) id = line.slice(3).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        if (event === "snapshot") onSnapshot?.(JSON.parse(data.join("\n")), id);
        else if (event === "error") onError?.(new ApiError("会话快照暂时不可用，请手动刷新。", 503));
      }
    }
  } catch (error) {
    if (error?.name === "AbortError" || epoch !== connectionEpoch) return;
    onError?.(error instanceof ApiError ? error : new ApiError("会话更新连接已中断，请手动刷新。", 0));
  } finally { controllers.delete(controller); signal?.removeEventListener("abort", abort); }
}
