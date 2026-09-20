import { chromium } from "@playwright/test";
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const failures = [];
page.on("response", (r) => { if (r.status() >= 400) failures.push(`${r.status()} ${r.url().slice(0, 90)}`); });
page.on("console", (m) => { if (m.type() === "error") failures.push(`console: ${m.text().slice(0, 110)}`); });
await page.goto(process.env.TARGET_URL ?? "http://127.0.0.1:3311/", { waitUntil: "networkidle" });
console.log(failures.length ? failures.slice(0, 6).join("\n") : "✅ 无失败请求、无 Console 错误");
await browser.close();
