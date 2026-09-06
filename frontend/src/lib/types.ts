/**
 * Mirrors the backend's Pydantic models and SSE event vocabulary.
 *
 * Hand-written rather than generated: the surface is small and stable, and a
 * generator would add a build step to keep in sync for the sake of six shapes.
 * The one rule is that field names here match `backend/src/email_assistant/`
 * exactly, so a rename on either side shows up as a type error rather than an
 * undefined at runtime.
 */

export type AgentId =
  | "input_parser"
  | "intent_detection"
  | "tone_stylist"
  | "personalization"
  | "draft_writer"
  | "review"
  | "router"

export type AgentStatus = "pending" | "running" | "done" | "fallback" | "failed"

export type RunStatus = "idle" | "running" | "complete" | "needs_review" | "failed"

export interface AgentMeta {
  id: AgentId
  label: string
}

export interface ParsedInput {
  recipient_name: string | null
  recipient_role: string | null
  relationship: string
  subject_hint: string | null
  key_points: string[]
  constraints: string[]
  length_hint: string
  language: string
}

export interface IntentResult {
  intent: string
  confidence: number
  rationale: string
}

export interface ToneSpec {
  tone: string
  voice: string
  greeting_style: string
  closing_style: string
  sentence_length: string
  use_contractions: boolean
  banned_phrases: string[]
  guidance: string[]
}

export interface EmailDraft {
  subject: string
  body: string
  word_count: number
}

export interface ReviewIssue {
  category: string
  severity: "low" | "medium" | "high"
  detail: string
  suggestion: string
}

export interface ReviewResult {
  passed: boolean
  tone_match: number
  issues: ReviewIssue[]
  fix_instructions: string
}

export interface ModelCall {
  task: string
  provider: string
  model: string
  attempt: number
  outcome: "success" | "error"
  latency_ms: number
  input_tokens: number
  output_tokens: number
  error_type: string | null
  error_message: string | null
  is_fallback: boolean
}

export interface AppConfig {
  offline: boolean
  active_profile: string
  routing_profiles: string[]
  providers: { name: string; available: boolean }[]
  tones: string[]
  intents: string[]
  lengths: string[]
  agents: AgentMeta[]
  max_revisions: number
}

export interface UserProfile {
  user_id: string
  name: string
  role: string
  company: string
  signature: string
  default_tone: string
  draft_history: { draft_id: string; subject: string; created_at: string }[]
  edit_history: unknown[]
  style_evidence_count?: number
}

export interface GenerateRequest {
  prompt: string
  tone?: string | null
  intent: string
  recipient?: string | null
  length: "short" | "medium" | "long"
  user_id: string
  routing_profile?: string | null
}

/** The `done` frame: everything needed to render the finished run. */
export interface RunResult {
  session_id: string
  draft_id: string
  status: Exclude<RunStatus, "idle" | "running">
  draft: EmailDraft | null
  review: ReviewResult | null
  parsed: ParsedInput | null
  intent: IntentResult | null
  tone_spec: ToneSpec | null
  attempts: number
  errors: string[]
  trace: ModelCall[]
  signature: string
}

/** One SSE frame, discriminated on the event name. */
export type StreamEvent =
  | { event: "run_start"; data: { session_id: string; routing_profile: string; agents: AgentMeta[]; max_revisions: number } }
  | { event: "agent_start"; data: { node: AgentId; label: string } }
  | { event: "agent_status"; data: { message: string } }
  | { event: "agent_done"; data: { node: AgentId; label: string; output: unknown; revision: boolean } }
  | { event: "model_call"; data: ModelCall }
  | { event: "draft"; data: { draft: EmailDraft; attempts: number } }
  | { event: "revision"; data: { attempt: number; reason: string; issues: ReviewIssue[] } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: RunResult }
