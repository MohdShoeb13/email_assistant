/** App shell: composer on the left, pipeline and draft on the right. */

import { useCallback, useEffect, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { CircleAlert } from "lucide-react"
import { Header } from "@/components/Header"
import { Composer, type ComposerValues } from "@/components/Composer"
import { AgentPipeline } from "@/components/AgentPipeline"
import { DraftCard } from "@/components/DraftCard"
import { TracePanel } from "@/components/TracePanel"
import { ProfilePanel } from "@/components/ProfilePanel"
import { useEmailStream } from "@/hooks/useEmailStream"
import { getConfig, getProfile, saveEdit, saveProfile } from "@/lib/api"
import type { AppConfig, UserProfile } from "@/lib/types"

const USER_ID = "default"

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)

  const [values, setValues] = useState<ComposerValues>({
    prompt: "",
    recipient: "",
    tone: "friendly",
    intent: "auto",
    length: "medium",
    routingProfile: "quality",
  })

  const [savingStyle, setSavingStyle] = useState(false)
  const [savedMessage, setSavedMessage] = useState<string | null>(null)

  const run = useEmailStream()

  useEffect(() => {
    let cancelled = false
    Promise.all([getConfig(), getProfile(USER_ID)])
      .then(([loadedConfig, loadedProfile]) => {
        if (cancelled) return
        setConfig(loadedConfig)
        setProfile(loadedProfile)
        // Seed the controls from the server rather than hardcoding defaults
        // twice, so the user's saved tone is what the form opens on.
        setValues((current) => ({
          ...current,
          tone: loadedProfile.default_tone || current.tone,
          routingProfile: loadedConfig.active_profile || current.routingProfile,
        }))
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBootError(
            error instanceof Error ? error.message : "Could not reach the backend on /api",
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const patch = useCallback(
    (update: Partial<ComposerValues>) => setValues((current) => ({ ...current, ...update })),
    [],
  )

  const generate = useCallback(() => {
    setSavedMessage(null)
    void run.start({
      prompt: values.prompt.trim(),
      tone: values.tone,
      intent: values.intent,
      recipient: values.recipient.trim() || null,
      length: values.length,
      user_id: USER_ID,
      routing_profile: values.routingProfile,
    })
  }, [run, values])

  const onSaveStyle = useCallback(
    async (originalBody: string, editedBody: string, subject: string) => {
      if (!run.draftId) return
      setSavingStyle(true)
      try {
        const response = await saveEdit(run.draftId, {
          user_id: USER_ID,
          original_body: originalBody,
          edited_body: editedBody,
          subject,
        })
        setSavedMessage(
          response.saved
            ? `Saved. The tone stylist now has ${response.evidence_count} sample${
                response.evidence_count === 1 ? "" : "s"
              } of how you write.`
            : "Nothing changed, so there was nothing to learn.",
        )
        setProfile(await getProfile(USER_ID))
      } catch (error) {
        setSavedMessage(error instanceof Error ? error.message : "Could not save that edit.")
      } finally {
        setSavingStyle(false)
        setTimeout(() => setSavedMessage(null), 6000)
      }
    },
    [run.draftId],
  )

  const onSaveProfile = useCallback(async (updates: Partial<UserProfile>) => {
    setProfile(await saveProfile(USER_ID, updates))
  }, [])

  if (bootError) return <BootError message={bootError} />

  return (
    <div className="min-h-screen">
      <Header config={config} />

      <main className="mx-auto max-w-[1400px] px-5 py-6">
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(320px,380px)_1fr]">
          <div className="space-y-5 lg:sticky lg:top-20 lg:self-start">
            <Composer
              values={values}
              config={config}
              isRunning={run.isRunning}
              onChange={patch}
              onSubmit={generate}
              onCancel={run.cancel}
            />
            <ProfilePanel profile={profile} config={config} onSave={onSaveProfile} />
          </div>

          <div className="space-y-5">
            <AgentPipeline
              agents={run.agents}
              activeAgent={run.activeAgent}
              statusMessage={run.statusMessage}
              revisionCount={run.revisions.length}
              maxRevisions={config?.max_revisions ?? 2}
            />

            <AnimatePresence>
              {run.error && (
                <motion.div
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  className="flex items-start gap-2 rounded-[12px] border border-rose/25 bg-rose-soft px-4 py-3"
                >
                  <CircleAlert size={15} className="mt-0.5 shrink-0 text-rose" />
                  <p className="text-[12px] leading-relaxed text-ink">{run.error}</p>
                </motion.div>
              )}
            </AnimatePresence>

            <DraftCard
              draft={run.draft}
              review={run.result?.review ?? null}
              status={run.status}
              signature={run.result?.signature ?? profile?.signature ?? ""}
              recipient={values.recipient}
              isSaving={savingStyle}
              savedMessage={savedMessage}
              onSaveStyle={onSaveStyle}
            />

            <TracePanel
              trace={run.trace}
              totals={run.totals}
              routingProfile={run.routingProfile}
              offline={config?.offline ?? false}
            />
          </div>
        </div>
      </main>
    </div>
  )
}

function BootError({ message }: { message: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-5">
      <div className="max-w-md rounded-[14px] border border-rose/25 bg-rose-soft p-6">
        <div className="mb-2 flex items-center gap-2">
          <CircleAlert size={16} className="text-rose" />
          <h1 className="text-[14px] font-semibold">Backend unreachable</h1>
        </div>
        <p className="mb-3 text-[12px] leading-relaxed text-muted">{message}</p>
        <p className="text-[12px] leading-relaxed text-muted">Start it with:</p>
        <pre className="mt-2 overflow-x-auto rounded-[8px] border border-edge bg-elevated p-3 font-mono text-[11px]">
          cd backend{"\n"}uvicorn email_assistant.api.app:app --reload
        </pre>
      </div>
    </div>
  )
}
