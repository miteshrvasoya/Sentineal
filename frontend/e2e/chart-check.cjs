/* Checks the interactive price chart in Simple view in a real browser.
 *
 *   make chart-check      (backend and frontend running, with some stored prices; it adds and removes one test purchase)
 *
 * Verifies: hover tooltip shows a date and a rupee price, arrow keys move the reading, drag shows a measured % change,
 * range buttons redraw the chart, trend lines toggle adds lines, and your buys appear as markers with a tooltip.
 */
const { chromium } = require("playwright");
const BASE = process.env.QL_URL || "http://127.0.0.1:3000";
const API = process.env.QL_API || "http://127.0.0.1:8000";
const SYM = process.env.QL_SYMBOL || "INFY";

const fail = [];
const ok = (cond, msg) => { if (!cond) fail.push(msg); console.log(`${cond ? "ok  " : "FAIL"} ${msg}`); };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1300, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const day = (n) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);
  const add = await page.request.post(`${API}/portfolio/transactions`, { data: { symbol: SYM, side: "buy", qty: 3, price: 1000, date: day(120) } });
  const ids = (await add.json()).ids ?? [];

  await page.goto(`${BASE}/s/${SYM}`, { waitUntil: "domcontentloaded" });
  const chart = page.getByTestId("ichart").first();
  await chart.waitFor({ timeout: 40000 });
  const box = await chart.boundingBox();
  const at = (f) => ({ x: box.x + box.width * f, y: box.y + box.height / 2 });

  await page.mouse.move(at(0.5).x, at(0.5).y);
  const tip = page.getByTestId("ichart-tip");
  await tip.waitFor();
  const t1 = await tip.innerText();
  ok(/₹/.test(t1) && /20\d\d/.test(t1), `hover tooltip shows a date and a price (${t1.split("\n").slice(0, 2).join(" | ")})`);
  await page.mouse.move(at(0.8).x, at(0.5).y);
  ok((await tip.innerText()) !== t1, "moving the mouse changes the reading");

  await chart.focus();
  await page.keyboard.press("ArrowLeft");
  const k1 = await tip.innerText();
  await page.keyboard.press("ArrowLeft");
  ok((await tip.innerText()) !== k1, "arrow keys move the reading");

  await page.mouse.move(at(0.3).x, at(0.5).y);
  await page.mouse.down();
  await page.mouse.move(at(0.6).x, at(0.5).y, { steps: 6 });
  await page.mouse.up();
  const m = page.getByTestId("ichart-measure");
  await m.waitFor({ timeout: 3000 });
  ok(/[+-]\d+\.\d%/.test(await m.innerText()), `dragging measures a change (${(await m.innerText()).slice(0, 90)})`);

  const axis = async () => (await chart.locator("text").allInnerTexts()).join("|");
  const before = await axis();
  await page.getByRole("button", { name: "3M", exact: true }).first().click();
  await page.waitForTimeout(300);
  ok((await axis()) !== before, "range button redraws the chart");

  const lines = async () => chart.locator("polyline").count();
  const l0 = await lines();
  await page.locator("label", { hasText: "trend lines" }).locator("input").check({ timeout: 8000 });
  await page.getByRole("button", { name: "1Y", exact: true }).first().click();
  await page.waitForTimeout(300);
  ok((await lines()) > l0 - 0 && (await lines()) >= 2, "trend lines add extra lines");

  const tri = await chart.locator("polygon").count();
  ok(tri >= 2, `your purchase appears as a marker (${tri} polygons incl. the area fill)`);
  const mk = await chart.locator("polygon").nth(1).boundingBox();
  if (mk) {
    await page.mouse.move(mk.x + mk.width / 2, box.y + box.height / 2);
    await page.mouse.move(mk.x + mk.width / 2, mk.y + mk.height - 2);
    await page.waitForTimeout(200);
    ok(/You bought/.test(await tip.innerText().catch(() => "")), "hovering a marker explains the trade");
  }
  for (const id of ids) await page.request.delete(`${API}/portfolio/transactions/${id}`);
  ok(errors.length === 0, `no page errors ${errors.slice(0, 2).join(";")}`);
  await browser.close();
  if (fail.length) { console.log(`\n${fail.length} check(s) failed`); process.exit(1); }
  console.log("\nchart-check OK");
})();
