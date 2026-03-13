"use client";

import { useState } from "react";
import { Box, Button, Paper, Stack, Typography } from "@mui/material";

export default function UploadContainer({
    onUploadSuccess
}: {
    onUploadSuccess: () => void
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selectedFiles = 
      event.target.files ? Array.from(event.target.files) : [];
    setFiles(selectedFiles);

    // allow re-selecting the same file later
    event.currentTarget.value = "";
  }

  async function handleUpload() {
    if (files.length === 0 || isUploading) return;
    setIsUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));

      const uploadRes = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      const uploadBody = await uploadRes.json();

			if (!uploadRes.ok) {
				throw new Error(
          (uploadBody as { error?: string } | null)?.error 
            ?? `Document(s) upload failed (${uploadRes.status})`,
				);
			}
      
      onUploadSuccess()
      setFiles([]);
    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Upload failed.";
      setError(errorMessage);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2.5}>
        <Box>
          <Typography variant="h6" fontWeight={700} gutterBottom>
            Add Documents
          </Typography>
          <Typography color="text.secondary" variant="body2">
            Only .pdf, .docx, .txt and .md files allowed.
          </Typography>
        </Box>

        <Stack direction="row" spacing={2} alignItems="center">
          <Button variant="outlined" component="label">
            Choose file
            <input
              type="file"
              multiple
              accept=".pdf, .docx, .txt, .md"
              onChange={handleFileChange}
              hidden
            />
          </Button>
          <Typography variant="body2" color="text.secondary">
            {files.length > 0 ? `${files.length} file(s) selected` : "No file selected"}
          </Typography>
        </Stack>
        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={files.length === 0 || isUploading}
          sx={{ alignSelf: "flex-start" }}
        >
          {isUploading ? "Uploading..." : "Upload"}
        </Button>
        {error ? (
          <Typography color="error" variant="body2">
            {error}
          </Typography>
        ) : null}
      </Stack>
    </Paper>
  );
}
