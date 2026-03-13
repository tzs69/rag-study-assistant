"use client";

import { Box, Container } from "@mui/material";
import { useState } from "react";
import type { ChatMessage, ChatRequest } from "@/lib/types/chat";
import MessageList from "@/components/chat/MessageList";
import ChatComposer from "@/components/chat/ChatComposer";
import BackButton from "@/components/shared/BackButton";

export default function ChatPage() {

  const [messages, setMessages] = useState<ChatMessage[]>([{ 
    role: "assistant", 
    content: "Hello! Ask me anything about your uploaded file(s)." 
  }]);
  const [isSending, setIsSending] = useState(false);
  
  async function handleSend(userQuery: string) {
    if (isSending) return;
    
    const nextMessages: ChatMessage[] = [
      ...messages, 
      { 
        role: "user", 
        content: userQuery 
      }
    ];
    setMessages(nextMessages)
    setIsSending(true);

    const chatRequest: ChatRequest ={
      message: userQuery,
      history: messages
    }

    try {
      const chatRes = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type":"application/json" },
        body: JSON.stringify(chatRequest)
      });

      const chatResponseBody = await chatRes.json();

			if (!chatRes.ok) {
				throw new Error(
          (chatResponseBody as { error?: string } | null)?.error 
            ?? `Chat failed (status ${chatRes.status})`,
				);
			}

      const assistantReply = chatResponseBody.answer ?? "(No answer returned)";

      setMessages((prev) => [
        ...prev, 
        { 
          role: "assistant", 
          content: assistantReply 
        }
      ]);

    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Chat request failed.";
      setMessages((prev) => [
        ...prev,
        { 
          role: "assistant", 
          content: `Warning: ${errorMessage}` 
        },
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