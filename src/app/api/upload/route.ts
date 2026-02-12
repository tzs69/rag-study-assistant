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
