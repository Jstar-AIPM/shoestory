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
import { artworkFrameClass } from "@/lib/utils/artwork";
import { emphasisOptions } from "@/lib/api/tasks";
import { useEffect, useState } from "react";

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
  onRegenerate: (emphasis?: string) => void;
  onReset: () => void;
}) {
  // 「不满意，重新画」先让人选一个方向（产品反馈 10）。
  // 每次重画都花 1 次额度，让用户把"哪里不对"说清楚，比换个种子再抽一次有用得多。
  // 选项来自后端 prompts/emphasis.yaml（与注入提示词的强化句是同一条记录）。
  const [picking, setPicking] = useState(false);
  const [options, setOptions] = useState<{ key: string; label: string }[]>([]);
  const [picked, setPicked] = useState("");

  useEffect(() => {
    if (!picking || options.length > 0) return;
    emphasisOptions()
      .then(setOptions)
      .catch(() => setOptions([])); // 拿不到选项就退回"普通重画"，不阻塞
  }, [picking, options.length]);

  const quality = task.quality;
  const passed = quality.verdict === "pass" || (quality.score ?? 0) >= 0.8;
  const artworkSrc = task.current_artwork_url ?? "";
  // 历史稿 = 除“当前展示的那一张”之外的其他尝试。
  // 不能简单用 slice(0, -1)：最优稿不一定是最后一次（先看是否通过质检，再看分数）。
  const history = task.artworks
    .filter((item) => item.attempt !== task.current_attempt)
    .slice()
    .reverse();

  return (
    <div className="space-y-5">
      {/* 墙上：画稿（3:2，始终保持比例，不裁切） */}
      <div className="mx-auto w-full max-w-[720px]">
        <div
          data-theme="card-paper"
          className={`${artworkFrameClass(task.style_id)} artwork-frame overflow-hidden rounded-[var(--radius-card)] border border-line`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={artworkSrc}
            alt={`${task.normalize?.normalized ?? task.query} 的插画`}
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
          <Button
            variant="secondary"
            onClick={() => setPicking((v) => !v)}
            disabled={busy || !task.can?.regenerate}
          >
            不满意，重新画
          </Button>
          <Button variant="ghost" onClick={onReset}>
            换一张图
          </Button>
        </div>

        {picking ? (
          <div className="mt-4 rounded-[var(--radius-card)] border border-line bg-black/[0.02] p-4">
            <p className="text-[13.5px] font-medium text-ink">这次主要想改哪里？</p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
              选一个方向，我这次会重点按它来画（不选也行，那就直接换一版）。
              每次重画会重新消耗 1 次生成额度。
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {options.map((item) => {
                const active = picked === item.key;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setPicked(active ? "" : item.key)}
                    className={
                      "rounded-full border px-3.5 py-1.5 text-[13px] transition-colors " +
                      (active
                        ? "border-[#5865f2] bg-[#5865f2] text-white"
                        : "border-line bg-surface text-ink hover:border-[#5865f2]/50")
                    }
                    aria-pressed={active}
                  >
                    {item.label}
                  </button>
                );
              })}
              {options.length === 0 ? (
                <span className="text-[12.5px] text-faint">正在读取可选项…</span>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="primary"
                className="btn-blurple"
                disabled={busy || !task.can?.regenerate}
                onClick={() => {
                  const chosen = picked;
                  setPicking(false);
                  setPicked("");
                  onRegenerate(chosen || undefined);
                }}
              >
                {picked ? "按这个方向重画" : "直接重画"}
              </Button>
              <Button variant="ghost" onClick={() => setPicking(false)} disabled={busy}>
                取消
              </Button>
            </div>
          </div>
        ) : null}

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
