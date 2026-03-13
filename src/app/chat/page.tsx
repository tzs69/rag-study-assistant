"use client";

import { Box, Container } from "@mui/material";
import { useState } from "react";
import type { ChatMessage, ChatRequest } from "@/lib/types/chat";
import MessageList from "@/components/chat/MessageList";
import ChatComposer from "@/components/chat/ChatComposer";
import BackButton from "@/components/shared/BackButton";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "Hello! Ask me anything about your uploaded file(s)." },
  ]);
  const [isSending, setIsSending] = useState(false);
  
  async function handleSend(userQuery: string) {
    if (isSending) return;
    
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: userQuery }];
    setMessages(nextMessages)
    setIsSending(true);

    const chatRequest: ChatRequest ={
      message: userQuery,
      history: messages
    }

    try {
      const chatRes = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type":"application/json"
        },
        body: JSON.stringify(chatRequest)
      });

      const chatResponse = await chatRes.json() as { answer?: string };

			if (!chatRes.ok) {
				throw new Error(
						(chatResponse as { error?: string } | null)?.error ?? `Delete failed (${chatRes.status})`,
				);
			}

      const assistantReply = chatResponse.answer ?? "(No answer returned)";

      setMessages((prev) => [...prev, { role: "assistant", content: assistantReply }]);

    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Chat request failed.";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Warning: ${msg}` },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <Container maxWidth="md"  sx={{ py: 2 }}> 
      <BackButton>Back</BackButton>
      <Box sx={{ py: 3 }}>

      <MessageList messages={messages} isSending={isSending} />

      <ChatComposer disabled={isSending} onSend={handleSend} />
    </Box>
    </Container>
  );
}