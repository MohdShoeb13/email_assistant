/**
 * Drives one generation run and reduces its SSE frames into render state.
 *
 * A reducer rather than a pile of useState calls, because the frames are a
 * stream of related facts: a `model_call` with is_fallback set has to change
 * the rail node that the last `agent_start` named. Splitting that across
 * separate setters makes the ordering implicit and easy to break.
 */

import { useCallback, useMemo, useRef, useReducer } from "react"
import { streamGenerate } from "@/lib/api"
import type {
  AgentId,
  AgentMeta,
  AgentStatus,
  EmailDraft,
  GenerateRequest,
  ModelCall,
  ReviewIssue,
  RunResult,
  RunStatus,
  StreamEvent,
} from "@/lib/types"

export interface AgentNodeState {
  id: AgentId
  label: string
  status: AgentStatus
  output: unknown
  /** Bumped each time the node re-runs, so the rail can show a revision badge. */
  runs: number
}

interface State {
  status: RunStatus
  sessionId: string | null
  draftId: string | null
  routingProfile: string | null
  agents: AgentNodeState[]
  activeAgent: AgentId | null
  statusMessage: string
  draft: EmailDraft | null
  result: RunResult | null
  trace: ModelCall[]
  revisions: { attempt: number; reason: string; issues: ReviewIssue[] }[]
  error: string | null
}

const initialState: State = {
  status: "idle",
  sessionId: null,
  draftId: null,
  routingProfile: null,
  agents: [],
  activeAgent: null,
  statusMessage: "",
  draft: null,
  result: null,
  trace: [],
  revisions: [],
  error: null,
}

/** Which agent a given router task belongs to, for attributing a fallback. */
const TASK_TO_AGENT: Record<string, AgentId> = {
  parse: "input_parser",
  intent: "intent_detection",
  tone: "tone_stylist",
  draft: "draft_writer",
  review: "review",
}

type Action =
  | { type: "reset" }
  | { type: "begin"; agents: AgentMeta[] }
  | { type: "frame"; event: StreamEvent }
  | { type: "failed"; message: string }

function setAgent(
  agents: AgentNodeState[],
  id: AgentId,
  patch: Partial<AgentNodeState>,
): AgentNodeState[] {
  return agents.map((agent) => (agent.id === id ? { ...agent, ...patch } : agent))
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "reset":
      return initialState

    case "begin":
      return {
        ...initialState,
        status: "running",
        agents: action.agents.map((meta) => ({
          id: meta.id,
          label: meta.label,
          status: "pending" as AgentStatus,
          output: null,
          runs: 0,
        })),
      }

    case "failed":
      return { ...state, status: "failed", error: action.message, activeAgent: null }

    case "frame": {
      const { event, data } = action.event

      switch (event) {
        case "run_start":
          return {
            ...state,
            status: "running",
            sessionId: data.session_id,
            routingProfile: data.routing_profile,
            agents: data.agents.map((meta) => ({
              id: meta.id,
              label: meta.label,
              status: "pending" as AgentStatus,
              output: null,
              runs: 0,
            })),
          }

        case "agent_start":
          return {
            ...state,
            activeAgent: data.node,
            agents: setAgent(state.agents, data.node, { status: "running" }),
          }

        case "agent_status":
          return { ...state, statusMessage: data.message }

        case "agent_done": {
          const previous = state.agents.find((a) => a.id === data.node)
          // A node that fell back keeps its amber marker; finishing does not
          // erase the fact that the primary model failed on the way here.
          const nextStatus: AgentStatus = previous?.status === "fallback" ? "fallback" : "done"
          return {
            ...state,
            agents: setAgent(state.agents, data.node, {
              status: nextStatus,
              output: data.output,
              runs: (previous?.runs ?? 0) + 1,
            }),
          }
        }

        case "model_call": {
          const trace = [...state.trace, data]
          const owner = TASK_TO_AGENT[data.task]
          if (!owner || !data.is_fallback) return { ...state, trace }
          return { ...state, trace, agents: setAgent(state.agents, owner, { status: "fallback" }) }
        }

        case "draft":
          return { ...state, draft: data.draft }

        case "revision":
          return { ...state, revisions: [...state.revisions, data] }

        case "error":
          return { ...state, error: data.message }

        case "done":
          return {
            ...state,
            status: data.status,
            result: data,
            draft: data.draft ?? state.draft,
            draftId: data.draft_id ?? state.draftId,
            // The done frame carries the authoritative trace; the streamed one
            // can be missing a call that landed after the last node reported.
            trace: data.trace?.length ? data.trace : state.trace,
            activeAgent: null,
            statusMessage: "",
            error: data.errors?.length ? data.errors.join(" ") : state.error,
            agents: state.agents.map((agent) =>
              agent.status === "running" || agent.status === "pending"
                ? { ...agent, status: data.status === "failed" ? "failed" : agent.status }
                : agent,
            ),
          }

        default:
          return state
      }
    }

    default:
      return state
  }
}

export function useEmailStream() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const abortRef = useRef<AbortController | null>(null)

  const start = useCallback(async (request: GenerateRequest) => {
    // Abort any run still in flight, so a fast double-click cannot leave two
    // streams writing into the same reducer.
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    dispatch({ type: "begin", agents: [] })

    try {
      await streamGenerate(request, (event) => dispatch({ type: "frame", event }), controller.signal)
    } catch (error) {
      if (controller.signal.aborted) return // the user cancelled; not a failure
      dispatch({
        type: "failed",
        message: error instanceof Error ? error.message : "Generation failed",
      })
    } finally {
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [])

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    dispatch({ type: "reset" })
  }, [])

  const totals = useMemo(() => {
    const inputTokens = state.trace.reduce((sum, call) => sum + call.input_tokens, 0)
    const outputTokens = state.trace.reduce((sum, call) => sum + call.output_tokens, 0)
    return {
      inputTokens,
      outputTokens,
      latencyMs: state.trace.reduce((sum, call) => sum + call.latency_ms, 0),
      fallbacks: state.trace.filter((call) => call.is_fallback).length,
      failures: state.trace.filter((call) => call.outcome === "error").length,
    }
  }, [state.trace])

  return {
    ...state,
    totals,
    isRunning: state.status === "running",
    start,
    cancel,
  }
}
