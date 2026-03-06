import { NextResponse } from "next/server";

export async function GET() {
  try {
    const backendUrl = process.env.BACKEND_URL;

    if (!backendUrl) {
      return NextResponse.json(
        { ok: false, error: "Missing BACKEND_URL in .env.local" },
        { status: 500 },
      );
    }

    const backendRes = await fetch(`${backendUrl}/documents`, {
      method: "GET",
      cache: "no-store",
    });
    
    if (!backendRes.ok) {
			const payload = await backendRes.json().catch(() => null) as
			| { error?: string }
			| null;
			const message = payload?.error || `Documents GET failed (${backendRes.status})`;

			return NextResponse.json(
				{ ok: false, error: message }, 
				{ status: backendRes.status }
			)
    }
    
    const documentData = await backendRes.json();

    return NextResponse.json(documentData, {
      status: backendRes.status,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to reach backend documents listing service";

    return NextResponse.json({ ok: false, error: message }, { status: 502 });
  }
}
