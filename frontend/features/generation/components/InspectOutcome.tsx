"use client";

/**
 * 体检结论（三档判定）的渲染：
 * - 明确是鞋 → 「认出来了」+ 开始画；
 * - 不确定   → 放行 + 软提示（拒绝太严比选错更伤体验）；
 * - 明确不是鞋 → 友好拒绝（说出"我看到的更像什么"+ 该传什么）。
 */
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusBar } from "@/components/ui/StatusBar";
import { StatusChip } from "@/components/ui/StatusChip";
import type { InspectResponse } from "@/lib/api/types";

export function InspectOutcome({
  inspect,
  busy,
  onStart,
  onReCrop,
  onReset,
}: {
  inspect: InspectResponse;
  busy: boolean;
  onStart: () => void;
  onReCrop: () => void;
  onReset: () => void;
}) {
  // 四档"先不画"：不是鞋 / 不止一只 / 角度不对 / 没框全。
  // 后三档（2026-09-25 产品反馈 7/11/12）以前会被放行去画，结果画出来和实物对不上 ——
  // 与其让人等 30 秒拿到一张不像的图，不如在这里就说清楚。
  const BLOCKED: Record<string, { title: string; tone: "danger" | "warn" }> = {
    not_shoe: { title: "这张先不画了", tone: "danger" },
    multi: { title: "框里不止一只鞋", tone: "warn" },
    not_side_view: { title: "这张角度不太合适", tone: "warn" },
    incomplete: { title: "方框里没框住整只鞋", tone: "warn" },
  };
  const blocked = BLOCKED[inspect.tier];
  if (blocked) {
    const canRecrop = inspect.tier !== "not_shoe";
    return (
      <Card className="px-5 py-5 sm:px-6">
        <Alert tone={blocked.tone} title={blocked.title}>
          <p className="mt-1">{inspect.message}</p>
          {inspect.hint ? <p className="mt-1.5 text-muted">{inspect.hint}</p> : null}
        </Alert>
        <div className="mt-4">
          <StatusBar tone="paper" label="这次没画（不算生成次数，也不用花钱）" meta="换一张就能重试" />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {canRecrop ? (
            <Button variant="primary" className="btn-blurple" onClick={onReCrop}>
              重新框选
            </Button>
          ) : null}
          <Button variant={canRecrop ? "secondary" : "primary"} className={canRecrop ? "" : "btn-blurple"} onClick={onReset}>
            换一张图
          </Button>
        </div>
      </Card>
    );
  }

  const uncertain = inspect.tier === "uncertain";
  const detail = inspect.detail;

  return (
    <Card className="px-5 py-5 sm:px-6">
      <div className="flex flex-wrap items-center gap-2.5">
        <StatusChip tone={uncertain ? "warn" : "success"}>
          {uncertain ? "不太确定" : "识别成功"}
        </StatusChip>
        {detail.display_name ? (
          <h2 className="text-[17px] font-semibold text-ink">{detail.display_name}</h2>
        ) : null}
      </div>

      <p className="mt-2.5 text-[13.5px] leading-relaxed text-muted">{inspect.message}</p>
      {inspect.hint ? (
        <p className="mt-1.5 text-[13px] text-faint">{inspect.hint}</p>
      ) : null}

      {/* 清晰度提示：**只建议、不拦人**（2026-09-25 反馈）——
          以前是短边不够就根本传不上去，界面上还没反应，体验很差。
          现在正常收图、照常能画，糊了才提醒一句，画不画由用户定。 */}
      {inspect.warning ? (
        <p className="mt-2 rounded-[var(--radius-btn)] border border-warn/30 bg-warn/[0.08] px-3 py-2 text-[12.5px] leading-relaxed text-warn">
          {inspect.warning}
        </p>
      ) : null}

      {!uncertain ? (
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-3">
          <Item label="品牌" value={detail.brand} />
          <Item label="型号" value={detail.model_name} />
          <Item label="配色" value={detail.colorway} />
          <Item label="Logo" value={detail.logo_type ? `${detail.logo_type}${detail.logo_position ? ` · ${detail.logo_position}` : ""}` : ""} />
          <Item label="鞋身文字" value={detail.texts.join(" / ")} />
        </dl>
      ) : null}

      <div className="mt-4">
        <StatusBar
          tone="paper"
          label={busy ? "正在开始…" : "认出来了，等您点「开始画」"}
          meta="约 30–60 秒 · 1 次生成额度"
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {/* 「开始画」加一个很轻的呼吸缩放（产品反馈 9）：识别成功后视线本来在数据上，
            按钮不动就容易被忽略。幅度刻意做小，不用彩虹色/弹跳那套。
            prefers-reduced-motion 时会被全局规则关掉。 */}
        <Button
          variant="primary"
          className="btn-blurple cta-pulse"
          onClick={onStart}
          disabled={busy}
        >
          {busy ? "正在开始…" : "开始画"}
        </Button>
        <Button variant="secondary" onClick={onReCrop} disabled={busy}>
          重新框选
        </Button>
        <Button variant="ghost" onClick={onReset} disabled={busy}>
          换一张
        </Button>
      </div>
      <p className="mt-2.5 text-[12.5px] text-faint">
        开始画会消耗 1 次生成额度，出图约 30–60 秒。
      </p>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
      <dt className="text-faint">{label}</dt>
      <dd className="max-w-[60%] truncate text-right font-medium text-ink" title={value}>
        {value}
      </dd>
    </div>
  );
}
