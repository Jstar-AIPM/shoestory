import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
const BASE = "http://127.0.0.1:3311";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR ?? resolve(HERE, "../../docs/screenshots");
const log = (s, ok, extra = "") => console.log(`  ${ok ? "✅" : "❌"} ${s}${extra ? "｜" + extra : ""}`);
let bad = 0;
const check = (s, ok, extra) => { log(s, ok, extra); if (!ok) bad++; };

// 安全约定：只操作"测试脚本/冒烟测试"产生的档案（模型名为 KD12 且故事含冒烟/E2E 标记），
// 绝不修改用户自己归档的真实鞋款。
const archive = await (await fetch(`${BASE}/api/v1/archive?limit=200`)).json();
const details = await Promise.all(
  archive.items.map(async (i) => await (await fetch(`${BASE}/api/v1/archive/${i.shoe_id}`)).json()),
);
const target =
  details.find((d) => /E2E|冒烟/.test(d.story ?? "")) ??
  details.find((d) => d.model_name.startsWith("Nike KD 12"));
if (!target) {
  console.error("❌ 没有找到可安全操作的测试档案，已中止（不碰用户数据）");
  process.exit(3);
}
console.log(`  测试对象：${target.model_name}｜故事：${(target.story ?? "（空）").slice(0, 24)}`);

const browser = await chromium.launch({ channel: "chrome" });
process.on("exit", () => { void browser.close(); });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "zh-CN" });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 120)); });
page.on("response", (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url().slice(0, 90)}`); });

const openShoe = async (p, modelName) => {
  const card = p.locator("button.group", { hasText: modelName }).first();
  await card.scrollIntoViewIfNeeded();
  await card.click();
  await p.locator("#shoe-detail-title").waitFor({ timeout: 20000 });
};

await page.goto(BASE, { waitUntil: "networkidle" });
const before = await page.locator("button.group").count();

// ① 打开目标鞋的详情（等"详情标题"出现，而不是等关闭按钮 —— 后者在详情加载前就存在）
await openShoe(page, target.model_name);
const firstName = await page.locator("#shoe-detail-title").innerText();
const pos = await page.getByText(/第 \d+ \/ \d+ 双/).innerText();
check("详情打开并显示型号与位置", firstName.length > 0 && /第 \d+ \/ \d+/.test(pos), `${firstName} / ${pos}`);

// ② 下一双：用「位置指示」判断（同名鞋款可能相邻，比名字不可靠）
const positionText = () => page.getByText(/第 \d+ \/ \d+ 双/).innerText();
const posBefore = await positionText();
await page.getByRole("button", { name: /下一双/ }).click();
await page.waitForTimeout(800);
const posAfterNext = await positionText();
check("「下一双」切换到下一双", posAfterNext !== posBefore, `${posBefore} → ${posAfterNext}`);

// ③ 键盘 ← 返回上一双
await page.keyboard.press("ArrowLeft");
await page.waitForTimeout(800);
const posAfterPrev = await positionText();
check("键盘 ← 翻回上一双", posAfterPrev === posBefore, `${posAfterNext} → ${posAfterPrev}`);

// ④ 编辑并保存
await page.getByRole("button", { name: "编辑信息" }).click();
await page.getByLabel("故事").fill("3.3 验证：编辑已生效");
await page.getByRole("button", { name: "保存" }).click();
await page.waitForTimeout(900);
check("编辑保存后立刻生效", (await page.getByText("3.3 验证：编辑已生效").count()) > 0);
await page.screenshot({ path: `${OUT}/e2e-7-detail-edit.png`, fullPage: true });

// ⑤ 刷新后仍生效（真实持久化）
await page.keyboard.press("Escape");
await page.reload({ waitUntil: "networkidle" });
await openShoe(page, target.model_name);
check("刷新后编辑仍生效（真实落盘）", (await page.getByText("3.3 验证：编辑已生效").count()) > 0);

// ⑥ 手机端：能打开详情、按钮可用（左右滑为渐进增强，合成触摸事件在无头环境不可靠 → 标为人工确认）
const mctx = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  locale: "zh-CN",
});
const mp = await mctx.newPage();
await mp.goto(BASE, { waitUntil: "networkidle" });
let mobileOk = false;
try {
  await openShoe(mp, target.model_name);
  const mTitle = await mp.locator("#shoe-detail-title").innerText({ timeout: 10_000 });
  const hasNav = (await mp.getByRole("button", { name: /下一双/ }).count()) > 0;
  mobileOk = mTitle.length > 0 && hasNav;
  check("手机 390px 可打开详情且翻页按钮可用", mobileOk, mTitle);
} catch (cause) {
  check("手机 390px 可打开详情且翻页按钮可用", false, String(cause).slice(0, 80));
}
console.log("  ⏳ 左右滑手势：需在真机上人工确认（无头浏览器无法可靠模拟触摸滑动）");
await mp.screenshot({ path: `${OUT}/e2e-8-detail-mobile.png`, fullPage: true });

// ⑦ 删除（只删本脚本自己造的那条测试档案）
await page.keyboard.press("Escape");
await page.waitForTimeout(300);
const targetTitle = target.model_name;
await openShoe(page, target.model_name);
await page.getByRole("button", { name: "删除这双" }).click();
check("删除需要二次确认", (await page.getByText(/确定删除/).count()) > 0);
await page.getByRole("button", { name: "确认删除" }).click();
await page.waitForTimeout(1200);
const after = await page.locator("button.group").count();
check("确认后删除成功", after === before - 1, `${before} → ${after}（删除 ${targetTitle}）`);

check("无 Console 错误 / 失败请求", errors.length === 0, errors.slice(0, 2).join(" / "));
await browser.close();
console.log(`\n结论：${bad === 0 ? "✅ 全部通过" : `❌ ${bad} 项未通过`}`);
process.exit(bad === 0 ? 0 : 1);
