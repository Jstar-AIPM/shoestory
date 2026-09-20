"use client";

/**
 * 「我的鞋柜」首页 —— 入口即产品（阶段 3 · 3.2 第一条真实闭环）
 *
 * 视觉方向：方案 C「黑夜画廊 × 纸白阅读」
 *   · 作品与图片挂在深色墙上；文字、确认与表单放在纸白卡里
 *   规则：展示用深色烘托，阅读与操作用纸白护眼（详见 docs/前端内部工程笔记.md 3.1）
 *
 * 本页承载的闭环（真实接口）：
 *   型号输入 → 校对 → 源图确认（三种形态）→ 生成进度 → 效果确认 → 时间/故事 → 归档 → 网格回显
 *   另含：刷新/离开后按 ?task= 恢复真实状态、轮询退避、页面不可见暂停、防重复提交。
 */
import { useEffect, useRef, useState } from "react";

import { PageShell } from "@/components/layout/PageShell";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { Dialog, DialogCloseButton, DialogContent, DialogTitle } from "@/components/ui/Dialog";
import { StatusChip } from "@/components/ui/StatusChip";
import { useCabinet } from "@/features/cabinet/hooks/useCabinet";
import { ShoeDetailDialog } from "@/features/cabinet/components/ShoeDetailDialog";
import { CabinetGrid } from "@/features/cabinet/components/CabinetGrid";
import { ArchiveForm } from "@/features/generation/components/ArchiveForm";
import { EffectConfirm } from "@/features/generation/components/EffectConfirm";
import { GenerationProgress } from "@/features/generation/components/GenerationProgress";
import { ModelInput } from "@/features/generation/components/ModelInput";
import { ResolveFeedback } from "@/features/generation/components/ResolveFeedback";
import { SourceConfirm } from "@/features/generation/components/SourceConfirm";
import { useTaskFlow } from "@/features/generation/hooks/useTaskFlow";
import { getHealth } from "@/lib/api/system";
import { track } from "@/lib/analytics";
import type { HealthResponse } from "@/lib/api/types";
import { toUiState } from "@/lib/state/taskState";

export default function CabinetPage() {
  const cabinet = useCabinet();
  const flow = useTaskFlow(() => void cabinet.reload());

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  /** 详情弹窗：只保存"当前打开的 shoe_id"，详情数据由弹窗自己按需拉取 */
  const [detailShoeId, setDetailShoeId] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    if (cabinet.state === "ready" || cabinet.state === "empty") {
      track("cabinet_loaded", { count: cabinet.items.length, state: cabinet.state });
    }
  }, [cabinet.state, cabinet.items.length]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  const task = flow.task;
  const ui = toUiState(task?.state);

  // 生成结果埋点：同一任务只记一次（避免轮询重复上报）
  const trackedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!task) return;
    if (task.state === "awaiting_effect_confirm" && trackedRef.current !== task.task_id) {
      trackedRef.current = task.task_id;
      track("generated", { attempts: task.quality?.attempts ?? 1, score: task.quality?.score ?? null });
    }
    if (task.state === "failed" && trackedRef.current !== `${task.task_id}:failed`) {
      trackedRef.current = `${task.task_id}:failed`;
      track("generation_failed", { code: task.error?.code ?? "UNKNOWN" });
    }
  }, [task]);
  const mode = health?.providers.mode ?? (health ? "real" : "unknown");
  const mockMode = health?.flags.mock_mode ?? false;

  return (
    <div data-theme="wall">
      {/* 顶栏 + Hero：同一层渐变，避免接缝 */}
      <div className="wall-gradient w-full">
        <PageShell className="!py-3.5">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-baseline gap-3">
              <span className="text-[22px] font-extrabold tracking-wide text-white">履历</span>
              <span className="hidden text-[12.5px] text-muted sm:inline">履（鞋）＋ 历（经历）</span>
            </div>
            {mockMode ? (
              <StatusChip tone="warn">演示模式（mock 上游）</StatusChip>
            ) : mode === "real" ? (
              <StatusChip tone="success">真实模型</StatusChip>
            ) : (
              <StatusChip tone="danger">后端未连接</StatusChip>
            )}
          </div>
        </PageShell>

        <PageShell className="!pt-10 !pb-14 sm:!pt-14 sm:!pb-20">
          <p className="display-upper text-[13px] text-accent">MY SHOE CABINET</p>
          <h1 className="display-upper mt-3 max-w-[560px] text-[34px] text-white sm:text-[46px]">
            一双鞋，
            <br />
            就是履历上的一行
          </h1>
          <p className="mt-5 max-w-[520px] text-[15px] leading-relaxed text-muted">
            输入鞋款型号，它会变成一张黑白线稿，收进你的鞋柜。线下穿旧的鞋，在这里留下痕迹。
          </p>
          <div className="mt-9 max-w-[640px]">
            <ModelInput
              submitting={flow.submitting}
              disabled={ui === "running" || ui === "waiting_user"}
              onSubmit={(query) => {
                track("generation_submitted", { query_len: query.length });
                void flow.submit(query);
              }}
            />
          </div>
          {flow.restoring ? (
            <p className="mt-3 text-[12.5px] text-faint">正在恢复上次的任务…</p>
          ) : null}
        </PageShell>
      </div>

      {/* 画廊墙：作品与流程 */}
      <main className="w-full bg-[#0a0b1e]">
        <PageShell className="!py-12">
          {flow.error ? (
            <div className="mb-6">
              <Card className="px-5 py-4">
                <Alert tone="danger" title="出错了">
                  {flow.error.userMessage}
                  {flow.error.retryable ? " 稍后可以重试。" : ""}
                  {flow.error.code ? <span className="ml-2 font-mono text-[11.5px] text-faint">({flow.error.code})</span> : null}
                </Alert>
              </Card>
            </div>
          ) : null}

          {/* ① 生成流程（按后端真实状态渲染） */}
          {task ? (
            <div className="mb-12 space-y-5">
              {ui === "waiting_user" && task.state === "awaiting_source_confirm" ? (
                <SourceConfirm
                  task={task}
                  busy={flow.busy}
                  onChoose={(payload) => {
                    track("source_confirmed", { mode: task.source_mode, model_only: Boolean(payload.use_model_only) });
                    void flow.choose(payload);
                  }}
                  onReset={flow.reset}
                />
              ) : null}

              {ui === "waiting_user" && (task.state === "model_not_found" || task.state === "resolve_failed") ? (
                <ResolveFeedback
                  task={task}
                  onPickCandidate={(name) => void flow.submit(name)}
                  onReset={flow.reset}
                />
              ) : null}

              {task.state === "resolve_failed" && !task.source_candidates.length ? (
                <SourceConfirm
                  task={task}
                  busy={flow.busy}
                  onChoose={(payload) => void flow.choose(payload)}
                  onReset={flow.reset}
                />
              ) : null}

              {ui === "running" || ui === "disconnected" ? <GenerationProgress task={task} /> : null}

              {task.state === "awaiting_effect_confirm" ? (
                <EffectConfirm
                  task={task}
                  busy={flow.busy}
                  onArchive={() => setArchiving(true)}
                  onRegenerate={() => {
                    track("regenerated");
                    void flow.regenerate("用户点重新生成");
                  }}
                  onReset={() => void flow.cancel()}
                />
              ) : null}

              {archiving && task.state === "awaiting_effect_confirm" ? (
                <ArchiveForm
                  modelName={task.normalize?.normalized ?? task.query}
                  busy={flow.busy}
                  onSubmit={async (payload) => {
                    const result = await flow.archive(payload);
                    setArchiving(false);
                    if (result) {
                      track("archived", { has_date: Boolean(payload.date_text), has_story: Boolean(payload.story) });
                      setToast("已归档进鞋柜");
                    }
                  }}
                  onSkip={async () => {
                    const result = await flow.archive({});
                    setArchiving(false);
                    if (result) {
                      track("archived", { has_date: false, has_story: false, skipped: true });
                      setToast("已归档进鞋柜");
                    }
                  }}
                />
              ) : null}

              {task.state === "interrupted" || task.state === "failed" ? (
                <Card className="px-5 py-5 sm:px-6">
                  <h2 className="text-[17px] font-semibold text-ink">
                    {task.state === "interrupted" ? "任务已暂停" : "这次没有画出可交付的线稿"}
                  </h2>
                  <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
                    {task.error?.message ?? "可以换一张参考图，或重新输入型号再试一次。"}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      onClick={() => void flow.regenerate("从暂停/失败状态继续")}
                      disabled={flow.busy}
                      className="btn-snow h-11 rounded-full border px-6 text-[14px] font-semibold disabled:opacity-50"
                    >
                      继续 / 重新生成
                    </button>
                    <button
                      onClick={flow.reset}
                      className="h-11 rounded-full border border-line px-6 text-[14px] text-muted hover:text-ink"
                    >
                      重新输入
                    </button>
                  </div>
                </Card>
              ) : null}
            </div>
          ) : null}

          {/* ② 鞋柜网格（同一事实来源：后端） */}
          <CabinetGrid
            state={cabinet.state}
            items={cabinet.items.map((item) => ({
              shoeId: item.shoe_id,
              modelName: item.model_name,
              artworkUrl: item.artwork_url,
              dateText: item.date_text,
            }))}
            onOpen={(shoeId) => setDetailShoeId(shoeId)}
            onRetry={() => void cabinet.retry()}
          />

          {cabinet.warning ? (
            <div className="mt-6">
              <Card className="px-5 py-4">
                <Alert tone="warn" title="存储提示">{cabinet.warning}</Alert>
              </Card>
            </div>
          ) : null}

          <footer className="mt-16 border-t border-line pt-6 text-[12.5px] leading-relaxed text-faint">
            <p>个人纪念性再创作，商标归原品牌所有；图源来自公开检索。</p>
            <p className="mt-1">你的鞋柜只保存在你自己的服务端文件里，默认不外传、不用于训练。</p>
          </footer>
        </PageShell>
      </main>

      <ShoeDetailDialog
        key={detailShoeId ?? "none"}
        shoeId={detailShoeId}
        onClose={() => setDetailShoeId(null)}
        onChanged={() => void cabinet.reload()}
        onNavigate={(nextId) => setDetailShoeId(nextId)}
      />

      {/* 归档成功提示（不阻塞主流程） */}
      {toast ? (
        <Dialog open>
          <DialogContent className="fixed bottom-6 left-1/2 z-50 w-auto max-w-[92vw] -translate-x-1/2 rounded-full border border-line bg-[var(--color-surface)] px-5 py-3 text-[14px] text-[var(--color-ink)] shadow-2xl">
            <DialogTitle className="sr-only">提示</DialogTitle>
            <span>{toast}</span>
            <DialogCloseButton />
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}
