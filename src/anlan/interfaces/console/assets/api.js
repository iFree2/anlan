// Credential and retry intents live only in this module's memory.
let token = "";
const intents = new Map();
const modulePath = new URL(import.meta.url).pathname;
const apiPrefix = modulePath.slice(0, modulePath.lastIndexOf("/console/assets/api.js"));
export function connectToken(value) { token = value; intents.clear(); }
export function disconnectToken() { token = ""; intents.clear(); }
export class ApiError extends Error {
  constructor(message, status, taskId = null) {
    super(message); this.status = status; this.taskId = taskId;
  }
}
export async function request(path, {method = "GET", body} = {}) {
  if (!token) throw new ApiError("请先连接本地服务。", 401);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(apiPrefix + path, {
      method, credentials: "omit", cache: "no-store", signal: controller.signal,
      headers: {Authorization: "Bearer " + token, ...(body ? {"Content-Type": "application/json"} : {})},
      ...(body ? {body: JSON.stringify(body)} : {}),
    });
    const result = await response.json();
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
    if (error instanceof ApiError) throw error;
    throw new ApiError("连接中断或请求超时，结果可能已保存。请刷新核对，或使用相同输入再次提交；不会自动重发。", 0);
  } finally { clearTimeout(timeout); }
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
