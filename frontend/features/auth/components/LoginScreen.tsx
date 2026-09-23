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
        <p className="display-upper text-[13px] text-accent">MY SHOE CABINET</p>
        <h1 className="display-upper mt-3 text-[30px] text-white sm:text-[34px]">履历 · 我的鞋柜</h1>
        <p className="mt-4 text-[14px] leading-relaxed text-muted">
          这是私人的球鞋纪念档案。请输入您收到的邀请码进入**您自己的**鞋柜 ——
          一个邀请码对应一个独立鞋柜，别人看不到您的鞋，您也看不到别人的。
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
          邀请码由项目所有者发放：有效期 30 天、最多可生成 20 双鞋的线稿；
          额度用完后，已归档的鞋柜仍然可以查看。
        </p>
      </div>
    </div>
  );
}
