"use client";

/**
 * 画稿下方的小状态条：把「当前状态」放在内容**紧贴着的下方**，而不是跑到顶栏去。
 *
 * 为什么要有它（产品经理反馈 2026-09-23）：
 * - 原来的状态提示在页面顶栏，离用户正在看的东西太远；
 * - 状态条紧贴画稿/图片下沿，一眼能看到"现在在干嘛、还要多久"。
 *
 * 两种外观：
 * - `tone="wall"`（默认，深色墙面上）：半透明深色胶囊；
 * - `tone="paper"`（纸白卡片里，如裁切/体检阶段）：浅色描边。
 */
export function StatusBar({
  label,
  percent,
  meta,
  tone = "wall",
  pulse = false,
  ariaLive = true,
}: {
  label: string;
  /** 0-100；传 undefined 则不显示进度条（例如"等您确认"） */
  percent?: number;
  /** 右侧小字：已用时 / 额度等 */
  meta?: string | null;
  tone?: "wall" | "paper";
  /** 左侧小圆点是否脉冲（进行中才脉冲） */
  pulse?: boolean;
  ariaLive?: boolean;
}) {
  const showTrack = typeof percent === "number";
  return (
    <div
      className={`status-bar ${tone === "paper" ? "status-bar--paper" : ""}`}
      role="status"
      aria-live={ariaLive ? "polite" : "off"}
      aria-atomic="true"
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${pulse ? "animate-pulse" : ""} ${
          tone === "paper" ? "bg-[#5865f2]" : "bg-[#57f287]"
        }`}
      />
      <p className="status-bar__label truncate">{label}</p>
      {showTrack ? (
        <span className="status-bar__track" aria-hidden>
          <span className="status-bar__fill" style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
        </span>
      ) : (
        <span className="flex-1" />
      )}
      {meta ? <span className="status-bar__meta">{meta}</span> : null}
    </div>
  );
}
