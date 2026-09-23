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
  if (inspect.tier === "not_shoe") {
    return (
      <Card className="px-5 py-5 sm:px-6">
        <Alert tone="danger" title="这张先不画了">
          <p className="mt-1">{inspect.message}</p>
          {inspect.hint ? <p className="mt-1.5 text-muted">{inspect.hint}</p> : null}
        </Alert>
        <div className="mt-4">
          <StatusBar tone="paper" label="这次没画（不算生成次数，也不用花钱）" meta="换一张就能重试" />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" className="btn-blurple" onClick={onReset}>
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
      {uncertain ? (
        <p className="mt-1.5 text-[13px] text-faint">{inspect.hint}</p>
      ) : inspect.hint ? (
        <p className="mt-1.5 text-[13px] text-faint">{inspect.hint}</p>
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
        <Button variant="primary" className="btn-blurple" onClick={onStart} disabled={busy}>
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
        开始画会消耗 1 次生成额度，出图约 30 秒；Logo 会按识别结果填实。
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
