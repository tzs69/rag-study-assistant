"use client";

import { Button, Stack, TextField } from "@mui/material";
import { useState } from "react";

export default function ChatComposer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string) => Promise<void> | void;
}) {
  const [input, setInput] = useState("");

  async function submit() {
    const text = input.trim();
    if (!text || disabled) return;
    setInput("");
    await onSend(text);
  }

  return (
    <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
      <TextField
        fullWidth
        size="small"
        placeholder={disabled ? "Please wait…" : "Type your question…"}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void submit();
          }
        }}
        disabled={disabled}
      />
      <Button variant="contained" disabled={disabled || !input.trim()} onClick={() => void submit()}>
        Send
      </Button>
    </Stack>
  );
}
