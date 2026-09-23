export interface SseEvent {
  event: string;
  data: unknown;
}

/** 手动消费 POST SSE，处理网络分块、CRLF、多行 data 和尾部 buffer。 */
export async function consumePostSse(
  response: Response,
  onEvent: (event: SseEvent) => void,
): Promise<void> {
  if (!response.ok) throw new Error("请求失败（HTTP " + response.status + "）");
  if (!response.body) throw new Error("浏览器未提供流式响应读取能力");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  const consume = (flush = false) => {
    if (flush) buffer += decoder.decode();
    // SSE 空行既可能使用 LF，也可能使用 CRLF；如果只按 LF 空行切分，
    // CRLF 数据会一直滞留到尾部并被误当成一个大 JSON 块解析。
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (parsed) onEvent(parsed);
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    consume();
  }
  consume(true);
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed) onEvent(parsed);
  }
}

export function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "data") dataLines.push(value);
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) as unknown };
  } catch {
    throw new Error("服务返回了无法解析的 SSE 数据");
  }
}
