"use client";

import { Paper, Typography } from "@mui/material";
import type { ChatMessage } from "@/lib/types/chat";

export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        maxWidth: "80%",
        bgcolor: "white",
      }}
    >
      <Typography variant="caption" sx={{ opacity: 0.7 }}>
        {isUser ? "You" : "Bot"}
      </Typography>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", mt: 0.5 }}>
        {message.content}
      </Typography>
    </Paper>
  );
}
