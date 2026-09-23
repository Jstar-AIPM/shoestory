/**
 * 登录与权限隔离验证（阶段 4）
 * 需要在"强制登录"的独立后端 + 指向它的前端上运行：
 *   DATA_DIR=/tmp/lvli-auth-verify ENV=dev FORCE_AUTH=true INVITE_CODES=GUEST-TEST ADMIN_CODE=ADMIN-TEST \
 *     python -m uvicorn app.main:app --port 8788
 *   BACKEND_URL=http://127.0.0.1:8788 npm run build && npx next start -p 3312
 *   BASE_URL=http://127.0.0.1:3312 node scripts/auth-check.mjs
 */
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SHOT_DIR ?? resolve(HERE, "../../docs/screenshots");
const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3312";
const GUEST = process.env.GUEST_CODE ?? "GUEST-TEST";
const ADMIN = process.env.ADMIN_CODE ?? "ADMIN-TEST";
const log = (s, ok, extra = "") => console.log(`  ${ok ? "✅" : "❌"} ${s}${extra ? "｜" + extra : ""}`);
let bad = 0;
const check = (s, ok, extra) => { log(s, ok, extra); if (!ok) bad++; };

const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "zh-CN" });
const page = await ctx.newPage();
const errs = [];
page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 100)); });
// 记录所有 4xx/5xx，用于判断"是否只有预期的鉴权拒绝"
const rejected = [];
page.on("response", (r) => {
  if (r.status() >= 400) rejected.push(`${r.status()} ${new URL(r.url()).pathname}`);
});

// ① 未登录 → 登录页，且看不到任何鞋柜内容
await page.goto(BASE, { waitUntil: "networkidle" });
check("未登录时显示邀请码登录页", (await page.getByLabel("邀请码").count()) > 0);
check("不泄露鞋柜网格", (await page.locator("button.group").count()) === 0);
check("不泄露鞋柜区块标题", (await page.getByText("我的鞋柜", { exact: true }).count()) === 0);
await page.screenshot({ path: `${OUT}/e2e-9-login.png`, fullPage: true });

// ② 错误邀请码被拒
await page.getByLabel("邀请码").fill("WRONG-CODE");
await page.getByRole("button", { name: /进入我的鞋柜/ }).click();
await page.getByText(/邀请码不对/).waitFor({ timeout: 15000 });
check("错误邀请码被拒且有明确提示", true);

// ③ 正确邀请码进入
await page.getByLabel("邀请码").fill(GUEST);
await page.getByRole("button", { name: /进入我的鞋柜/ }).click();
await page.getByText(/鞋柜还是空的/).waitFor({ timeout: 20000 });
check("正确邀请码可进入（新码 → 空鞋柜）", true);
check("顶栏显示剩余额度", (await page.getByText(/还可生成 20 次/).count()) > 0);
await page.screenshot({ path: `${OUT}/e2e-10-logged-in.png`, fullPage: true });

// ④ 普通码进不了管理员控制台
await page.goto(`${BASE}/admin`, { waitUntil: "networkidle" });
await page.getByText(/没有权限|需要管理员码登录/).first().waitFor({ timeout: 15000 });
check("普通邀请码进不了管理员控制台", true);

// ⑤ 退出 → 回到登录页
await page.goto(BASE, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /退出/ }).click();
await page.getByLabel("邀请码").waitFor({ timeout: 15000 });
check("退出后回到登录页", true);

// ⑥ 管理员码登录 → 不限次 + 能看到所有码与用量
await page.getByLabel("邀请码").fill(ADMIN);
await page.getByRole("button", { name: /进入我的鞋柜/ }).click();
await page.getByText(/管理员 · 不限次/).waitFor({ timeout: 20000 });
check("管理员码登录后显示不限次", true);

await page.goto(`${BASE}/admin`, { waitUntil: "networkidle" });
await page.getByText(GUEST).first().waitFor({ timeout: 20000 });
const rows = await page.locator("tbody tr").count();
check("管理员能看到所有邀请码", rows >= 2, `共 ${rows} 行`);
check("管理员码标记为不可作废（硬保护）", (await page.getByText("不可作废").count()) > 0);
check("可见每个码建了几双鞋", (await page.getByText(/0 双/).count()) > 0);
await page.screenshot({ path: `${OUT}/e2e-11-admin.png`, fullPage: true });

// ⑦ 管理员新建邀请码
await page.getByLabel("备注").fill("给 A 公司面试官");
await page.getByRole("button", { name: "创建" }).click();
await page.getByText(/已创建邀请码/).waitFor({ timeout: 15000 });
check("管理员可新建邀请码", true);
const newRows = await page.locator("tbody tr").count();
check("新建后列表增加一行", newRows === rows + 1, `${rows} → ${newRows}`);

// 鉴权过程中一定会有 401/403：断言它们**只来自预期的接口**，且没有 5xx
const unexpected = rejected.filter(
  (item) =>
    !(
      (item.startsWith("401") || item.startsWith("403")) &&
      (item.includes("/api/v1/admin") || item.includes("/api/v1/auth") || item.includes("/api/v1/archive"))
    ),
);
check("所有 4xx 都是预期的鉴权拒绝（无 5xx、无其他接口报错）", unexpected.length === 0, unexpected.slice(0, 3).join(" / "));
const realErrors = errs.filter((text) => !/401|403|Failed to load resource/.test(text));
check("无真正的 Console 错误", realErrors.length === 0, realErrors.slice(0, 2).join(" / "));
await browser.close();
console.log(`\n结论：${bad === 0 ? "✅ 全部通过" : `❌ ${bad} 项未通过`}`);
process.exit(bad === 0 ? 0 : 1);
