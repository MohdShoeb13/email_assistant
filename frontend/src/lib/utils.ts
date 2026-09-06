import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function titleCase(value: string): string {
  return value
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/**
 * Build an RFC 5322 .eml file.
 *
 * Worth the few lines over a .txt download: an .eml opens directly in Outlook
 * or Mail as a real draft with the subject already filled in, which is where
 * the user is going next anyway.
 */
export function buildEml(subject: string, body: string, to?: string | null): string {
  const headers = [
    "MIME-Version: 1.0",
    `Subject: ${subject}`,
    to ? `To: ${to}` : null,
    "Content-Type: text/plain; charset=utf-8",
    "X-Unsent: 1", // tells Outlook to open it as an editable draft, not a received message
  ].filter(Boolean)
  return `${headers.join("\r\n")}\r\n\r\n${body.replace(/\n/g, "\r\n")}`
}

export function downloadText(filename: string, content: string, mime = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type: `${mime};charset=utf-8` }))
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function slugify(value: string, fallback = "draft"): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
  return slug || fallback
}

export function mailtoHref(subject: string, body: string, to?: string | null): string {
  const target = to && /\S+@\S+/.test(to) ? encodeURIComponent(to) : ""
  return `mailto:${target}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}
