import { NextResponse } from "next/server";
import type { ChatResponse } from "@/lib/types/chat";

export async function POST(req: Request) {
  try{
    const chatRequest = await req.json();
    const backendUrl = process.env.BACKEND_URL;

    if (!backendUrl) {
      return NextResponse.json(
        { ok: false, error: "Missing BACKEND_URL in .env.local" },
        { status: 500 },
      );
    }

    const backendRes = await fetch(
      `${backendUrl}/chat`, 
      {
        method: "POST",
        headers: { "Content-Type":"application/json" },
        body: JSON.stringify(chatRequest)
      }
    );

    if (!backendRes.ok) {
			const errorBody = await backendRes.json().catch(() => null) as
			| { error?: string }
			| null;
			const errorMessage = errorBody?.error 
      || `Chat request failed (status ${backendRes.status})`;

			return NextResponse.json(
				{ ok: false, error: errorMessage }, 
				{ status: backendRes.status }
			)
    }

    const chatResponse: Partial<ChatResponse> = await backendRes.json()

    return NextResponse.json(
      { answer: chatResponse.answer }, 
      { status: backendRes.status }
    );

  } catch (error) {
    const errorMessage =
      error instanceof Error 
      ? error.message : "Failed to reach backend chat service";

    return NextResponse.json(
      { ok: false, error: errorMessage }, 
      { status: 502 }
    );
  }
}

