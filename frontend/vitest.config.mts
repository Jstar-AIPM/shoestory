import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * 单元/组件测试（前端手册 21.2：状态映射、数据转换、校验、错误归一化）
 * 环境用 jsdom 以支持组件测试；纯函数测试不受影响。
 *
 * `@/*` 别名必须与 tsconfig.json 的 paths 保持一致 —— 否则任何 import 了 `@/…`
 * 的模块（如 lib/api/client.ts）在测试里都加载不了。
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    globals: true,
  },
});
