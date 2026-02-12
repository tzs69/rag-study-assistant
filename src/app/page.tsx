"use client";

import Link from "next/link";
import { Box, Button, Container, Stack, Typography } from "@mui/material";

export default function Home() {
  return (
    <Container maxWidth="sm" sx={{ py: 8 }}>
      <Stack spacing={3} alignItems="flex-start">
        <Box>
          <Typography variant="h4" fontWeight={700} gutterBottom>
            RAG Study Assistant
          </Typography>
          <Typography color="text.secondary">
            Choose where you want to go next.
          </Typography>
        </Box>

        <Stack direction="row" spacing={2} flexWrap="wrap">
          <Button
            component={Link}
            href="/upload"
            variant="contained"
          >
            Upload a document
          </Button>
          <Button
            component={Link}
            href="/chat"
            variant="outlined"
          >
            Go to chat
          </Button>
        </Stack>
      </Stack>
    </Container>
  );
}
