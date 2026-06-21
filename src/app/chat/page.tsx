"use client";

import { Box, Container } from "@mui/material";
import { useState } from "react";
import type { ChatMessage, ChatRequest, ChatStreamEvent } from "@/lib/types/chat";
import MessageList from "@/components/chat/MessageList";
import ChatComposer from "@/components/chat/ChatComposer";
import BackButton from "@/components/shared/BackButton";

export default function ChatPage() {

  const [messages, setMessages] = useState<ChatMessage[]>([{ 
    role: "assistant", 
    content: "Hello! Ask me anything about your uploaded file(s)." 
  }]);
  const [isSending, setIsSending] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

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

			if (!chatRes.ok) {
				throw new Error(
          (await chatRes.json() as { error?: string } | null)?.error 
            ?? `Chat failed (status ${chatRes.status})`,
				);
			}

      const decoder = new TextDecoder();
      const reader = chatRes.body?.getReader();
      let sseBuffer = "";

      if (!reader) {
        throw new Error("Chat response body is not readable.");
      }

      while (true) {
        const { value, done } = await reader.read();
        if (done === true) {
          break;
        };


        sseBuffer += decoder.decode(value, { stream: true });
        const rawSSEEvents = sseBuffer.split("\n\n");
        sseBuffer = rawSSEEvents.pop() ?? "";

        for (const rawSSEEvent of rawSSEEvents) {
          const rawSSEEventLines = rawSSEEvent.split("\n");

          const eventLine = rawSSEEventLines.find((line) => line.startsWith("event:"));
          const dataLine = rawSSEEventLines.find((line) => line.startsWith("data:"));

          if (!eventLine || !dataLine) continue;

          const event = eventLine.slice("event:".length).trim();
          const dataJson = dataLine.slice("data:".length).trim();

          const data = JSON.parse(dataJson);

          const parsedSSEEvent = { event, data } as ChatStreamEvent;

          switch (parsedSSEEvent.event) {
            case "sse_started": {
              setIsSending(false);
              setIsStreaming(true);
              setMessages((prev) => [
                ...prev, 
                { 
                  role: "assistant", 
                  content: "" 
                }
              ]);
              break;
            }

            case "sse_in_progress": {
              setMessages((prev) => {
                const next = [...prev];
                const lastMessage = next[next.length - 1];

                if (lastMessage?.role === "assistant") {
                  next[next.length - 1] = {
                    ...lastMessage,
                    content: lastMessage.content + parsedSSEEvent.data.text,
                  };
                }

                return next;
              });
              break;
            }

            case "sse_completed": {
              setIsStreaming(false);
              break;
            }

            case "sse_error": {
              setIsStreaming(false);
              throw new Error(parsedSSEEvent.data.error);
            }
          }
        }
      }

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

      <MessageList messages={messages} isSending={isSending} isStreaming={isStreaming}/>

      <ChatComposer disabled={isSending} onSend={handleSend} />
    </Box>
    </Container>
  );
}
