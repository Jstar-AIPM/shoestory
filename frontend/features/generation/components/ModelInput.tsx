"use client";

/**
 * 型号输入区（画廊墙上的 hero）
 * 防重复提交：提交中禁用按钮与输入框（前端手册 11.2）。
 */
import { useState } from "react";

export function ModelInput({
  onSubmit,
  submitting,
  disabled,
}: {
  onSubmit: (query: string) => void;
  submitting: boolean;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const blocked = submitting || disabled;

  const submit = () => {
    if (!trimmed || blocked) return;
    onSubmit(trimmed);
  };

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
          }}
          placeholder="例如 kd12 / asics gel nimbus 27"
          maxLength={60}
          disabled={blocked}
          aria-label="鞋款型号"
          className="h-12 w-full rounded-full border border-line bg-black/20 px-5 text-[15px] text-ink placeholder:text-faint focus:border-[#5865f2] focus:outline-none disabled:opacity-60 sm:max-w-[420px]"
        />
        <button
          onClick={submit}
          disabled={!trimmed || blocked}
          className="btn-snow h-12 shrink-0 rounded-full border px-7 text-[15px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "正在提交…" : "生成线稿"}
        </button>
      </div>
      <p className="mt-3 text-[12.5px] text-faint">
        一次生成约 30 秒、消耗 1 次生成额度；生成中可以离开，回来接着看。
      </p>
    </div>
  );
}
