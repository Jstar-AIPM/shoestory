/**
 * V2 上传图闭环 E2E（对已部署的线上地址跑真实用户路径）
 *
 * 覆盖 V2 的入口与链路（V1 的型号路径由 e2e/online.mjs 覆盖）：
 *   ① 登录门 → 管理员码进入
 *   ② 上传一张真图（本机文件，不进仓库）→ 出现自动建议裁切框
 *   ③ 确认框选 → 体检（真实视觉模型，约 ）→ 显示识别出的品牌+型号
 *   ④ 开始画 → CV 草稿先出现（生成动效）→ AI 稿完成并显示质检分数
 *   ⑤ 满意归档 → 刷新页面 → 鞋柜里那双还在（证明落在对象存储）
 *   ⑥ 全程无 Console 错误、无异常失败请求
 *
 * 用法（凭据与图片都走环境变量/参数，不进仓库）：
 *   BASE_URL="https://xxx.apigateway-cn-beijing.volceapi.com" \
 *   LVLI_ADMIN_CODE="LVLI-ADMIN-XXXXXX" \
 *   IMAGE="/Users/you/鞋.jpg" \
 *   node e2e/upload.mjs
 *
 * 会真实生成一双（本机计算）并留下一条归档；CI 不跑这个脚本。
 */
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "";
const ADMIN_CODE = process.env.LVLI_ADMIN_CODE ?? "";
const IMAGE = process.env.IMAGE ?? "";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR ?? resolve(HERE, "../../docs/screenshots");
const STEP_TIMEOUT = 240_000; // 线上冷启动 + 生成 30–60s，给足余量
const SHORT = 60_000;

if (!BASE_URL || !ADMIN_CODE || !IMAGE) {
  console.error("缺少环境变量：BASE_URL / LVLI_ADMIN_CODE / IMAGE");
  process.exit(1);
}
if (!existsSync(IMAGE)) {
  console.error(`找不到图片：${IMAGE}`);
  process.exit(1);
}

const run = async () => {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome" });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
  const page = await context.newPage();

  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 140));
  });
  page.on("requestfailed", (r) => failedRequests.push(r.url().slice(0, 120)));
  page.on("response", (r) => {
    // 401/429 是有意的（错的邀请码、额度护栏），不算异常
    if (r.status() >= 400 && ![401, 429].includes(r.status())) {
      failedRequests.push(`${r.status()} ${r.url().slice(0, 110)}`);
    }
  });

  let failures = 0;
  // 截图只是旁证，不能因为它超时（线上有长动效/大图）就让整轮 E2E 失败
  const shoot = async (name) => {
    try {
      await page.screenshot({ path: `${OUT}/${name}`, fullPage: true, timeout: 60_000, animations: "disabled" });
    } catch (error) {
      console.log(`  ⚠️ 截图跳过（${name}）：${error.message.split("\n")[0]}`);
    }
  };
  const check = (step, ok, extra = "") => {
    console.log(`  ${ok ? "✅" : "❌"} ${step}${extra ? "｜" + extra : ""}`);
    if (!ok) failures += 1;
  };

  // ---------- ① 登录 ----------
  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await page.getByLabel("邀请码").waitFor({ timeout: SHORT });
  await page.getByLabel("邀请码").fill(ADMIN_CODE);
  await page.getByRole("button", { name: /进入我的鞋柜/ }).click();
  await page.getByText(/管理员 · 不限次|还可生成/).first().waitFor({ timeout: STEP_TIMEOUT });
  check("管理员码登录成功", true);

  // ---------- ② 上传真图 ----------
  await page.locator('input[type="file"]').setInputFiles(IMAGE);
  const confirmButton = page.getByRole("button", { name: "确认框选" });
  await confirmButton.waitFor({ timeout: STEP_TIMEOUT });
  const cropHeading = await page.getByText("框出您要画的那一双").count();
  check("上传后出现自动建议裁切框（可拖动）", cropHeading > 0);
  await shoot("v2-1-crop.png");

  // ---------- ③ 体检（真实视觉模型）----------
  await confirmButton.click();
  const recognized = page.getByText("识别成功");
  await recognized.waitFor({ timeout: STEP_TIMEOUT });
  const inspectText = await page.locator("body").innerText();
  const nameLine = inspectText.split("\n").find((line) => /Nike|ASICS|adidas|Jordan|New Balance|PUMA|安踏|李宁/i.test(line)) ?? "";
  check("体检识别出鞋（品牌/型号）", inspectText.includes("品牌"), nameLine.trim().slice(0, 40));
  await shoot("v2-2-inspect.png");

  // ---------- ④ 开始画：草稿动效 → 正式稿 ----------
  await page.getByRole("button", { name: "开始画" }).click();
  // 注：质检明细自 2026-09-23 起不再对用户显示（用户只需要判断"满不满意"），
  // 所以这里等的是状态条 + 画稿本身，而不是分数。
  await page.getByText(/画好了，等您确认/).first().waitFor({ timeout: STEP_TIMEOUT });
  const artworkImg = page.locator("img[alt$='的插画']").first();
  await artworkImg.waitFor({ timeout: STEP_TIMEOUT });
  // 等图片**真的解码出来**再判：状态条出现时图片可能还在下载/解码，
  // 单次 evaluate 会误判成"没加载"（自测踩过）。
  const loaded = await page
    .waitForFunction(
      () => {
        const el = document.querySelector("img[alt$='的插画']");
        return !!el && el.naturalWidth > 0 && el.complete;
      },
      null,
      { timeout: STEP_TIMEOUT },
    )
    .then(() => true)
    .catch(() => false);
  const box = await artworkImg.boundingBox();
  check("产出画稿并真正加载出图", loaded && !!box && box.width > 200, `尺寸 ${box?.width ?? 0}×${box?.height ?? 0}`);
  // 展示层按风格分派：水彩稿自带纸底，**不能**再叠牛皮纸 + multiply，否则会被染成褐色。
  const frameClass = (await artworkImg.evaluate((el) => el.parentElement?.className ?? "")) || "";
  check(
    "水彩稿没有被叠上牛皮纸层",
    frameClass.includes("artwork-plain") && !frameClass.includes("artwork-paper"),
    frameClass.trim().slice(0, 48),
  );
  await shoot("v2-3-artwork.png");

  // ---------- ⑤ 归档 → 刷新仍在 ----------
  await page.getByRole("button", { name: "满意，收进鞋柜" }).click();
  await page.getByRole("button", { name: "归档进鞋柜" }).click();
  await page.getByText(/已归档/).first().waitFor({ timeout: STEP_TIMEOUT });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText(/已归档|鞋柜/).first().waitFor({ timeout: STEP_TIMEOUT });
  const gridCount = await page.locator("img[alt$='的插画']").count();
  check("刷新后鞋柜里那双还在（数据在对象存储）", gridCount >= 1, `画稿数=${gridCount}`);
  await shoot("v2-4-archived.png");

  check("无 Console 错误", consoleErrors.length === 0, consoleErrors[0] ?? "");
  check("无异常失败请求", failedRequests.length === 0, failedRequests[0] ?? "");

  await browser.close();
  console.log(failures === 0 ? "\nV2 上传闭环 E2E：全部通过 ✅" : `\nV2 上传闭环 E2E：${failures} 项未通过 ❌`);
  process.exit(failures === 0 ? 0 : 1);
};

run().catch((error) => {
  console.error("E2E 执行失败：", error.message);
  process.exit(1);
});
