export type ServerSentEvent = {
  data: string;
  event?: string;
};

export function parseServerSentEventBlock(
  block: string,
): ServerSentEvent | undefined {
  const lines = block.split(/\r?\n/);
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return undefined;
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const event = eventLine?.slice(6).trim();
  return { data, event: event || undefined };
}

export async function consumeServerSentEvents({
  response,
  onEvent,
}: {
  response: Response;
  onEvent: (event: ServerSentEvent) => void;
}) {
  if (!response.body) throw new Error("Event stream response was empty");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const event = parseServerSentEventBlock(block);
        if (event) onEvent(event);
      }
      if (done) break;
    }
    const trailing = parseServerSentEventBlock(buffer);
    if (trailing) onEvent(trailing);
  } finally {
    reader.releaseLock();
  }
}
