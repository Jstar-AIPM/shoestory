/**
 * 录制 30–60 秒闭环演示（Playwright 原生录屏，webm）
 *
 * 用途：README / GitHub 作品集演示素材、阶段验收证据。
 * 说明：录屏内容包含真实模型生成的品牌鞋款线稿 → 输出到 docs/demo/，默认**不随仓库发布**（见 .gitignore）。
 *
 * 用法：node scripts/record-demo.mjs  （需后端 8787 与前端 3311 均在运行；会真实生成，约 ）
 */
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:3311";
const QUERY = process.env.QUERY ?? "kd12";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR ?? resolve(HERE, "../../docs/demo");

const run = async () => {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome" });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "zh-CN",
    recordVideo: { dir: OUT, size: { width: 1440, height: 900 } },
  });
  const page = await context.newPage();

  const pause = (ms) => page.waitForTimeout(ms);

  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await pause(1200); // 展示首屏

  // ① 输入型号
  await page.getByLabel("鞋款型号").fill(QUERY);
  await pause(600);
  await page.getByRole("button", { name: "生成线稿" }).click();

  // ② 校对 + 源图确认
  await page.getByText(/识别为|没找到/).first().waitFor({ timeout: 60_000 });
  await pause(1800);

  const modelOnly = page.getByRole("button", { name: /直接用型号生成/ });
  const confirmSingle = page.getByRole("button", { name: /就是这双，开始画|用这张开始画/ });
  await Promise.race([
    modelOnly.first().waitFor({ timeout: 120_000 }),
    confirmSingle.first().waitFor({ timeout: 120_000 }),
  ]).catch(() => undefined);
  await pause(1500);

  if (await modelOnly.count()) await modelOnly.first().click();
  else await confirmSingle.first().click();

  // ③ 生成中（真实等待，录屏里能看到阶段推进）
  await page.getByText(/正在处理|去背景|生成黑白线稿|独立质检中|校正到 3:2|后处理/).first().waitFor({ timeout: 60_000 });
  await pause(6000);

  // ④ 效果确认
  await page.getByRole("button", { name: /满意，归档/ }).first().waitFor({ timeout: 180_000 });
  await pause(2600);

  // ⑤ 归档
  await page.getByRole("button", { name: /满意，归档/ }).first().click();
  await pause(900);
  await page.getByLabel("时间 / 日期").fill("2021年6月");
  await pause(900);
  await page.getByLabel("故事").fill("高三那年买的，陪我从教室到球场。");
  await pause(900);
  await page.getByRole("button", { name: /归档进鞋柜/ }).click();
  await page.getByText(/已归档进鞋柜/).first().waitFor({ timeout: 30_000 });
  await pause(2000);

  // ⑥ 打开详情、翻页（展示 3.3 的交互）
  await page.locator("button.group").first().click();
  await page.locator("#shoe-detail-title").waitFor({ timeout: 20_000 });
  await pause(1800);
  const next = page.getByRole("button", { name: /下一双/ });
  if (await next.count()) {
    await next.click();
    await pause(1600);
  }
  await page.keyboard.press("Escape");
  await pause(1200);

  await context.close(); // 关闭上下文才会把视频落盘
  await browser.close();
  console.log("✅ 录屏已保存到 docs/demo/（webm）");
};

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
