"use client";

import { Box, Paper, Stack, Typography } from "@mui/material";
import DocumentLineItem from "./DocumentLineItem";
import { DocumentData } from "@/lib/types/kb";


export default function DocumentsDisplay({ 
  docs,
  onDelete
} : { 
  docs : DocumentData[],
	onDelete: (documentData: DocumentData) => void | Promise<void>
}) {

  // Pass deletion event of child (DocumentLineItem) to parent (knowledge_base/page)
  async function handleDocumentDelete(documentData: DocumentData) {
    await onDelete(documentData)
  }

  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h6" fontWeight={700}>
            Your Uploaded Documents
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Rough skeleton view for document list and delete actions.
          </Typography>
        </Box>

        <Stack spacing={1.25}>
          {docs.map((doc) => (
            <DocumentLineItem 
              documentData={doc} 
              key={doc.docId}
              onDelete={handleDocumentDelete}
            />
          ))}
        </Stack>
      </Stack>
    </Paper>
  );
}
