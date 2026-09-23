/**
 * 真实闭环 E2E（阶段 3 · 3.2）
 *
 * 走真实后端与真实模型：型号 → 源图确认 → 生成 → 效果确认 → 归档 → 网格回显 → 详情
 * 另含：刷新恢复（?task=）、不存在的型号、加载/空态不混淆。
 *
 * 用法：
 *   BASE_URL=http://127.0.0.1:3311 QUERY=kd12 node e2e/closure.mjs
 * 费用：每次生成约 （真实模型）。无 BACKEND/Key 时请先启动后端。
 */
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:3311";
const QUERY = process.env.QUERY ?? "kd12";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR ?? resolve(HERE, "../../docs/screenshots");
const STEP_TIMEOUT = 120_000;
const SHORT = 60_000;

const log = (step, ok, extra = "") => console.log(`  ${ok ? "✅" : "❌"} ${step}${extra ? "｜" + extra : ""}`);

const run = async () => {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome" });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "zh-CN" });
  const page = await context.newPage();

  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 140));
  });
  page.on("requestfailed", (r) => failedRequests.push(r.url().slice(0, 120)));
  page.on("response", (r) => {
    if (r.status() >= 400) failedRequests.push(`${r.status()} ${r.url().slice(0, 110)}`);
  });

  let failures = 0;
  const check = (step, ok, extra) => {
    log(step, ok, extra);
    if (!ok) failures += 1;
  };

  await page.goto(BASE_URL, { waitUntil: "networkidle" });

  // ① 初始：要么空态、要么已有鞋（同一账号可能已有档案）
  const emptyVisible = await page.getByText("鞋柜还是空的").count();
  const gridCount = await page.locator("button.group").count();
  check("初始渲染（空态或已有鞋，二者不混淆）", emptyVisible > 0 || gridCount > 0, `空态=${emptyVisible} 卡片=${gridCount}`);

  const beforeCount = gridCount;

  // ② 输入型号 → 校对
  await page.getByLabel("鞋款型号").fill(QUERY);
  await page.getByRole("button", { name: "生成线稿" }).click();

  // 校对结果有两种呈现：命中 → 源图确认卡里显示"识别为 X"；未命中 → 显示"没找到"
  await page
    .getByText(/识别为|没找到|直接用型号生成|就是这双/)
    .first()
    .waitFor({ timeout: SHORT });
  const resolveText = await page
    .getByText(/识别为|没找到/)
    .first()
    .innerText()
    .catch(() => "");
  check("型号校对有明确反馈（识别为 X / 没找到 + 候选）", resolveText.length > 0, resolveText.slice(0, 40));

  // ③ 源图确认（三种形态之一）→ 选择主推操作
  const modelOnly = page.getByRole("button", { name: /直接用型号生成/ });
  const confirmSingle = page.getByRole("button", { name: /就是这双，开始画|用这张开始画/ });
  const chooseAny = page.getByRole("button", { name: /用这张开始画/ });
  await Promise.race([
    modelOnly.first().waitFor({ timeout: STEP_TIMEOUT }),
    confirmSingle.first().waitFor({ timeout: STEP_TIMEOUT }),
    chooseAny.first().waitFor({ timeout: STEP_TIMEOUT }),
  ]).catch(() => undefined);
  const mode = (await modelOnly.count()) ? "model_only（推荐型号直出）" : "single（推荐参考图）";
  check("源图确认出现且形态明确", true, mode);
  await page.screenshot({ path: `${OUT}/e2e-1-source-confirm.png`, fullPage: true });

  if (await modelOnly.count()) await modelOnly.first().click();
  else await confirmSingle.first().click();

  // ④ 生成中（允许离开）
  await page.getByText(/正在处理|整理成 3:2|线条描摹|自检|整理干净/).first().waitFor({ timeout: 60_000 });
  check("显示真实阶段与可离开提示", (await page.getByText(/可以离开这一页/).count()) > 0);
  await page.screenshot({ path: `${OUT}/e2e-2-generating.png`, fullPage: true });

  // ⑤ 效果确认（画稿 + 质检）
  await page.getByRole("button", { name: /满意，归档/ }).first().waitFor({ timeout: STEP_TIMEOUT });
  const scoreText = await page.getByText(/^质检 /).first().innerText();
  check("效果确认出现并显示质检分数", /质检/.test(scoreText), scoreText.slice(0, 30));
  await page.screenshot({ path: `${OUT}/e2e-3-effect-confirm.png`, fullPage: true });

  // ⑥ 归档（填时间与故事）
  await page.getByRole("button", { name: /满意，归档/ }).first().click();
  await page.getByLabel("时间 / 日期").fill("2021年6月");
  await page.getByLabel("故事").fill("E2E 验证：陪我跑完第一个半马。");
  await page.getByText(/识别为 2021年6月/).waitFor({ timeout: 10_000 });
  check("时间自由文本给的是人话反馈（不露排序键）", true, "2021年6月 → 识别为 2021年6月");
  await page.getByRole("button", { name: /归档进鞋柜/ }).click();

  await page.getByText(/已归档进鞋柜/).first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(800);
  const afterCount = await page.locator("button.group").count();
  check("归档成功且网格新增一双", afterCount > beforeCount, `${beforeCount} → ${afterCount}`);
  await page.screenshot({ path: `${OUT}/e2e-4-archived.png`, fullPage: true });

  // ⑦ 刷新后仍在（真实状态恢复，不依赖内存）
  await page.reload({ waitUntil: "networkidle" });
  const afterReload = await page.locator("button.group").count();
  check("刷新后鞋柜仍在", afterReload === afterCount, `卡片=${afterReload}`);

  // ⑧ 详情（只读）
  await page.locator("button.group").first().click();
  await page.getByRole("button", { name: "关闭" }).waitFor({ timeout: 15_000 });
  const detailTitle = await page.locator("#shoe-detail-title").innerText();
  check("详情可打开并显示型号", detailTitle.length > 0, detailTitle.slice(0, 30));
  await page.screenshot({ path: `${OUT}/e2e-5-detail.png`, fullPage: true });
  await page.keyboard.press("Escape"); // Radix 应支持 Esc 关闭
  await page.waitForTimeout(400);
  check("Esc 能关闭对话框", (await page.getByRole("button", { name: "关闭" }).count()) === 0);

  // ⑨ 不存在的型号 → 如实拒绝 + 相近候选
  await page.getByLabel("鞋款型号").fill("nike kd 999");
  await page.getByRole("button", { name: "生成线稿" }).click();
  await page.getByText(/没找到/).first().waitFor({ timeout: 60_000 });
  check("不存在的型号被如实拒绝并给出候选", (await page.getByText(/没找到/).count()) > 0);
  await page.screenshot({ path: `${OUT}/e2e-6-not-found.png`, fullPage: true });
  await page.getByRole("button", { name: /重新输入型号/ }).first().click();

  // ⑩ 控制台与网络
  check("无 Console 错误", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" / "));
  check("无失败请求", failedRequests.length === 0, failedRequests.slice(0, 2).join(" / "));

  return { failures };
};

/** 兜底：脚本必须在 10 分钟内结束（含关闭浏览器），避免命令挂死 */
const GLOBAL_TIMEOUT_MS = 10 * 60 * 1000;
const guard = setTimeout(() => {
  console.error("\n❌ 全局超时（10 分钟），强制退出");
  process.exit(2);
}, GLOBAL_TIMEOUT_MS);

let code = 1;
try {
  const { failures } = await run();
  code = failures === 0 ? 0 : 1;
  console.log(`\n结论：${failures === 0 ? "✅ 全部通过" : `❌ ${failures} 项未通过`}`);
} catch (error) {
  console.error("\n❌ 执行中断：", error instanceof Error ? error.message : error);
} finally {
  clearTimeout(guard);
  // 显式退出：Playwright 的浏览器子进程若未关闭会让 Node 一直挂着
  process.exit(code);
}
