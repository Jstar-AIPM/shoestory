"use client";

/**
 * 效果确认：画稿挂在"墙上"（深色底更像装裱作品），操作放在"纸上"。
 *
 * 三个选择：满意收进鞋柜 / 不满意重新画 / 换一张图。
 * ⚠️ 质检细节（分项分数、问题清单）**不对外显示**（2026-09-23 产品反馈）：
 * 用户只需要判断"满不满意"；质检仍在内部照常执行，明细留在接口与轨迹里备查。
 */
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusBar } from "@/components/ui/StatusBar";
import type { TaskOut } from "@/lib/api/types";

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
        {/* 状态条紧贴画稿下方（原来在顶栏，离用户看的东西太远） */}
        <div className="mt-3">
          <StatusBar
            label={passed ? "画好了，等您确认后收进鞋柜" : quality.note || "画好了，等您确认后收进鞋柜"}
            pulse={false}
          />
        </div>
      </div>

      {/* 纸上：只留「满意 / 不满意」两个选择。
          质检细节（分项打分与问题清单）**不外显** —— 内部照常执行，结果留在接口与日志里备查（2026-09-23 反馈）。 */}
      <Card className="px-5 py-5 sm:px-6">
        <h2 className="text-[17px] font-semibold text-ink">这张您满意吗？</h2>
        <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
          满意就收进鞋柜；不满意可以再画一张（会重新消耗 1 次生成额度，上一张留在历史里可对比）。
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            className="btn-blurple"
            onClick={onArchive}
            disabled={busy || !task.can?.archive}
          >
            满意，收进鞋柜
          </Button>
          <Button variant="secondary" onClick={onRegenerate} disabled={busy || !task.can?.regenerate}>
            不满意，重新画
          </Button>
          <Button variant="ghost" onClick={onReset}>
            换一张图
          </Button>
        </div>

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
