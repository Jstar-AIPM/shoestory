/**
 * 截图自检脚本（开发/验收用）
 *
 * 为什么不用 `chrome --headless --screenshot`：旧版无头模式会按更宽的视口排版再裁切，
 * 造成"手机端被裁"的假象（实测 scrollWidth 正常却被截断）。Playwright 能精确控制
 * viewport / 设备像素比 / 全页高度，并可直接测量横向溢出。
 *
 * 用法：
 *   node scripts/shots.mjs                 # 输出到 docs/screenshots/
 *   BASE_URL=http://127.0.0.1:3311 node scripts/shots.mjs
 */
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(HERE, "../../docs/screenshots");
const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:3311";

/** 目标宽度（前端手册 16.1：390 / 768 / 1280 / 1440） */
const TARGETS = [
  { name: "desktop-1280", width: 1280, height: 900, scale: 1 },
  { name: "desktop-1440", width: 1440, height: 900, scale: 1 },
  { name: "tablet-768", width: 768, height: 1000, scale: 1 },
  { name: "mobile-390", width: 390, height: 844, scale: 2, mobile: true },
];

/** 开发环境的预览状态切换器（生产构建中不存在） */
const STATES = ["empty", "loading", "populated", "failed"];

async function measure(page) {
  return page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  }));
}

const run = async () => {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome" });
  const results = [];

  for (const target of TARGETS) {
    const context = await browser.newContext({
      viewport: { width: target.width, height: target.height },
      deviceScaleFactor: target.scale,
      isMobile: Boolean(target.mobile),
      hasTouch: Boolean(target.mobile),
      locale: "zh-CN",
    });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(String(error)));

    await page.goto(BASE_URL, { waitUntil: "networkidle" });

    for (const state of STATES) {
      if (!target.mobile) {
        // 只在桌面宽度切换状态，避免重复截很多张
        const label = { populated: "有鞋", empty: "空", loading: "加载中", failed: "失败" }[state];
        const button = page.getByRole("button", { name: label, exact: true });
        if (await button.count()) {
          await button.first().click();
          await page.waitForTimeout(250);
          const cards = await page.locator("button.group").count();
          const emptyText = await page.getByText("鞋柜还是空的").count();
          const ok = state === "populated" ? cards > 0 : emptyText > 0 || cards === 0;
          if (!ok) throw new Error(`状态切换失败：${state}（卡片 ${cards}，空态文案 ${emptyText}）`);
        }
      }
      const suffix = state === "populated" ? "" : `-${state}`;
      await page.screenshot({
        path: resolve(OUT_DIR, `${target.name}${suffix}.png`),
        fullPage: state === "populated",
      });
    }

    const metrics = await measure(page);
    results.push({ target: target.name, ...metrics, consoleErrors });
    await context.close();
  }

  await browser.close();

  console.log("截图输出目录：", OUT_DIR);
  for (const row of results) {
    const flag = row.overflow ? "❌ 横向溢出" : "✅ 无横向溢出";
    const errors = row.consoleErrors.length ? `｜Console 错误 ${row.consoleErrors.length} 条` : "｜Console 无错误";
    console.log(`  ${row.target.padEnd(14)} innerWidth=${row.innerWidth} scrollWidth=${row.scrollWidth}  ${flag}${errors}`);
    row.consoleErrors.slice(0, 3).forEach((error) => console.log(`      - ${error.slice(0, 120)}`));
  }

  if (results.some((row) => row.overflow || row.consoleErrors.length)) process.exitCode = 1;
};

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
