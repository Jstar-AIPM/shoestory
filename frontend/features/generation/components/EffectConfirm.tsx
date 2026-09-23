"use client";

/**
 * 效果确认：画稿挂在"墙上"（深色底更像装裱作品），
 * 质检与操作放在"纸上"（易读、可长按阅读）。
 * 三个选项语义化：满意归档 / 重新生成 / 重新输入（前端工程约定 11.1）。
 */
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/StatusChip";
import type { TaskOut } from "@/lib/api/types";

const CHECK_LABELS: Record<string, string> = {
  shoe_silhouette_match: "鞋型吻合",
  logo_legibility: "Logo 可辨识",
  style_consistency: "风格一致",
  noise_level: "画面干净",
  canvas_ratio: "画布规格",
  logo_filled: "Logo 填实",
  laces_solid_ratio: "鞋带实心度",
  text_legible: "文字可辨",
};

export function EffectConfirm({
  task,
  busy,
  onArchive,
  onRegenerate,
  onReset,
}: {
  task: TaskOut;
  busy: boolean;
  onArchive: () => void;
  onRegenerate: () => void;
  onReset: () => void;
}) {
  const quality = task.quality;
  const passed = quality.verdict === "pass" || (quality.score ?? 0) >= 0.8;
  const artworkSrc = task.current_artwork_url ?? "";
  const history = task.artworks.slice(0, -1).reverse();

  return (
    <div className="space-y-5">
      {/* 墙上：画稿（3:2，始终保持比例，不裁切） */}
      <div className="mx-auto w-full max-w-[720px]">
        <div
          data-theme="card-paper"
          className="artwork-paper artwork-frame overflow-hidden rounded-[var(--radius-card)] border border-line"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={artworkSrc}
            alt={`${task.normalize?.normalized ?? task.query} 的黑白线稿`}
            className="artwork-fade-in frame-3x2"
            style={{ objectFit: "contain" }}
          />
        </div>
      </div>

      {/* 纸上：质检 + 操作 */}
      <Card className="px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-center gap-2.5">
          <StatusChip tone={passed ? "success" : "warn"}>
            质检 {quality.score != null ? quality.score.toFixed(3) : "—"}（阈值 0.80）
          </StatusChip>
          <StatusChip tone="neutral">第 {task.artworks.at(-1)?.attempt ?? 1} 次尝试</StatusChip>
          {!passed ? <StatusChip tone="danger">未达到交付标准</StatusChip> : null}
        </div>

        {quality.checks && Object.keys(quality.checks).length > 0 ? (
          <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-[13px] text-muted sm:grid-cols-3">
            {Object.entries(quality.checks).map(([key, value]) => (
              <li key={key} className="flex items-center justify-between gap-2">
                <span>{CHECK_LABELS[key] ?? key}</span>
                <span className="font-mono text-ink">{typeof value === "number" ? value.toFixed(2) : String(value)}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {quality.issues?.length ? (
          <div className="mt-4">
            <Alert tone={passed ? "warn" : "danger"} title="质检给出的问题">
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {quality.issues.slice(0, 5).map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </Alert>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            className="btn-blurple"
            onClick={onArchive}
            disabled={busy || !task.can?.archive}
          >
            满意，归档
          </Button>
          <Button variant="secondary" onClick={onRegenerate} disabled={busy || !task.can?.regenerate}>
            重新生成
          </Button>
          <Button variant="ghost" onClick={onReset}>
            重新输入
          </Button>
        </div>
        <p className="mt-2.5 text-[12.5px] text-faint">
          「重新生成」会保留型号与参考图，并消耗 1 次生成额度；上一张会留在历史里可对比。
        </p>

        {history.length > 0 ? (
          <details className="mt-4">
            <summary className="cursor-pointer select-none text-[13px] text-muted">
              历史尝试（{history.length}）
            </summary>
            <div className="mt-3 flex flex-wrap gap-3">
              {history.map((item) => (
                <a
                  key={item.attempt}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  data-theme="card-paper"
                  className="block w-[150px] overflow-hidden rounded-[var(--radius-btn)] border border-line bg-white"
                  title={`第 ${item.attempt} 次 · 分数 ${item.score ?? "—"}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={item.url} alt={`第 ${item.attempt} 次画稿`} className="frame-3x2" style={{ objectFit: "contain" }} />
                  <span className="block px-2 py-1 text-[11.5px] text-muted">
                    第 {item.attempt} 次 · {item.score ?? "—"}
                  </span>
                </a>
              ))}
            </div>
          </details>
        ) : null}
      </Card>
    </div>
  );
}
