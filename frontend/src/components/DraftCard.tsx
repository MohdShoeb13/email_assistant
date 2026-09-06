/**
 * The draft, editable in place, plus the reviewer's verdict and the export row.
 *
 * The body is a controlled textarea seeded from the streamed draft. It has to be
 * genuinely editable rather than a preview with a separate edit mode, because
 * the edits are the product: "Save my style" sends the diff back so the tone
 * stylist can learn how this user actually writes.
 */

import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  ExternalLink,
  FileDown,
  Loader2,
  Save,
} from "lucide-react"
import { Badge, Button, Card, CardBody, Input, Label, Textarea } from "@/components/ui/primitives"
import type { EmailDraft, ReviewResult, RunStatus } from "@/lib/types"
import { buildEml, cn, downloadText, mailtoHref, slugify } from "@/lib/utils"

interface Props {
  draft: EmailDraft | null
  review: ReviewResult | null
  status: RunStatus
  signature: string
  recipient: string
  isSaving: boolean
  savedMessage: string | null
  onSaveStyle: (originalBody: string, editedBody: string, subject: string) => void
}

export function DraftCard({
  draft,
  review,
  status,
  signature,
  recipient,
  isSaving,
  savedMessage,
  onSaveStyle,
}: Props) {
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [copied, setCopied] = useState(false)

  // The text the model produced, kept so "Save my style" can diff against it.
  // A ref rather than state: it must not trigger a re-render when it changes,
  // and it must not be reset by the user's own typing.
  const generatedBody = useRef("")

  useEffect(() => {
    if (!draft) return
    setSubject(draft.subject)
    setBody(draft.body)
    generatedBody.current = draft.body
  }, [draft])

  if (!draft) return <EmptyDraft status={status} />

  const fullText = signature ? `${body}\n${signature}` : body
  const isEdited = body.trim() !== generatedBody.current.trim()
  const filename = slugify(subject)

  async function copy() {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${fullText}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard blocked - the download buttons still work */
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-5 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold tracking-[-0.01em]">Draft</h2>
          {status === "needs_review" && <Badge tone="amber">needs review</Badge>}
          {status === "complete" && <Badge tone="emerald">approved</Badge>}
          {isEdited && <Badge tone="violet">edited</Badge>}
        </div>
        {review && <ToneMeter value={review.tone_match} />}
      </div>

      <CardBody className="pt-4">
        <div className="mb-3">
          <Label htmlFor="subject">Subject</Label>
          <Input
            id="subject"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            className="font-medium"
          />
        </div>

        <div className="mb-1">
          <Label htmlFor="body">Body</Label>
          <Textarea
            id="body"
            rows={14}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            className="text-[13.5px] leading-[1.7]"
          />
        </div>

        <div className="mb-4 flex items-center justify-between font-mono text-[10px] text-faint">
          <span>{body.trim() ? body.trim().split(/\s+/).length : 0} words</span>
          {signature && <span>signature appended on export</span>}
        </div>

        {review && review.issues.length > 0 && <IssueList review={review} />}

        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={copy}>
            {copied ? <Check size={13} /> : <Copy size={13} />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            size="sm"
            onClick={() =>
              downloadText(`${filename}.eml`, buildEml(subject, fullText, recipient), "message/rfc822")
            }
          >
            <Download size={13} />
            .eml
          </Button>
          <Button
            size="sm"
            onClick={() =>
              downloadText(`${filename}.md`, `# ${subject}\n\n${fullText}\n`, "text/markdown")
            }
          >
            <FileDown size={13} />
            .md
          </Button>
          <a
            href={mailtoHref(subject, fullText, recipient)}
            className="inline-flex h-8 items-center gap-1.5 rounded-[9px] border border-edge bg-raised px-3 text-[12px] text-ink transition-colors hover:border-edge-strong"
          >
            <ExternalLink size={13} />
            Open in mail
          </a>

          <Button
            size="sm"
            variant={isEdited ? "primary" : "ghost"}
            disabled={!isEdited || isSaving}
            title={
              isEdited
                ? "Teach the tone stylist how you actually write"
                : "Edit the draft first, then save what you changed"
            }
            onClick={() => onSaveStyle(generatedBody.current, body, subject)}
            className="ml-auto"
          >
            {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            Save my style
          </Button>
        </div>

        <AnimatePresence>
          {savedMessage && (
            <motion.p
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-3 overflow-hidden text-[11px] text-emerald"
            >
              {savedMessage}
            </motion.p>
          )}
        </AnimatePresence>
      </CardBody>
    </Card>
  )
}

function ToneMeter({ value }: { value: number }) {
  const percent = Math.round(value * 100)
  const tone = value >= 0.8 ? "var(--emerald)" : value >= 0.6 ? "var(--amber)" : "var(--rose)"

  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-[0.07em] text-faint">tone match</span>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-raised">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
          className="h-full rounded-full"
          style={{ background: tone }}
        />
      </div>
      <span className="w-8 text-right font-mono text-[11px]" style={{ color: tone }}>
        {percent}%
      </span>
    </div>
  )
}

function IssueList({ review }: { review: ReviewResult }) {
  return (
    <div className="mb-4 space-y-2">
      {review.issues.map((issue, index) => (
        <motion.div
          key={`${issue.category}-${index}`}
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.05 }}
          className={cn(
            "rounded-[9px] border px-3 py-2",
            issue.severity === "high"
              ? "border-rose/25 bg-rose-soft"
              : "border-amber/25 bg-amber-soft",
          )}
        >
          <div className="mb-0.5 flex items-center gap-1.5">
            <AlertTriangle
              size={12}
              className={issue.severity === "high" ? "text-rose" : "text-amber"}
            />
            <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted">
              {issue.category} · {issue.severity}
            </span>
          </div>
          <p className="text-[12px] leading-relaxed text-ink">{issue.detail}</p>
          {issue.suggestion && (
            <p className="mt-1 text-[11px] leading-relaxed text-muted">{issue.suggestion}</p>
          )}
        </motion.div>
      ))}
    </div>
  )
}

function EmptyDraft({ status }: { status: RunStatus }) {
  return (
    <Card className="border-dashed">
      <CardBody className="flex min-h-[280px] flex-col items-center justify-center gap-2 py-16 text-center">
        {status === "running" ? (
          <>
            <Loader2 size={20} className="animate-spin text-accent" />
            <p className="text-[12px] text-muted">Writing…</p>
          </>
        ) : (
          <>
            <p className="text-[13px] text-muted">No draft yet</p>
            <p className="max-w-xs text-[12px] leading-relaxed text-faint">
              Describe the email on the left. The draft appears here as soon as the writer
              finishes, while review is still running.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
