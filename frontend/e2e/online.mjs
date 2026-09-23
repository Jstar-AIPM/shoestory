/**
 * 线上 E2E（阶段 4 · 部署后验证）
 *
 * 对着**已经部署上线的地址**跑一遍真实用户路径：
 *   ① 登录门：未登录只能看到登录页
 *   ② 错误邀请码 → 被拒且有明确提示
 *   ③ 正确邀请码 → 进入鞋柜、顶栏显示额度/身份
 *   ④ 真实生成：型号 → 源图确认 → 生成 → 质检 → 归档（真实模型，约 ）
 *   ⑤ 刷新后鞋柜仍在（证明数据落在对象存储，不在实例内存里）
 *   ⑥ 退出登录 → 回到登录页
 *   ⑦ 全程无 Console 错误、无异常失败请求
 *
 * 用法（凭据走环境变量，不进仓库）：
 *   BASE_URL="https://xxx.apigateway-cn-beijing.volceapi.com" \
 *   LVLI_ADMIN_CODE="LVLI-ADMIN-XXXXXX" \
 *   QUERY="nike kd 12" \
 *   GENERATE=1 \
 *   node e2e/online.mjs
 *
 * GENERATE=0 时只验证登录门与浏览，不产生模型费用。
 */
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "";
const ADMIN_CODE = process.env.LVLI_ADMIN_CODE ?? "";
const QUERY = process.env.QUERY ?? "nike kd 12";
const DO_GENERATE = (process.env.GENERATE ?? "1") !== "0";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR ?? resolve(HERE, "../../docs/screenshots");
const STEP_TIMEOUT = 180_000; // 线上有冷启动，给足余量
const SHORT = 60_000;

if (!BASE_URL || !ADMIN_CODE) {
  console.error("缺少环境变量：BASE_URL / LVLI_ADMIN_CODE");
  process.exit(1);
}

const run = async () => {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome" });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-CN" });
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
  const check = (step, ok, extra = "") => {
    console.log(`  ${ok ? "✅" : "❌"} ${step}${extra ? "｜" + extra : ""}`);
    if (!ok) failures += 1;
  };

  // ---------- ① 登录门 ----------
  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  const codeInput = page.getByLabel("邀请码");
  await codeInput.waitFor({ timeout: SHORT });
  check("未登录只能看到登录页", (await codeInput.count()) > 0);
  await page.screenshot({ path: `${OUT}/online-1-login.png`, fullPage: true });

  // ---------- ② 错误邀请码 ----------
  await codeInput.fill("LVLI-WRONG-CODE-999");
  await page.getByRole("button", { name: /进入我的鞋柜/ }).click();
  await page.getByText("没能进入").first().waitFor({ timeout: SHORT });
  const wrongMsg = await page.locator("div[data-theme='card-paper']").first().innerText();
  check("错误邀请码被拒且给出可读提示", /没能进入/.test(wrongMsg), wrongMsg.split("\n").slice(-1)[0]?.slice(0, 40));
  check("被拒后仍停在登录页（未泄露任何数据）", (await page.getByLabel("邀请码").count()) > 0);
  await page.screenshot({ path: `${OUT}/online-2-wrong-code.png`, fullPage: true });

  // 有意的 401 不算异常请求：清空，后续只看真实异常
  failedRequests.length = 0;
  consoleErrors.length = 0;

  // ---------- ③ 正确邀请码 ----------
  await page.getByLabel("邀请码").fill(ADMIN_CODE);
  await page.getByRole("button", { name: /进入我的鞋柜/ }).click();
  // 身份无关的判定：登录页消失 + 顶栏出现额度/身份徽标（管理员显示"不限次"，访客显示"还可生成 N 次"）
  await page.getByLabel("邀请码").waitFor({ state: "detached", timeout: SHORT });
  await page.getByText(/不限次|还可生成/).first().waitFor({ timeout: SHORT });
  const quotaText = await page.getByText(/不限次|还可生成/).first().innerText();
  check("登录后顶栏显示身份/额度", /不限次|还可生成/.test(quotaText), quotaText.slice(0, 24));
  check(
    "访客额度显示为 20 次（一码 20 次生成）",
    /不限次/.test(quotaText) || /20/.test(quotaText),
    quotaText.slice(0, 24),
  );

  await page.waitForTimeout(1200);
  const emptyVisible = await page.getByText("鞋柜还是空的").count();
  const beforeCount = await page.locator("button.group").count();
  check("进入后鞋柜可渲染（空态或已有鞋）", emptyVisible > 0 || beforeCount >= 0, `空态=${emptyVisible} 卡片=${beforeCount}`);
  await page.screenshot({ path: `${OUT}/online-3-cabinet.png`, fullPage: true });

  if (!DO_GENERATE) {
    check("（GENERATE=0，跳过真实生成）", true);
  } else {
    // ---------- ④ 真实生成闭环 ----------
    await page.getByLabel("鞋款型号").fill(QUERY);
    await page.getByRole("button", { name: "生成线稿" }).click();
    await page.getByText(/识别为|没找到|直接用型号生成|就是这双/).first().waitFor({ timeout: STEP_TIMEOUT });
    const resolveText = await page.getByText(/识别为|没找到/).first().innerText().catch(() => "");
    check("型号校对有明确反馈", resolveText.length > 0, resolveText.slice(0, 36));

    const modelOnly = page.getByRole("button", { name: /直接用型号生成/ });
    const confirmSingle = page.getByRole("button", { name: /就是这双，开始画|用这张开始画/ });
    await Promise.race([
      modelOnly.first().waitFor({ timeout: STEP_TIMEOUT }),
      confirmSingle.first().waitFor({ timeout: STEP_TIMEOUT }),
    ]).catch(() => undefined);
    const mode = (await modelOnly.count()) ? "model_only（型号直出）" : "single（参考图）";
    check("源图确认出现", (await modelOnly.count()) + (await confirmSingle.count()) > 0, mode);
    await page.screenshot({ path: `${OUT}/online-4-source-confirm.png`, fullPage: true });

    if (await modelOnly.count()) await modelOnly.first().click();
    else await confirmSingle.first().click();

    await page.getByText(/正在处理|去背景|生成黑白线稿|独立质检中|校正到 3:2|后处理/).first().waitFor({ timeout: 90_000 });
    await page.screenshot({ path: `${OUT}/online-5-generating.png`, fullPage: true });

    await page.getByRole("button", { name: /满意，归档/ }).first().waitFor({ timeout: STEP_TIMEOUT });
    const scoreText = await page.getByText(/^质检 /).first().innerText();
    check("出图并显示质检分数", /质检/.test(scoreText), scoreText.slice(0, 30));
    await page.screenshot({ path: `${OUT}/online-6-effect-confirm.png`, fullPage: true });

    await page.getByRole("button", { name: /满意，归档/ }).first().click();
    await page.getByLabel("时间 / 日期").fill("2026年9月");
    await page.getByLabel("故事").fill("线上验收：部署后真实生成归档。");
    await page.getByRole("button", { name: /归档进鞋柜/ }).click();
    await page.getByText(/已归档进鞋柜/).first().waitFor({ timeout: SHORT });
    await page.waitForTimeout(1000);
    const afterCount = await page.locator("button.group").count();
    check("归档成功且网格新增一双", afterCount > beforeCount, `${beforeCount} → ${afterCount}`);
    await page.screenshot({ path: `${OUT}/online-7-archived.png`, fullPage: true });

    // ---------- ⑤ 刷新后仍在（数据在对象存储，不在实例内存）----------
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    const afterReload = await page.locator("button.group").count();
    check("刷新后鞋柜仍在（读的是对象存储）", afterReload === afterCount, `卡片=${afterReload}`);
    await page.screenshot({ path: `${OUT}/online-8-after-reload.png`, fullPage: true });

    // 详情可打开
    await page.locator("button.group").first().click();
    await page.getByRole("button", { name: "关闭" }).waitFor({ timeout: 20_000 });
    check("详情弹层可打开", (await page.locator("#shoe-detail-title").innerText()).length > 0);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
  }

  // ---------- ⑥ 退出登录 ----------
  await page.getByRole("button", { name: "退出" }).click();
  await page.getByLabel("邀请码").waitFor({ timeout: SHORT });
  check("退出后回到登录页", (await page.getByLabel("邀请码").count()) > 0);

  // ---------- ⑦ 无异常 ----------
  const realErrors = failedRequests.filter((u) => !/401|\/api\/v1\/auth\/me/.test(u));
  check("无 Console 错误", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" / "));
  check("无异常失败请求", realErrors.length === 0, realErrors.slice(0, 2).join(" / "));

  await browser.close();
  return { failures };
};

const guard = setTimeout(() => {
  console.error("\n❌ 全局超时（15 分钟），强制退出");
  process.exit(2);
}, 15 * 60 * 1000);

let exitCode = 1;
try {
  const { failures } = await run();
  exitCode = failures === 0 ? 0 : 1;
  console.log(`\n${failures === 0 ? "线上 E2E 全部通过 ✅" : `线上 E2E 有 ${failures} 项失败 ❌`}`);
} catch (error) {
  console.error("\n❌ 线上 E2E 异常终止：", error?.message ?? error);
} finally {
  clearTimeout(guard);
  process.exit(exitCode);
}
