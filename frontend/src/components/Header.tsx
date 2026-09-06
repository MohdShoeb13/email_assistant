/** Sticky header: identity, provider status, theme toggle. */

import { useEffect, useState } from "react"
import { Moon, Sun } from "lucide-react"
import { Badge } from "@/components/ui/primitives"
import type { AppConfig } from "@/lib/types"

function readTheme(): "light" | "dark" {
  return document.documentElement.classList.contains("light") ? "light" : "dark"
}

export function Header({ config }: { config: AppConfig | null }) {
  // Seeded from the DOM, which the inline script in index.html has already set.
  // Reading localStorage again here would duplicate that logic and could
  // disagree with what is on screen.
  const [theme, setTheme] = useState<"light" | "dark">(readTheme)

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light")
    try {
      localStorage.setItem("theme", theme)
    } catch {
      /* private mode: the choice just will not persist */
    }
  }, [theme])

  const live = config?.providers.filter((provider) => provider.available) ?? []

  return (
    <header className="sticky top-0 z-30 border-b border-edge bg-[var(--bg)]/80 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between gap-4 px-5">
        <div className="flex items-center gap-2.5">
          <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="var(--bg-raised)" />
            <path
              d="M7 11.5a2.5 2.5 0 0 1 2.5-2.5h13a2.5 2.5 0 0 1 2.5 2.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 7 20.5z"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="1.8"
            />
            <path
              d="m7.8 11 8.2 6 8.2-6"
              fill="none"
              stroke="var(--violet)"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold tracking-[-0.01em]">Email Assistant</div>
            <div className="font-mono text-[10px] text-faint">seven agents · langgraph</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {config?.offline ? (
            <Badge tone="violet" title="No API key configured. Responses are deterministic and local.">
              offline mode
            </Badge>
          ) : (
            live.map((provider) => (
              <Badge key={provider.name} tone="emerald">
                {provider.name}
              </Badge>
            ))
          )}

          <button
            type="button"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
            className="flex h-8 w-8 items-center justify-center rounded-[9px] border border-edge bg-raised text-muted transition-colors hover:border-edge-strong hover:text-ink"
          >
            {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}
          </button>
        </div>
      </div>
    </header>
  )
}
