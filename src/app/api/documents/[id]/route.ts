import { NextResponse } from "next/server";

type Params = { params: Promise<{ id: string }> };

export async function DELETE(_: Request, { params }: Params) {
  try {
    const { id } = await params; 
    const backendUrl = process.env.BACKEND_URL;

    if (!backendUrl) {
      return NextResponse.json(
        { ok: false, error: "Missing BACKEND_URL in .env.local" }, 
        { status: 500 }
      );
    }

    // if docId contains "/" or special chars, encode on client when calling this route
    const backendRes = await fetch(
      `${backendUrl}/documents/${encodeURIComponent(id)}`, 
      {
        method: "DELETE",
        cache: "no-store",
      }
    );

    if (!backendRes.ok) {
			const errorBody = await backendRes.json().catch(() => null) as
			| { error?: string }
			| null;
			const errorMessage = errorBody?.error 
      || `Failed to delete document (status ${backendRes.status})`;

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
    const errorMessage =
      error instanceof Error 
      ? error.message : "Failed to reach backend document delete service";

    return NextResponse.json(
      { ok: false, error: errorMessage }, 
      { status: 502 }
    );
  }
}