/**
 * The model-call trace.
 *
 * This is the visible evidence for the brief's "Routing & MCP" criterion —
 * "shows fallback, logs usage or model switching". Every attempt is listed,
 * including the failures, because a trace that only shows successes cannot
 * demonstrate that fallback happened.
 */

import { useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { ChevronDown, CircleAlert, CornerDownRight } from "lucide-react"
import { Badge } from "@/components/ui/primitives"
import type { ModelCall } from "@/lib/types"
import { cn, formatLatency } from "@/lib/utils"

interface Props {
  trace: ModelCall[]
  totals: {
    inputTokens: number
    outputTokens: number
    latencyMs: number
    fallbacks: number
    failures: number
  }
  routingProfile: string | null
  offline: boolean
}

export function TracePanel({ trace, totals, routingProfile, offline }: Props) {
  const [open, setOpen] = useState(false)

  if (trace.length === 0) return null

  return (
    <div className="rounded-[14px] border border-edge bg-elevated shadow-[var(--shadow-card)]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold tracking-[-0.01em]">Model routing</span>
          {routingProfile && <Badge tone="accent">{routingProfile}</Badge>}
          {offline && <Badge tone="violet">offline</Badge>}
          {totals.fallbacks > 0 && (
            <Badge tone="amber">
              {totals.fallbacks} fallback{totals.fallbacks > 1 ? "s" : ""}
            </Badge>
          )}
          {totals.failures > 0 && (
            <Badge tone="rose">
              {totals.failures} failed attempt{totals.failures > 1 ? "s" : ""}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-faint">
          <span className="hidden sm:inline">
            {trace.length} calls · {totals.inputTokens + totals.outputTokens} tokens ·{" "}
            {formatLatency(totals.latencyMs)}
          </span>
          <ChevronDown
            size={15}
            className={cn("transition-transform duration-200", open && "rotate-180")}
          />
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-edge px-5 py-3">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse font-mono text-[11px]">
                  <thead>
                    <tr className="text-left text-faint">
                      <th className="pb-2 pr-3 font-medium">task</th>
                      <th className="pb-2 pr-3 font-medium">provider / model</th>
                      <th className="pb-2 pr-3 text-right font-medium">latency</th>
                      <th className="pb-2 pr-3 text-right font-medium">in</th>
                      <th className="pb-2 pr-3 text-right font-medium">out</th>
                      <th className="pb-2 font-medium">result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trace.map((call, index) => (
                      <motion.tr
                        key={`${call.task}-${call.attempt}-${index}`}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: Math.min(index * 0.02, 0.2) }}
                        className={cn(
                          "border-t border-edge/60",
                          call.outcome === "error" && "text-rose",
                        )}
                      >
                        <td className="py-1.5 pr-3">{call.task}</td>
                        <td className="py-1.5 pr-3">
                          <span className="flex items-center gap-1">
                            {call.is_fallback && (
                              <CornerDownRight size={11} className="shrink-0 text-amber" />
                            )}
                            <span className={cn(call.is_fallback && "text-amber")}>
                              {call.provider}/{call.model}
                            </span>
                          </span>
                        </td>
                        <td className="py-1.5 pr-3 text-right text-muted">
                          {formatLatency(call.latency_ms)}
                        </td>
                        <td className="py-1.5 pr-3 text-right text-muted">{call.input_tokens}</td>
                        <td className="py-1.5 pr-3 text-right text-muted">{call.output_tokens}</td>
                        <td className="py-1.5">
                          {call.outcome === "success" ? (
                            <span className="text-emerald">ok</span>
                          ) : (
                            <span
                              className="flex items-center gap-1"
                              title={call.error_message ?? undefined}
                            >
                              <CircleAlert size={11} />
                              {call.error_type}
                            </span>
                          )}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="mt-3 text-[11px] leading-relaxed text-faint">
                Failed attempts are kept on purpose — they are the only evidence that the router
                fell back. Every line is also appended to{" "}
                <code className="text-muted">backend/data/usage_log.jsonl</code>.
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
