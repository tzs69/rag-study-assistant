import { NextResponse } from "next/server";

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
    };

    if (!backendRes.body) {
      return NextResponse.json(
        { ok: false, error: "Backend chat stream did not return a body" },
        { status: 502 }
      )
    };

    return new Response(backendRes.body, {
      status: backendRes.status,
      headers: {
        "Content-Type": backendRes.headers.get("content-type") ?? "text/event-stream",
        "Cache-Control": backendRes.headers.get("cache-control") ?? "no-cache",
        "X-Content-Type-Options":
          backendRes.headers.get("x-content-type-options") ?? "nosniff",
      },
    });

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

