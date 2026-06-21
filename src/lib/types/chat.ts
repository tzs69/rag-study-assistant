

export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ChatRequest = {
  message: string;
  history?: ChatMessage[];
};

export type ChatStreamEvent =
  | { event: "sse_started"; data: Record<string, never> }
  | { event: "sse_in_progress"; data: { text: string } }
  | { event: "sse_completed"; data: Record<string, never> }
  | { event: "sse_error"; data: { error: string } };