/** 错误归一化：后端错误结构 → 前端 AppError（前端工程约定 12.3） */
import { describe, expect, it } from "vitest";

import { NETWORK_ERROR, TIMEOUT_ERROR, normalizeError } from "../lib/api/errors";

describe("normalizeError", () => {
  it("解析后端统一错误结构，并把中文 message 作为 userMessage", () => {
    const error = normalizeError(422, {
      error: { code: "IMAGE_SEARCH_EMPTY", message: "没找到这个型号的清晰图片，请确认型号写法后重试。", detail: { model_name: "X" } },
    });
    expect(error.code).toBe("IMAGE_SEARCH_EMPTY");
    expect(error.userMessage).toContain("没找到这个型号的清晰图片");
    expect(error.retryable).toBe(false);
    expect(error.status).toBe(422);
  });

  it("上游临时故障标记为可重试", () => {
    for (const code of ["UPSTREAM_TIMEOUT", "UPSTREAM_RATE_LIMITED", "GENERATE_FAILED", "INTERNAL_ERROR"]) {
      expect(normalizeError(504, { error: { code, message: "x" } }).retryable, code).toBe(true);
    }
  });

  it("鉴权/输入类错误不可重试（改配置或改输入才有用）", () => {
    for (const code of ["UPSTREAM_AUTH_FAILED", "INVALID_INPUT", "CONFIRM_REQUIRED", "BUDGET_EXCEEDED"]) {
      expect(normalizeError(401, { error: { code, message: "x" } }).retryable, code).toBe(false);
    }
  });

  it("非预期响应（无 error 字段）走安全兜底，不泄露原始内容", () => {
    const error = normalizeError(200, { weird: "payload" });
    expect(error.code).toBe("UNEXPECTED_RESPONSE");
    expect(error.userMessage).toContain("截图");
    expect(error.userMessage).not.toContain("weird");
  });

  it("缺 message 时给出通用中文文案", () => {
    expect(normalizeError(500, { error: { code: "UPSTREAM_ERROR" } }).userMessage).toBe("出错了，请重试。");
  });

  it("网络失败有独立错误码", () => {
    expect(NETWORK_ERROR.code).toBe("NETWORK_ERROR");
    expect(NETWORK_ERROR.userMessage).toContain("网络");
  });

  it("超时（线上冷启动/长连接失效）与断网是不同的提示，且都可重试", () => {
    expect(TIMEOUT_ERROR.code).toBe("REQUEST_TIMEOUT");
    expect(TIMEOUT_ERROR.userMessage).toContain("服务正在启动");
    expect(TIMEOUT_ERROR.retryable).toBe(true);
    expect(TIMEOUT_ERROR.userMessage).not.toBe(NETWORK_ERROR.userMessage);
  });
});
