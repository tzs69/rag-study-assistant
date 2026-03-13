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
			const errorBody = await backendRes.json().catch(() => null) as
			| { error?: string }
			| null;
			const errorMessage = errorBody?.error 
      || `Failed to fetch documents (status ${backendRes.status})`;

			return NextResponse.json(
				{ ok: false, error: errorMessage }, 
				{ status: backendRes.status }
			)
    }
    
    const documentData = await backendRes.json();

    return NextResponse.json(
      documentData, 
      { status: backendRes.status }
    );
  } catch (error) {
    const errorMessage =
      error instanceof Error 
      ? error.message : "Failed to reach backend document listing service";

    return NextResponse.json(
      { ok: false, error: errorMessage }, 
      { status: 502 }
    );
  }
}
