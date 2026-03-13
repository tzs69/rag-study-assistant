"use client";

import { useEffect, useState } from "react";
import { Alert, Container, Stack } from "@mui/material";
import UploadContainer from "@/components/knowledge_base/UploadContainer";
import DocumentsDisplay from "@/components/knowledge_base/DocumentsDisplay";
import BackButton from "@/components/shared/BackButton";
import type { DocumentData } from "@/lib/types/kb";


export default function KnowledgeBasePage() {

  const [docs, setDocs] = useState<DocumentData[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function refetchDocuments() {
    try {
      const res = await fetch("/api/documents", { method: "GET" });

      const payload = await res.json();

			if (!res.ok) {
				throw new Error(
						(payload as { error?: string } | null)?.error ?? `Documents fetch failed (${res.status})`,
				);
			}
      
      const documents = (payload as { documents?: DocumentData[] } | null)?.documents ?? [];
      setDocs(documents)

    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Documents fetch failed.";
      setError(message);
    }
  }

  async function deleteSingleDocument(documentData: DocumentData): Promise<void> {
    try {
      const res = await fetch(`/api/documents/${encodeURIComponent(documentData.docId)}`, {
        method: "DELETE"
      })

      const payload = await res.json();

			if (!res.ok) {
				throw new Error(
						(payload as { error?: string } | null)?.error ?? `Delete failed (${res.status})`,
				);
			}

      await refetchDocuments()
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Delete failed.";
      setError(message);
    }
  }

  useEffect(() => {
    refetchDocuments();
  }, []);


  return (
    <Container maxWidth="md" sx={{ py: 2 }}>
      <BackButton>Back</BackButton>
      <Stack spacing={3}  sx={{ py: 3 }}>
        {error ? <Alert severity="error">{error}</Alert> : null}
        <DocumentsDisplay docs={docs} onDelete={deleteSingleDocument}/>
        <UploadContainer onUploadSuccess={refetchDocuments}/>
      </Stack>
    </Container>
  );
}
