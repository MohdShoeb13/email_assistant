/**
 * The sender's profile, and the count of saved style edits.
 *
 * The evidence count is the visible proof that memory is doing something: it
 * goes up when you save an edit, and the tone stylist reads those same edits on
 * the next run. Without it, personalization is a claim in the README.
 */

import { useEffect, useState } from "react"
import { Check, ChevronDown, Loader2 } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { Badge, Button, Input, Label, Select } from "@/components/ui/primitives"
import type { AppConfig, UserProfile } from "@/lib/types"
import { cn, titleCase } from "@/lib/utils"

interface Props {
  profile: UserProfile | null
  config: AppConfig | null
  onSave: (updates: Partial<UserProfile>) => Promise<void>
}

export function ProfilePanel({ profile, config, onSave }: Props) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Partial<UserProfile>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (profile) setDraft({})
  }, [profile])

  if (!profile) return null

  const value = (key: keyof UserProfile) => (draft[key] as string) ?? (profile[key] as string) ?? ""
  const dirty = Object.keys(draft).length > 0
  const evidence = profile.style_evidence_count ?? 0

  async function save() {
    setSaving(true)
    try {
      await onSave(draft)
      setDraft({})
      setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-[14px] border border-edge bg-elevated shadow-[var(--shadow-card)]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold tracking-[-0.01em]">Your profile</span>
          {evidence > 0 && (
            <Badge tone="violet" title="Saved edits the tone stylist learns from">
              {evidence} style {evidence === 1 ? "sample" : "samples"}
            </Badge>
          )}
        </div>
        <ChevronDown
          size={15}
          className={cn("shrink-0 text-faint transition-transform duration-200", open && "rotate-180")}
        />
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
            <div className="space-y-3 border-t border-edge px-5 py-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="p-name">Name</Label>
                  <Input
                    id="p-name"
                    value={value("name")}
                    onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  />
                </div>
                <div>
                  <Label htmlFor="p-role">Role</Label>
                  <Input
                    id="p-role"
                    value={value("role")}
                    onChange={(event) => setDraft({ ...draft, role: event.target.value })}
                  />
                </div>
              </div>

              <div>
                <Label htmlFor="p-company">Company</Label>
                <Input
                  id="p-company"
                  value={value("company")}
                  onChange={(event) => setDraft({ ...draft, company: event.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="p-signature">Signature</Label>
                <Input
                  id="p-signature"
                  value={value("signature")}
                  placeholder="Appended on export, not written by the model"
                  onChange={(event) => setDraft({ ...draft, signature: event.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="p-tone">Default tone</Label>
                <Select
                  id="p-tone"
                  value={value("default_tone")}
                  onChange={(event) => setDraft({ ...draft, default_tone: event.target.value })}
                >
                  {(config?.tones ?? []).map((tone) => (
                    <option key={tone} value={tone}>
                      {titleCase(tone)}
                    </option>
                  ))}
                </Select>
              </div>

              <Button
                size="sm"
                variant={dirty ? "primary" : "ghost"}
                disabled={!dirty || saving}
                onClick={save}
                className="w-full"
              >
                {saving ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : saved ? (
                  <Check size={13} />
                ) : null}
                {saved ? "Saved" : "Save profile"}
              </Button>

              <p className="text-[11px] leading-relaxed text-faint">
                Edits you save on a draft are stored here as style samples. The tone stylist reads
                the most recent ones on the next run.
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
