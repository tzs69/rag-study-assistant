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
        const errorBody = await backendRes.json().catch(() => null) as
        | { error?: string }
        | null;
        const errorMessage = errorBody?.error 
        || `Failed to upload document(s) (status ${backendRes.status})`;

        return NextResponse.json(
            { ok: false, error: errorMessage }, 
            { status: backendRes.status }
        )
    }

    return NextResponse.json(
      { ok: true }, 
      { status: backendRes.status }
    );

  } catch (error) {
    const message =
      error instanceof Error 
      ? error.message : "Failed to reach backend document upload service";

    return NextResponse.json(
      { ok: false, error: message }, 
      { status: 502 }
    );
  }
}
