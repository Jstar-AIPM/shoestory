/**
 * 后端状态 → 前端统一状态映射（纯函数单测）
 * 这是"页面不直接判断后端枚举"的关键保障（前端工程约定 9.1）。
 */
import { describe, expect, it } from "vitest";

import { isPolling, isTerminal, isWaitingUser, toUiState } from "../lib/state/taskState";

describe("toUiState：后端 15 个状态全部有明确映射", () => {
  const cases: Array<[string, string]> = [
    ["created", "submitting"],
    ["resolving", "running"],
    // 线上事故复盘：搜图/预筛移入后台流水线后新增的状态，必须映射为"处理中"且继续轮询
    ["searching_source", "running"],
    ["model_not_found", "waiting_user"],
    ["resolve_failed", "waiting_user"],
    ["awaiting_source_confirm", "waiting_user"],
    ["preprocessing", "running"],
    ["generating", "running"],
    ["refining", "running"],
    ["verifying", "running"],
    ["interrupted", "disconnected"],
    ["awaiting_effect_confirm", "waiting_user"],
    ["archiving", "running"],
    ["archived", "succeeded"],
    ["failed", "failed"],
    ["cancelled", "cancelled"],
  ];

  it.each(cases)("%s → %s", (backend, ui) => {
    expect(toUiState(backend)).toBe(ui);
  });

  it("空值视为 idle", () => {
    expect(toUiState(null)).toBe("idle");
    expect(toUiState(undefined)).toBe("idle");
    expect(toUiState("")).toBe("idle");
  });

  it("未知状态必须安全兜底（不猜成功也不猜失败）", () => {
    expect(toUiState("brand_new_state_from_backend")).toBe("unknown");
  });
});

describe("轮询/终态/等待用户的判定", () => {
  it("运行中与提交中才轮询", () => {
    for (const state of ["created", "resolving", "searching_source", "preprocessing", "generating", "refining", "verifying", "archiving", "interrupted"]) {
      expect(isPolling(state), state).toBe(true);
    }
  });

  it("等待用户确认时停止轮询（状态不会自己变）", () => {
    for (const state of ["awaiting_source_confirm", "awaiting_effect_confirm", "model_not_found", "resolve_failed"]) {
      expect(isPolling(state), state).toBe(false);
      expect(isWaitingUser(state), state).toBe(true);
    }
  });

  it("终态判定：归档/失败/放弃", () => {
    expect(isTerminal("archived")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("cancelled")).toBe(true);
    expect(isTerminal("generating")).toBe(false);
    expect(isTerminal("awaiting_effect_confirm")).toBe(false);
  });
});
