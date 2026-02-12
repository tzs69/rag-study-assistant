export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ChatRequest = {
  message: string;
  history?: ChatMessage[];
};

export type ChatResponse = {
  answer: string;
  // later: sources?: Source[];
};
