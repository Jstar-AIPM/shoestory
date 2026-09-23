import type { NextConfig } from "next";

/**
 * 后端地址：前端通过同源代理调用后端，避免 CORS。
 * ⚠️ rewrites 的目标地址在 **build 时** 固化进产物 —— 部署（阶段 4）时必须在
 * 构建命令里注入 BACKEND_URL，而不是部署后再配运行时环境变量。
 */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8787";

const nextConfig: NextConfig = {
  /** Next.js 16 开发期安全策略：非白名单来源访问 dev server 会被 403 阻断（表现为页面不 hydrate） */
  allowedDevOrigins: ["127.0.0.1", "localhost"],

  /** 阶段 4 部署用：standalone 产物（前端独立部署到 veFaaS） */
  output: "standalone",

  /** 同源代理：/api/* -> 后端 */
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
