/**
 * HTTP 客户端的超时与重试行为（阶段 4 线上冷启动复盘后新增）
 *
 * 背景：veFaaS 弹性实例空闲后首次请求可能长时间无响应（网关到实例的长连接先失效）。
 * 处理原则：**GET 幂等请求自动重试；写请求（POST/PATCH/DELETE）绝不自动重试** ——
 * 否则"点一次生成"可能变成"扣两次额度、花两次钱"。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { request } from "../lib/api/client";

const okResponse = (payload: unknown = { ok: true }) =>
  new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

/** 模拟"超时"：fetch 直到 signal 被 abort 才 reject（与真实 AbortController 行为一致） */
const hangingFetch = (signal?: AbortSignal | null) =>
  new Promise<Response>((_resolve, reject) => {
    signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  });

describe("request：超时处理与重试策略", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("GET 超时后自动重试，第二次成功就正常返回", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce((_url: string, init: RequestInit) => hangingFetch(init.signal))
      .mockImplementationOnce(() => Promise.resolve(okResponse({ items: [] })));
    vi.stubGlobal("fetch", fetchMock);

    const promise = request("/archive");
    await vi.advanceTimersByTimeAsync(30_000 + 1_500); // 第一次超时 + 退避
    await expect(promise).resolves.toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("GET 一直超时：重试到上限后抛出可读的\"服务正在启动\"提示", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_url: string, init: RequestInit) => hangingFetch(init.signal));
    vi.stubGlobal("fetch", fetchMock);

    const promise = request("/archive");
    const assertion = expect(promise).rejects.toThrow(/服务正在启动/);
    await vi.advanceTimersByTimeAsync(30_000 * 3 + 5_000);
    await assertion;
    // 首次 + 2 次重试
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("POST（写操作）超时绝不自动重试：避免重复扣额度/重复花钱", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((_url: string, init: RequestInit) => hangingFetch(init.signal));
    vi.stubGlobal("fetch", fetchMock);

    const promise = request("/tasks", { method: "POST", body: { query: "kd12" } });
    const assertion = expect(promise).rejects.toThrow(/服务正在启动/);
    await vi.advanceTimersByTimeAsync(30_000 + 10_000);
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("断网（非超时）给出的是网络提示，而不是\"服务正在启动\"", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/archive", { retriesOnTimeout: 0 })).rejects.toThrow(/网络连接中断/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("后端返回业务错误时，原样抛出后端的中文提示且不重试", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "CODE_INVALID", message: "邀请码不对，请检查后重新输入。" } }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/auth/login", { method: "POST", body: { code: "x" } })).rejects.toThrow(
      "邀请码不对，请检查后重新输入。",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
