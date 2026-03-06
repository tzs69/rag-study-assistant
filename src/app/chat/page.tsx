"use client";

import ChatScreen from "@/components/chat/ChatScreen";
import BackButton from "@/components/shared/BackButton";
import { Container } from "@mui/material"

export default function Home() {
  return (
    <Container maxWidth="md"> 
      <BackButton>Back</BackButton>
      <ChatScreen />
    </Container>
  )
}
