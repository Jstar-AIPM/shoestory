import { defineConfig } from "vitest/config";

/**
 * 单元/组件测试（前端手册 21.2：状态映射、数据转换、校验、错误归一化）
 * 环境用 jsdom 以支持组件测试；纯函数测试不受影响。
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    globals: true,
  },
});
