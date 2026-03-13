import { NextResponse } from "next/server";
import type { ChatResponse } from "@/lib/types/chat";

export async function POST(req: Request) {
  try{
    const payload = await req.json();
    const backendUrl = process.env.BACKEND_URL;

    if (!backendUrl) {
      return NextResponse.json(
        { ok: false, error: "Missing BACKEND_URL in .env.local" },
        { status: 500 },
      );
    }

    const backendRes = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      headers: {
          "Content-Type":"application/json"
        },
      body: JSON.stringify(payload)
    });

    if (!backendRes.ok) {
			const payload = await backendRes.json().catch(() => null) as
			| { error?: string }
			| null;
			const message = payload?.error || `Chat request failed (${backendRes.status})`;

			return NextResponse.json(
				{ ok: false, error: message }, 
				{ status: backendRes.status }
			)
    }

    const llm_response: Partial<ChatResponse> = await backendRes.json()
    return NextResponse.json({answer: llm_response.answer}, {
      status: backendRes.status
    });

  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to reach backend llm chat service";

    return NextResponse.json({ ok: false, error: message }, { status: 502 });
  }
}

