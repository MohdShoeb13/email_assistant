/** HTTP client, including the SSE reader. */

import type { AppConfig, GenerateRequest, StreamEvent, UserProfile } from "@/lib/types"

// In dev this stays "/api" and Vite proxies it. In production (Vercel) set
// VITE_API_BASE to the backend origin, e.g. https://email-assistant-api.onrender.com/api
const BASE = import.meta.env.VITE_API_BASE ?? "/api"

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => "")
    throw new Error(detail ? `${response.status}: ${detail}` : `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const getConfig = () => json<AppConfig>("/config")

export const getProfile = (userId: string) =>
  json<{ profile: UserProfile }>(`/profile/${encodeURIComponent(userId)}`).then((r) => r.profile)

export const saveProfile = (userId: string, updates: Partial<UserProfile>) =>
  json<{ profile: UserProfile }>(`/profile/${encodeURIComponent(userId)}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  }).then((r) => r.profile)

export const saveEdit = (
  draftId: string,
  payload: { user_id: string; original_body: string; edited_body: string; subject: string },
) =>
  json<{ saved: boolean; reason?: string; evidence_count: number }>(
    `/drafts/${encodeURIComponent(draftId)}/edits`,
    { method: "POST", body: JSON.stringify(payload) },
  )

/**
 * Stream a generation run.
 *
 * Uses fetch + a ReadableStream reader rather than EventSource, because
 * EventSource can only issue GET requests and this endpoint takes a JSON body.
 * That means parsing the SSE wire format by hand — which is the small cost of
 * not having to shoehorn the whole request into a query string.
 */
export async function streamGenerate(
  request: GenerateRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  })

  if (!response.ok) {
    // A validation failure arrives as JSON, not as a stream.
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep the status-code message */
    }
    throw new Error(detail)
  }
  if (!response.body) throw new Error("The server returned no stream")

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Frames are separated by a blank line. A frame split across two network
      // chunks stays in the buffer until its terminator arrives.
      let boundary = buffer.indexOf("\n\n")
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const parsed = parseFrame(frame)
        if (parsed) onEvent(parsed)
        boundary = buffer.indexOf("\n\n")
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let name = ""
  const dataLines: string[] = []

  for (const rawLine of frame.split("\n")) {
    const line = rawLine.replace(/\r$/, "")
    if (line.startsWith(":")) continue // a comment, used as a keep-alive
    if (line.startsWith("event:")) name = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart())
  }

  if (!name || dataLines.length === 0) return null
  try {
    return { event: name, data: JSON.parse(dataLines.join("\n")) } as StreamEvent
  } catch {
    // A malformed frame should not kill a run that is otherwise fine.
    return null
  }
}
