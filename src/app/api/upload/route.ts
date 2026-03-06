import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const backendUrl = process.env.BACKEND_URL;

    if (!backendUrl) {
      return NextResponse.json(
        { ok: false, error: "Missing BACKEND_URL in .env.local" },
        { status: 500 },
      );
    }

    const backendRes = await fetch(`${backendUrl}/upload`, {
      method: "POST",
      body: formData,
    });

    if (!backendRes.ok) {
        const payload = await backendRes.json().catch(() => null) as
        | { error?: string }
        | null;
        const message = payload?.error || `Upload failed (${backendRes.status})`;

        return NextResponse.json(
            { ok: false, error: message }, 
            { status: backendRes.status }
        )
    }

    const text = await backendRes.text();
    const contentType =
      backendRes.headers.get("content-type") ?? "application/json";

    return new NextResponse(text, {
      status: backendRes.status,
      headers: { "content-type": contentType },
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to reach backend upload service";

    return NextResponse.json({ ok: false, error: message }, { status: 502 });
  }
}
