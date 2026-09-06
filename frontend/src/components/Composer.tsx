/** The request form: what to say, to whom, in what voice. */

import { Loader2, Sparkles, Square } from "lucide-react"
import { Button, Card, CardBody, Input, Label, Select, Textarea } from "@/components/ui/primitives"
import type { AppConfig } from "@/lib/types"
import { titleCase } from "@/lib/utils"

export interface ComposerValues {
  prompt: string
  recipient: string
  tone: string
  intent: string
  length: "short" | "medium" | "long"
  routingProfile: string
}

interface Props {
  values: ComposerValues
  config: AppConfig | null
  isRunning: boolean
  onChange: (patch: Partial<ComposerValues>) => void
  onSubmit: () => void
  onCancel: () => void
}

const EXAMPLES = [
  "Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday",
  "Apologise to the client for the wrong figures in yesterday's report",
  "Introduce myself to Sarah at Acme and pitch our onboarding tool",
]

export function Composer({ values, config, isRunning, onChange, onSubmit, onCancel }: Props) {
  const canSubmit = values.prompt.trim().length >= 8 && !isRunning

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl+Enter submits. Plain Enter has to stay as a newline, since the
    // prompt is often two or three lines.
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canSubmit) {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <Card>
      <CardBody className="pt-5">
        <div className="mb-4">
          <Label htmlFor="prompt">What should the email say?</Label>
          <Textarea
            id="prompt"
            rows={5}
            value={values.prompt}
            placeholder="Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday"
            onChange={(event) => onChange({ prompt: event.target.value })}
            onKeyDown={handleKeyDown}
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => onChange({ prompt: example })}
                className="rounded-full border border-edge px-2.5 py-1 text-left text-[11px] text-faint transition-colors hover:border-edge-strong hover:text-muted"
              >
                {example.slice(0, 34)}…
              </button>
            ))}
          </div>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="recipient">Recipient</Label>
            <Input
              id="recipient"
              value={values.recipient}
              placeholder="Optional"
              onChange={(event) => onChange({ recipient: event.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="tone">Tone</Label>
            <Select
              id="tone"
              value={values.tone}
              onChange={(event) => onChange({ tone: event.target.value })}
            >
              {(config?.tones ?? []).map((tone) => (
                <option key={tone} value={tone}>
                  {titleCase(tone)}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="intent">Intent</Label>
            <Select
              id="intent"
              value={values.intent}
              onChange={(event) => onChange({ intent: event.target.value })}
            >
              {(config?.intents ?? []).map((intent) => (
                <option key={intent} value={intent}>
                  {intent === "auto" ? "Detect automatically" : titleCase(intent)}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="length">Length</Label>
            <Select
              id="length"
              value={values.length}
              onChange={(event) =>
                onChange({ length: event.target.value as ComposerValues["length"] })
              }
            >
              {(config?.lengths ?? ["short", "medium", "long"]).map((length) => (
                <option key={length} value={length}>
                  {titleCase(length)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="mb-4">
          <Label htmlFor="profile">Model routing</Label>
          <Select
            id="profile"
            value={values.routingProfile}
            onChange={(event) => onChange({ routingProfile: event.target.value })}
          >
            {(config?.routing_profiles ?? []).map((profile) => (
              <option key={profile} value={profile}>
                {profile === "cost"
                  ? "Cost — cheap models for classification"
                  : "Quality — strongest model throughout"}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex gap-2">
          <Button variant="primary" className="flex-1" disabled={!canSubmit} onClick={onSubmit}>
            {isRunning ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles size={15} />
                Generate draft
              </>
            )}
          </Button>
          {isRunning && (
            <Button variant="secondary" onClick={onCancel} aria-label="Cancel generation">
              <Square size={13} fill="currentColor" />
            </Button>
          )}
        </div>
        <p className="mt-2 text-center font-mono text-[10px] text-faint">
          {navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl"}+Enter to generate
        </p>
      </CardBody>
    </Card>
  )
}
