"use client";

/**
 * 邀请码登录（阶段 4）
 *
 * 上线后未持有效会话一律看不到鞋柜（隐私底线：用户只能看自己的数据）。
 * 文案让访客明白三件事：这是什么、为什么需要邀请码、输错会怎样。
 */
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { login } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import type { AppError } from "@/lib/api/errors";

export function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AppError | null>(null);

  const submit = async () => {
    const value = code.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(value);
      onSuccess();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.appError
          : { code: "UNKNOWN", userMessage: "登录失败，请重试。", retryable: true, status: 0 },
      );
      setBusy(false);
    }
  };

  return (
    <div data-theme="wall" className="wall-gradient flex min-h-screen items-center justify-center px-5">
      <div className="w-full max-w-[460px]">
        {/* 与首页/顶栏同一套排版：英文标识在上，中文主名在下 */}
        <p className="text-[17px] font-extrabold uppercase tracking-[0.2em] text-white sm:text-[19px]">
          Shoestory
        </p>
        <p className="display-upper mt-2 text-[12px] tracking-[0.2em] text-accent">MY SHOE CABINET</p>
        <h1 className="display-upper mt-3 text-[30px] text-white sm:text-[34px]">鞋历</h1>
        <p className="mt-3 text-[14px] text-accent">鞋会穿旧，故事不会。</p>
        {/* JSX 不渲染 Markdown：这里原来写了 **您自己的**，界面上会原样显示星号，已改成 <strong> */}
        <p className="mt-4 text-[14px] leading-relaxed text-muted">
          这是私人的球鞋纪念档案。请输入您收到的邀请码，进入
          <strong className="font-medium text-ink">您自己的</strong>
          鞋柜 —— 一个邀请码对应一个独立鞋柜，别人看不到您的鞋，您也看不到别人的。
        </p>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submit();
            }}
            placeholder="请输入邀请码"
            aria-label="邀请码"
            maxLength={64}
            disabled={busy}
            className="h-12 w-full rounded-full border border-line bg-black/20 px-5 text-[15px] text-ink placeholder:text-faint focus:border-[#5865f2] focus:outline-none disabled:opacity-60"
          />
          <button
            onClick={() => void submit()}
            disabled={!code.trim() || busy}
            className="btn-snow h-12 shrink-0 rounded-full border px-7 text-[15px] font-semibold transition-colors disabled:opacity-50"
          >
            {busy ? "正在进入…" : "进入我的鞋柜"}
          </button>
        </div>

        {error ? (
          <div className="mt-4" data-theme="card-paper">
            <Alert tone="danger" title="没能进入">{error.userMessage}</Alert>
          </div>
        ) : null}

        <p className="mt-6 text-[12.5px] leading-relaxed text-faint">
          邀请码由项目所有者发放：有效期 30 天、最多可生成 20 双鞋的插画；
          额度用完后，已归档的鞋柜仍然可以查看。
        </p>
      </div>
    </div>
  );
}
