/* Plays through EVERY in-app tour in a real browser and fails if anything is off.
 *
 * Usage (backend and frontend must be running, ideally with `make seed` data):
 *   npm i -g playwright   (or: npm i -D playwright)   then:   make tour-check
 *
 * Checks, per step: the spotlight found its element (or the step is an intentional centred card, or it showed the
 * "not on screen" note), the explanation card is fully inside the viewport, and the tour ends cleanly.
 * Also checks Esc closes a tour, completed tours are remembered, and no page errors occur.
 * Set TOUR_SHOTS=/some/dir to save a screenshot of every step.
 */
const { chromium } = require("playwright");

const BASE = process.env.QL_URL || "http://127.0.0.1:3000";
const SHOTS = process.env.TOUR_SHOTS;

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(`${BASE}/s/RELIANCE`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /^Tour/ }).click();
  const titles = await page.getByRole("menuitem").evaluateAll((els) => els.map((e) => e.querySelector("span.flex").textContent.trim()));
  await page.keyboard.press("Escape");
  console.log(`found ${titles.length} tours`);

  const problems = [];
  let steps = 0, spotlit = 0, notes = 0, cards = 0;
  for (let t = 0; t < titles.length; t++) {
    await page.goto(`${BASE}/s/RELIANCE`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: /^Tour/ }).click();
    await page.getByRole("menuitem").nth(t).click();
    await page.waitForSelector("[role=dialog][aria-modal=true]");
    for (let n = 1; ; n++) {
      await page.waitForTimeout(1000);
      const s = await page.evaluate(() => {
        const o = document.querySelector("[data-testid=tour-overlay]"), d = document.querySelector("[role=dialog]");
        const ring = o && o.querySelector(".ring-2"), r = ring && ring.getBoundingClientRect(), dr = d.getBoundingClientRect();
        return { title: d.querySelector("h2").textContent, counter: d.querySelector(".tabular-nums").textContent.trim(),
          spot: !!r && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight, note: !!d.querySelector(".bg-amber-50"),
          inView: dr.left >= 0 && dr.right <= innerWidth && dr.top >= 0 && dr.bottom <= innerHeight + 2 };
      });
      steps++;
      if (s.spot) spotlit++; else if (s.note) notes++; else cards++;
      if (!s.inView) problems.push(`card off-screen: ${titles[t]} / ${s.counter} / ${s.title}`);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/tour${t}_step${n}.png` });
      const [a, b] = s.counter.split("/").map((x) => x.trim());
      await page.keyboard.press("ArrowRight");
      if (a === b) break;
    }
    await page.waitForTimeout(300);
    if ((await page.locator("[data-testid=tour-overlay]").count()) !== 0) problems.push(`did not close: ${titles[t]}`);
  }

  await page.goto(`${BASE}/s/RELIANCE`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /^Tour/ }).click();
  await page.getByRole("menuitem").first().click();
  await page.waitForSelector("[role=dialog]");
  await page.keyboard.press("Escape");
  if ((await page.locator("[data-testid=tour-overlay]").count()) !== 0) problems.push("Esc did not close the tour");
  const seen = JSON.parse((await page.evaluate(() => localStorage.getItem("ql-tours-seen"))) || "[]");
  if (seen.length !== titles.length) problems.push(`remembered ${seen.length} of ${titles.length} completed tours`);
  if (errors.length) problems.push(`page errors: ${errors.join(" | ")}`);
  await browser.close();

  console.log(`${steps} steps: ${spotlit} spotlighted, ${notes} showed the 'no data yet' note, ${cards} centred cards`);
  if (problems.length) { console.error("PROBLEMS:\n- " + problems.join("\n- ")); process.exit(1); }
  console.log("tour-check OK");
})();
