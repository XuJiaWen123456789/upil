/* uPil 客服演示页：使用原生 Fetch 读取 POST SSE，避免引入额外前端依赖。 */

const elements = {
  form: document.querySelector("#chat-form"), question: document.querySelector("#question"), send: document.querySelector("#send-button"),
  messages: document.querySelector("#messages"), conversation: document.querySelector("#conversation-id"), newConversation: document.querySelector("#new-conversation"),
  debug: document.querySelector("#debug-mode"), demoLearnerField: document.querySelector("#demo-learner-field"), demoLearner: document.querySelector("#demo-learner-id"), modeLabel: document.querySelector("#mode-label"), status: document.querySelector("#connection-status"),
  route: document.querySelector("#metric-route"), provider: document.querySelector("#metric-provider"), recognition: document.querySelector("#metric-recognition"),
  duration: document.querySelector("#metric-duration"), timeline: document.querySelector("#event-timeline"), sources: document.querySelector("#source-output"), debugPanel: document.querySelector("#debug-panel"),
};

let activeController = null;

/** 生成只用于演示会话关联的前端 ID，不携带用户信息。 */
function createConversationId() {
  const suffix = window.crypto?.randomUUID?.() || String(Date.now()) + "-" + Math.random().toString(16).slice(2);
  return "web-" + suffix.replaceAll("-", "").slice(0, 24);
}

/** 更新页面连接状态；最终成功以 complete 事件为准。 */
function setStatus(label, kind = "") {
  elements.status.textContent = label;
  elements.status.className = "status-pill " + kind;
}

/** 以 textContent 写入用户问题，避免把用户输入当作 HTML 执行。 */
function appendUserMessage(content) {
  const wrapper = document.createElement("div"); wrapper.className = "message user";
  const bubble = document.createElement("div"); bubble.className = "bubble"; bubble.textContent = content;
  const meta = document.createElement("span"); meta.className = "message-meta"; meta.textContent = "您";
  wrapper.append(bubble, meta); elements.messages.appendChild(wrapper); scrollMessagesToBottom();
}

/** 创建助手气泡，token 事件会追加到该节点。 */
function createAssistantMessage() {
  const wrapper = document.createElement("div"); wrapper.className = "message assistant";
  const bubble = document.createElement("div"); bubble.className = "bubble";
  const meta = document.createElement("span"); meta.className = "message-meta"; meta.textContent = "uPil 客服 · 流式生成中";
  wrapper.append(bubble, meta); elements.messages.appendChild(wrapper); scrollMessagesToBottom(); return wrapper;
}

/** 更新观测指标；所有值来自后端事件，不按问题关键词自行推断。 */
function updateMetrics(result, durationMs) {
  elements.route.textContent = result.route || "—"; elements.provider.textContent = result.provider || "—";
  elements.recognition.textContent = result.recognition_source || "—"; elements.duration.textContent = String(durationMs) + " ms";
}

/** 调试模式只展示后端真实返回的来源。 */
function renderSources(sources) {
  elements.sources.textContent = Array.isArray(sources) && sources.length ? JSON.stringify(sources, null, 2) : "本次未返回可展示的引用来源。";
}

/** 把真实收到的 SSE 事件记录到时间线。 */
function recordEvent(eventName, data) {
  if (!elements.debug.checked) return;
  const item = document.createElement("li"); const detail = data?.stage || data?.content || data?.route || "received";
  item.textContent = new Date().toLocaleTimeString() + " · " + eventName + " · " + detail;
  elements.timeline.appendChild(item); elements.timeline.scrollTop = elements.timeline.scrollHeight;
}

/** 滚动到最新消息。 */
function scrollMessagesToBottom() { elements.messages.scrollTop = elements.messages.scrollHeight; }

/** 解析一个 SSE 事件块，支持多行 data 与 CRLF。 */
function parseSseBlock(block) {
  let eventName = "message"; const dataLines = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, ""); if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":"); const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") eventName = value; if (field === "data") dataLines.push(value);
  }
  if (!dataLines.length) return null;
  try { return { eventName, data: JSON.parse(dataLines.join("\n")) }; }
  catch (_error) { throw new Error("服务返回了无法解析的 SSE 数据"); }
}

/**
 * 消费 POST SSE 响应。不能使用 EventSource，因为 EventSource 只能发 GET；
 * 这里手动处理网络包拆分和最后一个不完整 buffer。
 */
async function consumeSse(response, onEvent) {
  if (!response.ok) throw new Error("请求失败（HTTP " + response.status + "）");
  if (!response.body) throw new Error("浏览器未提供流式响应读取能力");
  const reader = response.body.getReader(); const decoder = new TextDecoder("utf-8"); let buffer = "";
  const consumeBuffer = (flush = false) => {
    if (flush) buffer += decoder.decode(); const blocks = buffer.split(/\n\n/); buffer = blocks.pop() || "";
    for (const block of blocks) { const parsed = parseSseBlock(block); if (parsed) onEvent(parsed.eventName, parsed.data); }
  };
  while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); consumeBuffer(); }
  consumeBuffer(true); if (buffer.trim()) { const parsed = parseSseBlock(buffer); if (parsed) onEvent(parsed.eventName, parsed.data); }
}

/** 发送一轮对话并处理 accepted、routed、token、complete 事件。 */
async function sendQuestion(question) {
  if (activeController) activeController.abort(); activeController = new AbortController();
  const startedAt = performance.now(); let assistantMessage = null; let completeReceived = false;
  appendUserMessage(question); setStatus("处理中", "busy"); elements.send.disabled = true; elements.question.disabled = true;
  elements.timeline.replaceChildren(); elements.sources.textContent = "等待后端返回真实引用。"; updateMetrics({}, 0);
  try {
    // 只有答辩调试模式才附带演示学员编号；普通模式保持公开咨询最小请求体。
    const payload = { message: question, conversation_id: elements.conversation.value.trim() || null };
    if (elements.debug.checked && elements.demoLearner.value.trim()) payload.learner_id = elements.demoLearner.value.trim();
    const response = await fetch("/api/v1/chat/stream", {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(payload), signal: activeController.signal,
    });
    await consumeSse(response, (eventName, data) => {
      recordEvent(eventName, data);
      if (eventName === "status") { if (data.stage === "routed") elements.route.textContent = data.route || "—"; if (data.stage === "a2a_task") elements.provider.textContent = "A2A · " + (data.status || "—"); }
      if (eventName === "token") { if (!assistantMessage) assistantMessage = createAssistantMessage(); assistantMessage.querySelector(".bubble").textContent += data.content || ""; scrollMessagesToBottom(); }
      if (eventName === "complete") { completeReceived = true; if (!assistantMessage) assistantMessage = createAssistantMessage(); assistantMessage.querySelector(".message-meta").textContent = "uPil 客服 · " + (data.provider || "workflow"); updateMetrics(data, Math.round(performance.now() - startedAt)); renderSources(data.sources); setStatus("已完成"); }
    });
    if (!completeReceived) throw new Error("连接已结束，但未收到 complete 完成事件");
  } catch (error) {
    if (error.name === "AbortError") setStatus("已取消");
    else { setStatus("请求异常", "error"); const wrapper = document.createElement("div"); wrapper.className = "message assistant"; const bubble = document.createElement("div"); bubble.className = "bubble"; bubble.textContent = error.message || "网络连接失败，请稍后重试。"; const meta = document.createElement("span"); meta.className = "message-meta"; meta.textContent = "连接错误"; wrapper.append(bubble, meta); elements.messages.appendChild(wrapper); scrollMessagesToBottom(); }
  } finally { elements.send.disabled = false; elements.question.disabled = false; elements.question.focus(); activeController = null; }
}

elements.form.addEventListener("submit", (event) => { event.preventDefault(); const question = elements.question.value.trim(); if (!question || activeController) return; sendQuestion(question); elements.question.value = ""; });
elements.question.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); elements.form.requestSubmit(); } });
elements.newConversation.addEventListener("click", () => { if (activeController) activeController.abort(); elements.conversation.value = createConversationId(); elements.messages.replaceChildren(); elements.messages.insertAdjacentHTML("beforeend", '<div class="welcome-message"><strong>已创建新会话。</strong><p>请继续输入您的课程或校区咨询。</p></div>'); updateMetrics({}, 0); setStatus("就绪"); });
elements.debug.addEventListener("change", () => {
  elements.modeLabel.textContent = elements.debug.checked ? "答辩调试模式" : "普通模式";
  elements.debugPanel.hidden = !elements.debug.checked;
  elements.demoLearnerField.hidden = !elements.debug.checked;
  if (!elements.debug.checked) { elements.timeline.replaceChildren(); elements.sources.textContent = "普通模式不展示内部引用。"; }
});
document.querySelectorAll(".quick-button").forEach((button) => button.addEventListener("click", () => { elements.question.value = button.dataset.question || ""; elements.question.focus(); }));
elements.conversation.value = createConversationId();
