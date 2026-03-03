"use client";

import { useState } from "react";
import { Box, Button, Container, Stack, Typography } from "@mui/material";

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files ? Array.from(e.target.files) : [];
    setFiles(selected);

    // allow re-selecting the same file later
    e.currentTarget.value = "";
  }

  async function handleUpload() {
    if (files.length === 0 || isUploading) return;
    setIsUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));

      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const payload = await res.json().catch(() => null) as
          | { error?: string }
          | null;
        const message = payload?.error || `Upload failed (${res.status})`;
        throw new Error(message);
      }

      const data: {
        ok: boolean;
        fileCount: number;
        files: { name: string; type: string; size: number }[];
      } = await res.json();

      console.log("Server returned:", data);
      console.log("Filenames:", data.files.map((f) => f.name));

      setFiles([]);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Upload failed.";
      setError(message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <Container maxWidth="sm" sx={{ py: 8 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h5" fontWeight={700} gutterBottom>
            Document Upload Page
          </Typography>
          <Typography color="text.secondary">
            Only .pdf, .docx, .txt and .md files allowed.
          </Typography>
        </Box>

        <Stack direction="row" spacing={2} alignItems="center">
          <Button variant="outlined" component="label">
            Choose file
            <input type="file" 
              multiple 
              accept=".pdf, .docx, .txt, .md"
              onChange={handleFileChange} 
              hidden
            />
          </Button>
          <Typography variant="body2" color="text.secondary">
            {files.length>0 ? `${files.length} file(s) selected` : "No file selected"}
          </Typography>
        </Stack>
        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={files.length === 0 || isUploading}
        >
          {isUploading ? "Uploading..." : "Upload"}
        </Button>
        {error ? (
          <Typography color="error" variant="body2">
            {error}
          </Typography>
        ) : null}
      </Stack>
    </Container>
  );
}
