import type { ChatRequest, ChatResponse } from "@/lib/types/chat";

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Chat failed (${res.status}): ${text}`);
  }

  const data = (await res.json()) as Partial<ChatResponse>;
  return { answer: data.answer ?? "(No answer returned)" };
}
