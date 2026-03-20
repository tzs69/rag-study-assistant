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

  async function refreshDocuments() {
    try {
      const fetchRes = await fetch(
        "/api/documents", 
        { method: "GET" }
      );

      const documentsBody = await fetchRes.json();

			if (!fetchRes.ok) {
				throw new Error(
          (documentsBody as { error?: string } | null)?.error 
            ?? `Document(s) fetch failed (${fetchRes.status})`,
				);
			}
      
      const documents = (documentsBody as { documents?: DocumentData[] } | null)?.documents ?? [];
      setDocs(documents)

    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Documents fetch failed.";
      setError(errorMessage);
    }
  }

  async function deleteDocument(documentData: DocumentData): Promise<void> {
    try {
      const deleteRes = await fetch(
        `/api/documents/${encodeURIComponent(documentData.docId)}`, 
        { method: "DELETE" }
      );

      const deleteBody = await deleteRes.json();

			if (!deleteRes.ok) {
				throw new Error(
          (deleteBody as { error?: string } | null)?.error 
            ?? `Document delete failed (${deleteRes.status})`,
				);
			}

      await refreshDocuments()
    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Delete failed.";
      setError(errorMessage);
    }
  }

  useEffect(() => {
    refreshDocuments();
  }, []);


  return (
    <Container maxWidth="md" sx={{ py: 2 }}>
      <BackButton>Back</BackButton>
      <Stack spacing={3}  sx={{ py: 3 }}>
        {error ? <Alert severity="error">{error}</Alert> : null}
        <DocumentsDisplay docs={docs} onDelete={deleteDocument}/>
        <UploadContainer onUploadSuccess={refreshDocuments}/>
      </Stack>
    </Container>
  );
}
