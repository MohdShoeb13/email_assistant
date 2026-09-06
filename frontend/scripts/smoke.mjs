/**
 * End-to-end smoke test: drives the real UI against a running backend.
 *
 * Requires both servers up (`uvicorn` on :8000 and `pnpm dev` on :5173) and
 * writes numbered screenshots to the output directory.
 *
 * Uses channel: "chrome" — the locally installed browser — rather than a
 * Playwright-managed build, because `playwright install` needs a download this
 * machine could not complete and the system Chrome works identically here.
 */
import { chromium } from "playwright"
import { mkdirSync } from "node:fs"

const OUT = process.argv[2] || "./shots"
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: "chrome" })
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })

const consoleErrors = []
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text())
})
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`))

function log(...args) {
  console.log(...args)
}

await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.waitForTimeout(600)

// 1. Boot
const title = await page.title()
const bootError = await page.locator("text=Backend unreachable").count()
log(`boot: title="${title}" bootError=${bootError}`)
await page.screenshot({ path: `${OUT}/01-idle-dark.png` })

// 2. Fill and generate
await page.fill("#prompt", "Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday")
await page.fill("#recipient", "Priya")
await page.selectOption("#tone", "friendly")
await page.screenshot({ path: `${OUT}/02-composed.png` })

await page.click("text=Generate draft")

// 3. Wait for the draft to appear
await page.waitForSelector("#body", { timeout: 30000 })
await page.waitForTimeout(1200)

const subject = await page.inputValue("#subject")
const body = await page.inputValue("#body")
log(`draft: subject="${subject}" bodyChars=${body.length}`)

// 4. Pipeline rail state
const railNodes = await page.locator('button[aria-label*=":"]').count()
const railLabels = await page.locator('button[aria-label*=":"]').evaluateAll((els) =>
  els.map((e) => e.getAttribute("aria-label")),
)
log(`rail: ${railNodes} nodes`)
railLabels.forEach((l) => log(`   ${l}`))
await page.screenshot({ path: `${OUT}/03-draft-dark.png`, fullPage: true })

// 5. Trace panel
await page.locator('button:has-text("Model routing")').click()
await page.waitForTimeout(450)
const traceRows = await page.locator("table tbody tr").count()
log(`trace: ${traceRows} rows`)
await page.screenshot({ path: `${OUT}/04-trace.png`, fullPage: true })

// 6. Expand a rail node
await page.locator('button[aria-label*="Draft Writer"]').click()
await page.waitForTimeout(400)
const hasOutput = (await page.locator("pre").count()) > 0
log(`rail node expands with output: ${hasOutput}`)
await page.screenshot({ path: `${OUT}/05-node-expanded.png`, fullPage: true })

// 7. Edit the body, then save style
await page.locator('button[aria-label*="Draft Writer"]').click()
await page.fill("#body", body.replace("Hi Priya,", "Hey Priya —"))
await page.waitForTimeout(250)
const saveDisabled = await page.locator("text=Save my style").isDisabled()
log(`save-my-style enabled after edit: ${!saveDisabled}`)
await page.click("text=Save my style")
await page.waitForTimeout(1200)
const savedMsg = await page.locator("text=/tone stylist now has/").count()
log(`style saved confirmation shown: ${savedMsg > 0}`)
await page.screenshot({ path: `${OUT}/06-edited-saved.png`, fullPage: true })

// 8. Light mode
await page.locator('button[aria-label^="Switch to"]').click()
await page.waitForTimeout(500)
const themeAfter = await page.evaluate(() => document.documentElement.classList.contains("light") ? "light" : "dark")
log(`theme after toggle: ${themeAfter}`)
await page.screenshot({ path: `${OUT}/07-draft-toggled.png`, fullPage: true })

// 9. Contrast sample in light mode
const contrast = await page.evaluate(() => {
  const s = getComputedStyle(document.body)
  return { bg: s.backgroundColor, color: s.color }
})
log(`light body colors: ${JSON.stringify(contrast)}`)

// 10. Profile panel
await page.click("text=Your profile")
await page.waitForTimeout(400)
const evidence = await page.locator("text=/style sample/").count()
log(`profile shows style samples badge: ${evidence > 0}`)
await page.screenshot({ path: `${OUT}/08-profile-toggled.png`, fullPage: true })

log(`\nconsole errors: ${consoleErrors.length}`)
consoleErrors.forEach((e) => log(`   ! ${e}`))

await browser.close()
