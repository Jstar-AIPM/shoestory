import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Next.js 16 的开发期安全策略：非白名单来源访问 dev server 会被 403 阻断
   * （表现为客户端 JS 不加载、页面不 hydrate、HMR 失败）。
   * 本地自检用 127.0.0.1 访问，因此显式加入白名单。仅影响 dev，不影响生产构建。
   */
  allowedDevOrigins: ["127.0.0.1", "localhost"],

  /**
   * 阶段 4 部署用：standalone 产物（前端独立部署到 veFaaS）。
   * 本地开发/构建同样可用，不会影响 dev。
   */
  output: "standalone",
};

export default nextConfig;
