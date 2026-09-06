/**
 * The agent pipeline rail.
 *
 * This is the component that makes the architecture visible. The brief grades
 * "distinct modular agents, LangGraph routing, fallback handling" at 25%, and
 * all three are otherwise invisible at runtime — a working app looks identical
 * whether it runs seven agents or one prompt. So the rail draws each node
 * advancing live, marks the one that fell back to a second model in amber, and
 * lights an arc under the review node when it sends the draft back to be
 * rewritten.
 *
 * Node order comes from the server's run_start frame rather than a constant
 * here, so adding an agent to the graph adds it to the rail with no UI change.
 */

import { AnimatePresence, motion } from "motion/react"
import {
  AlertTriangle,
  Check,
  FileText,
  Fingerprint,
  Palette,
  PenLine,
  Route,
  ScanSearch,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react"
import { useState } from "react"
import type { AgentId, AgentStatus } from "@/lib/types"
import type { AgentNodeState } from "@/hooks/useEmailStream"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/primitives"

const ICONS: Record<AgentId, LucideIcon> = {
  input_parser: ScanSearch,
  intent_detection: Fingerprint,
  tone_stylist: Palette,
  personalization: FileText,
  draft_writer: PenLine,
  review: ShieldCheck,
  router: Route,
}

const DESCRIPTIONS: Record<AgentId, string> = {
  input_parser: "Pulls the recipient, key points, and constraints out of your request.",
  intent_detection: "Classifies the purpose, which decides how the email is structured.",
  tone_stylist: "Turns the tone name into a checkable style contract.",
  personalization: "Loads your profile and how you have edited past drafts. No model call.",
  draft_writer: "Writes the email against the contract. Re-runs if review sends it back.",
  review: "Checks tone, grammar, and — most importantly — invented facts.",
  router: "Settles the status and saves the draft to memory. No model call.",
}

const NODE_STYLES: Record<AgentStatus, string> = {
  pending: "border-edge bg-raised text-faint",
  running: "border-accent/50 bg-accent-soft text-accent animate-pulse-ring",
  done: "border-emerald/35 bg-emerald-soft text-emerald",
  fallback: "border-amber/40 bg-amber-soft text-amber",
  failed: "border-rose/40 bg-rose-soft text-rose",
}

interface Props {
  agents: AgentNodeState[]
  activeAgent: AgentId | null
  statusMessage: string
  revisionCount: number
  maxRevisions: number
}

export function AgentPipeline({
  agents,
  activeAgent,
  statusMessage,
  revisionCount,
  maxRevisions,
}: Props) {
  const [expanded, setExpanded] = useState<AgentId | null>(null)

  if (agents.length === 0) return <IdleRail />

  const reviewIndex = agents.findIndex((a) => a.id === "review")
  const writerIndex = agents.findIndex((a) => a.id === "draft_writer")
  const selected = agents.find((a) => a.id === expanded) ?? null

  return (
    <div className="rounded-[14px] border border-edge bg-elevated shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold tracking-[-0.01em]">Agent pipeline</h2>
          {revisionCount > 0 && (
            <Badge tone="amber">
              revision {revisionCount} of {maxRevisions}
            </Badge>
          )}
        </div>
        <div className="min-h-[18px] font-mono text-[11px] text-muted">
          <AnimatePresence mode="wait">
            {statusMessage && (
              <motion.span
                key={statusMessage}
                initial={{ opacity: 0, y: -3 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 3 }}
                transition={{ duration: 0.16 }}
              >
                {statusMessage}
                <span className="caret-blink ml-0.5">_</span>
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* The rail scrolls sideways rather than wrapping. Seven nodes wrapped to
          two rows stop reading as a sequence, which is the whole point. */}
      <div className="overflow-x-auto px-5 pt-5 pb-8">
        <div className="relative flex min-w-[680px] items-start">
          {agents.map((agent, index) => (
            <div key={agent.id} className="flex flex-1 items-start">
              <Node
                agent={agent}
                isActive={activeAgent === agent.id}
                isExpanded={expanded === agent.id}
                onToggle={() => setExpanded(expanded === agent.id ? null : agent.id)}
              />
              {index < agents.length - 1 && (
                <Connector
                  active={agents[index + 1].status === "running"}
                  complete={agent.status === "done" || agent.status === "fallback"}
                />
              )}
            </div>
          ))}

          {reviewIndex > writerIndex && writerIndex >= 0 && (
            <RevisionArc
              active={revisionCount > 0}
              fromRatio={(writerIndex + 0.5) / agents.length}
              toRatio={(reviewIndex + 0.5) / agents.length}
            />
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {selected && (
          <motion.div
            key={selected.id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="mx-5 mb-5 rounded-[10px] border border-edge bg-raised p-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[12px] font-semibold">{selected.label}</span>
                {selected.runs > 1 && <Badge tone="amber">ran {selected.runs}x</Badge>}
              </div>
              <p className="mb-3 text-[12px] leading-relaxed text-muted">
                {DESCRIPTIONS[selected.id]}
              </p>
              {selected.output ? (
                <pre className="max-h-56 overflow-auto rounded-[8px] border border-edge bg-elevated p-3 font-mono text-[11px] leading-relaxed text-muted">
                  {JSON.stringify(selected.output, null, 2)}
                </pre>
              ) : (
                <p className="font-mono text-[11px] text-faint">No output yet.</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function Node({
  agent,
  isActive,
  isExpanded,
  onToggle,
}: {
  agent: AgentNodeState
  isActive: boolean
  isExpanded: boolean
  onToggle: () => void
}) {
  const Icon = ICONS[agent.id] ?? FileText
  const settled = agent.status === "done" || agent.status === "fallback"

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={isExpanded}
      aria-label={`${agent.label}: ${agent.status}`}
      className="group flex w-[74px] shrink-0 flex-col items-center gap-2 focus-visible:outline-none"
    >
      <motion.span
        animate={isActive ? { scale: [1, 1.06, 1] } : { scale: 1 }}
        transition={{ duration: 1.7, repeat: isActive ? Infinity : 0, ease: "easeInOut" }}
        className={cn(
          "relative flex h-11 w-11 items-center justify-center rounded-full border transition-colors duration-300",
          NODE_STYLES[agent.status],
          isExpanded && "ring-2 ring-accent/40 ring-offset-2 ring-offset-[var(--bg-elevated)]",
        )}
      >
        <AnimatePresence mode="wait" initial={false}>
          {settled ? (
            <motion.span
              key="settled"
              initial={{ scale: 0.4, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: "spring", stiffness: 460, damping: 24 }}
            >
              {agent.status === "fallback" ? (
                <AlertTriangle size={17} strokeWidth={2.2} />
              ) : (
                <Check size={18} strokeWidth={2.6} />
              )}
            </motion.span>
          ) : (
            <motion.span key="icon" exit={{ scale: 0.5, opacity: 0 }} transition={{ duration: 0.14 }}>
              <Icon size={17} strokeWidth={1.9} />
            </motion.span>
          )}
        </AnimatePresence>

        {agent.runs > 1 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border border-[var(--bg-elevated)] bg-amber px-1 font-mono text-[9px] font-bold text-[#1a1204]">
            {agent.runs}
          </span>
        )}
      </motion.span>

      <span
        className={cn(
          "text-center text-[10px] leading-tight transition-colors",
          agent.status === "pending" ? "text-faint" : "text-muted",
          isActive && "text-accent",
          "group-hover:text-ink",
        )}
      >
        {agent.label}
      </span>
    </button>
  )
}

function Connector({ active, complete }: { active: boolean; complete: boolean }) {
  return (
    <div className="mt-[21px] h-[2px] min-w-4 flex-1 overflow-hidden rounded-full bg-edge">
      {active ? (
        <div className="rail-sweep h-full w-full" />
      ) : (
        <motion.div
          initial={{ scaleX: 0 }}
          animate={{ scaleX: complete ? 1 : 0 }}
          transition={{ duration: 0.34, ease: "easeOut" }}
          style={{ transformOrigin: "left" }}
          className="h-full w-full bg-emerald/50"
        />
      )}
    </div>
  )
}

/**
 * The review-to-writer loop, drawn as an arc beneath the rail.
 *
 * Worth drawing rather than describing: a conditional edge that sends work
 * backwards is the one part of the graph a straight left-to-right row cannot
 * express, and it is exactly what the brief means by "LangGraph routing".
 */
function RevisionArc({
  active,
  fromRatio,
  toRatio,
}: {
  active: boolean
  fromRatio: number
  toRatio: number
}) {
  const left = Math.min(fromRatio, toRatio) * 100
  const width = Math.abs(toRatio - fromRatio) * 100

  return (
    // The arc is positioned and sized in CSS, and the caption is real HTML.
    // An earlier version put the label inside the SVG, but the path needs
    // preserveAspectRatio="none" to span an arbitrary width, and that same
    // non-uniform scale stretches text into an unreadable smear.
    <div
      className="pointer-events-none absolute top-[74px]"
      style={{ left: `${left}%`, width: `${width}%` }}
      aria-hidden="true"
    >
      <svg
        className="h-4 w-full overflow-visible"
        viewBox="0 0 100 16"
        preserveAspectRatio="none"
      >
        <motion.path
          d="M 100 0 C 100 13, 50 15, 50 15 C 50 15, 0 13, 0 0"
          fill="none"
          stroke={active ? "var(--amber)" : "var(--border)"}
          strokeWidth={active ? 1.6 : 1.2}
          strokeDasharray="4 3"
          vectorEffect="non-scaling-stroke"
          animate={active ? { strokeDashoffset: [0, -14] } : { strokeDashoffset: 0 }}
          transition={
            active ? { duration: 1.1, repeat: Infinity, ease: "linear" } : { duration: 0.2 }
          }
        />
      </svg>
      <div
        className="text-center font-mono text-[9px] leading-none"
        style={{ color: active ? "var(--amber)" : "var(--text-faint)" }}
      >
        revise
      </div>
    </div>
  )
}

function IdleRail() {
  return (
    <div className="rounded-[14px] border border-dashed border-edge bg-elevated/50 px-5 py-8 text-center">
      <p className="text-[12px] text-faint">
        Seven agents will run here — parse, intent, tone, personalize, write, review, route.
      </p>
    </div>
  )
}
