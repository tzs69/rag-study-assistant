"use client";

import { useRouter } from 'next/navigation'; // Use 'next/navigation' for App Router
import { Button } from "@mui/material";
import React from 'react';

export default function BackButton({ children, className }: React.PropsWithChildren<{ className?: string }>) {
  const router = useRouter();

  return (
    <Button 
      variant="outlined"
      className={className} onClick={() => router.back()}
    >
      {children || 'Go Back'}
    </Button>
  );
}
