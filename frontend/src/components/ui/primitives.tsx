/**
 * The small set of primitives this app actually uses.
 *
 * Hand-written on top of the design tokens rather than pulled in wholesale from
 * a registry: the app needs six components, and each one here is under thirty
 * lines and reads the same CSS variables as everything else. The shadcn
 * convention that matters — open code you own, styled with Tailwind, composed
 * rather than configured — is kept.
 */

import * as React from "react"
import { cn } from "@/lib/utils"

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "rounded-[14px] border border-edge bg-elevated shadow-[var(--shadow-card)]",
        className,
      )}
      {...props}
    />
  ),
)
Card.displayName = "Card"

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center justify-between gap-3 px-5 pt-4 pb-3", className)} {...props} />
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("text-[13px] font-semibold tracking-[-0.01em] text-ink", className)}
      {...props}
    />
  )
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5", className)} {...props} />
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger"
type ButtonSize = "sm" | "md"

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-[#04191d] hover:brightness-110 active:brightness-95 font-semibold light:text-white",
  secondary: "bg-raised text-ink border border-edge hover:border-edge-strong",
  ghost: "text-muted hover:text-ink hover:bg-raised",
  danger: "bg-rose-soft text-rose border border-transparent hover:border-rose/40",
}

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[12px] gap-1.5",
  md: "h-10 px-4 text-[13px] gap-2",
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "secondary", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center rounded-[9px] transition-all duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]",
        "disabled:opacity-40 disabled:pointer-events-none",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    />
  ),
)
Button.displayName = "Button"

const FIELD_BASE =
  "w-full rounded-[9px] border border-edge bg-raised px-3 text-[13px] text-ink placeholder:text-faint " +
  "transition-colors focus:outline-none focus:border-accent/60 focus:ring-2 focus:ring-accent/15"

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(FIELD_BASE, "h-10", className)} {...props} />
  ),
)
Input.displayName = "Input"

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(FIELD_BASE, "py-2.5 leading-relaxed resize-y", className)} {...props} />
))
Textarea.displayName = "Textarea"

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(FIELD_BASE, "h-10 cursor-pointer appearance-none pr-8", className)}
    style={{
      // An inline SVG caret keeps the control looking the same across browsers
      // without shipping an icon font or wrapping it in another element.
      backgroundImage:
        "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M3 4.5 6 7.5 9 4.5' fill='none' stroke='%239b9ba5' stroke-width='1.4' stroke-linecap='round'/%3E%3C/svg%3E\")",
      backgroundRepeat: "no-repeat",
      backgroundPosition: "right 10px center",
      backgroundSize: "12px",
    }}
    {...props}
  >
    {children}
  </select>
))
Select.displayName = "Select"

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "mb-1.5 block text-[11px] font-medium uppercase tracking-[0.07em] text-faint",
        className,
      )}
      {...props}
    />
  )
}

type BadgeTone = "neutral" | "accent" | "amber" | "rose" | "emerald" | "violet"

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-raised text-muted border-edge",
  accent: "bg-accent-soft text-accent border-accent/25",
  amber: "bg-amber-soft text-amber border-amber/25",
  rose: "bg-rose-soft text-rose border-rose/25",
  emerald: "bg-emerald-soft text-emerald border-emerald/25",
  violet: "bg-violet/12 text-violet border-violet/25",
}

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        BADGE_TONES[tone],
        className,
      )}
      {...props}
    />
  )
}
