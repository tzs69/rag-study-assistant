"use client";

import { Box } from "@mui/material";
import { useState } from "react";
import type { ChatMessage } from "@/lib/types/chat";
import { sendChat } from "@/lib/api/chatApi";
import MessageList from "./MessageList";
import ChatComposer from "./ChatComposer";

export default function ChatScreen() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "Hello! Ask me anything about your uploaded file(s)." },
  ]);
  const [isSending, setIsSending] = useState(false);

  async function handleSend(text: string) {
    if (isSending) return;

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setIsSending(true);

    try {
      const data = await sendChat({
        message: text,
        history: nextMessages,
      });

      setMessages((prev) => [...prev, { role: "assistant", content: data.answer }]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Something went wrong.";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Warning: ${msg}` },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <Box sx={{ py: 6 }}>

      <MessageList messages={messages} isSending={isSending} />

      <ChatComposer disabled={isSending} onSend={handleSend} />
    </Box>
  );
}
