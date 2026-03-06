// src/app/api/documents/[id]/route.ts
import { NextResponse } from "next/server";

type Params = { params: Promise<{ id: string }> };

export async function DELETE(_: Request, { params }: Params) {
  try {
    const { id } = await params; // id from /api/documents/:id
    const backendUrl = process.env.BACKEND_URL;

    if (!backendUrl) {
      return NextResponse.json({ ok: false, error: "Missing BACKEND_URL" }, { status: 500 });
    }

    // if docId contains "/" or special chars, encode on client when calling this route
    const res = await fetch(`${backendUrl}/documents/${encodeURIComponent(id)}`, {
      method: "DELETE",
      cache: "no-store",
    });

    const payload = await res.json().catch(() => null);

    return NextResponse.json(payload ?? { ok: res.ok }, { status: res.status });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to reach backend document delete service";

    return NextResponse.json({ ok: false, error: message }, { status: 502 });
  }
}