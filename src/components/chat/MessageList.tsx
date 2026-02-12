"use client";

import { Box, Paper, Stack } from "@mui/material";
import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types/chat";
import MessageBubble from "./MessageBubble";

export default function MessageList({
  messages,
  isSending,
}: {
  messages: ChatMessage[];
  isSending: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        height: "70vh",
        overflowY: "auto",
        bgcolor: "grey.50",
      }}
    >
      <Stack spacing={1.25}>
        {messages.map((m, idx) => (
          <Box
            key={idx}
            sx={{
              display: "flex",
              justifyContent: m.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            <MessageBubble message={m} />
          </Box>
        ))}

        {isSending ? (
          <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
            <MessageBubble message={{ role: "assistant", content: "Thinking…" }} />
          </Box>
        ) : null}

        <div ref={bottomRef} />
      </Stack>
    </Paper>
  );
}
