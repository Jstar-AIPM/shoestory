"use client";

/**
 * 「鞋历」首页 —— 入口即产品
 *
 * 视觉方向：方案 C「黑夜画廊 × 纸白阅读」
 *   · 作品与图片挂在深色墙上；文字、确认与表单放在纸白卡里
 *   规则：展示用深色烘托，阅读与操作用纸白护眼（详见 docs/前端内部工程笔记.md 3.1）
 *
 * 本页承载的闭环（真实接口）：
 *   上传图 → 裁切确认 → 体检 → 生成（CV 草稿动效）→ 效果确认 → 时间/故事 → 归档 → 网格回显
 *   型号输入作为「老方式」保留在折叠区；另含刷新/离开按 ?task= 恢复、轮询退避、防重复提交。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { PageShell } from "@/components/layout/PageShell";
import { TopBar, type QuotaInfo } from "@/components/layout/TopBar";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/Dialog";
import { LoginScreen } from "@/features/auth/components/LoginScreen";
import { useCabinet } from "@/features/cabinet/hooks/useCabinet";
import { ShoeDetailDialog } from "@/features/cabinet/components/ShoeDetailDialog";
import { CabinetGrid } from "@/features/cabinet/components/CabinetGrid";
import { ArchiveForm } from "@/features/generation/components/ArchiveForm";
import { CropConfirm } from "@/features/generation/components/CropConfirm";
import { EffectConfirm } from "@/features/generation/components/EffectConfirm";
import { GenerationProgress } from "@/features/generation/components/GenerationProgress";
import { InspectOutcome } from "@/features/generation/components/InspectOutcome";
import { ModelInput } from "@/features/generation/components/ModelInput";
import { ResolveFeedback } from "@/features/generation/components/ResolveFeedback";
import { SourceConfirm } from "@/features/generation/components/SourceConfirm";
import { UploadEntry } from "@/features/generation/components/UploadEntry";
import { useTaskFlow } from "@/features/generation/hooks/useTaskFlow";
import { useUploadFlow } from "@/features/generation/hooks/useUploadFlow";
import { logout as logoutApi, me as fetchMe } from "@/lib/api/auth";
import { getHealth } from "@/lib/api/system";
import { track } from "@/lib/analytics";
import type { HealthResponse, MeOut } from "@/lib/api/types";
import { toUiState } from "@/lib/state/taskState";

export default function CabinetPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [identity, setIdentity] = useState<MeOut | null>(null);
  const [identityChecked, setIdentityChecked] = useState(false);

  // 是否需要登录：据此决定"要不要拉数据"（未登录时绝不发数据请求，避免 401 污染界面）
  const needLogin = Boolean(identity?.auth_required && !identity?.authenticated);
  const dataEnabled = identityChecked && !needLogin;

  const cabinet = useCabinet({ enabled: dataEnabled });
  const flow = useTaskFlow(() => void cabinet.reload(), { enabled: dataEnabled });
  const upload = useUploadFlow(async (payload) => {
    const task = await flow.submitUpload(payload);
    if (task) track("generation_submitted", { mode: "upload" });
    return task;
  });
  const [archiving, setArchiving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  /** 详情弹窗：只保存"当前打开的 shoe_id"，详情数据由弹窗自己按需拉取 */
  const [detailShoeId, setDetailShoeId] = useState<string | null>(null);

  const loadIdentity = useCallback(async () => {
    try {
      setIdentity(await fetchMe());
    } catch {
      setIdentity(null);
    } finally {
      setIdentityChecked(true);
    }
  }, []);

  // 初始鉴权：订阅 Promise 回调（effect 只做"订阅"这件事）
  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((data) => {
        if (!cancelled) setIdentity(data);
      })
      .catch(() => {
        if (!cancelled) setIdentity(null);
      })
      .finally(() => {
        if (!cancelled) setIdentityChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      await logoutApi();
    } catch {
      /* 退出请求失败也让前端回到登录页（服务端 cookie 无论如何会过期） */
    }
    setIdentity(null);
    await loadIdentity();
  }, [loadIdentity]);

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

  const canGenerate = identity?.can_generate ?? true;
  const quota: QuotaInfo | null = identity
    ? {
        authRequired: identity.auth_required,
        role: identity.role,
        remaining: identity.remaining,
        canGenerate,
      }
    : null;

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

  if (!identityChecked) {
    return (
      <div data-theme="wall" className="wall-gradient flex min-h-screen items-center justify-center">
        <p className="text-[14px] text-muted">正在检查访问权限…</p>
      </div>
    );
  }

  if (needLogin) {
    return <LoginScreen onSuccess={() => void loadIdentity()} />;
  }

  return (
    <div data-theme="wall">
      {/* 顶栏 + Hero：同一层渐变，避免接缝 */}
      <div className="wall-gradient w-full">
        <TopBar
          mode={mockMode ? "mock" : mode === "real" ? "real" : "offline"}
          quota={quota}
          onLogout={handleLogout}
        />

        {/* 首屏要在一屏内露出「上传入口 + 我的鞋柜标题」：Hero 收紧（标题变小、间距变紧、文案压到两行） */}
        <PageShell className="!pt-6 !pb-8 sm:!pt-8 sm:!pb-10">
          <p className="display-upper text-[12.5px] text-accent">MY SHOE CABINET</p>
          <h1 className="display-upper mt-2 text-[30px] text-white sm:text-[34px]">鞋历</h1>
          {/* slogan 已在顶栏出现一次，这里不再重复（2026-09-23 反馈） */}
          <p className="mt-2 max-w-[560px] text-[13.5px] leading-relaxed text-muted">
            上传一张您那双鞋的照片，它会变成一张黑白线稿，收进您的鞋柜。
          </p>
          {!canGenerate ? (
            <div className="mt-6 max-w-[640px] rounded-[var(--radius-btn)] border border-warn/30 bg-warn/[0.08] px-4 py-3 text-[13px] leading-relaxed text-ink">
              {identity?.message ?? "邀请码的生成次数已用完。"}
              已归档的鞋柜仍可正常查看、编辑与删除。
            </div>
          ) : null}
          <div className="mt-6 max-w-[640px]">
            {upload.phase === "empty" ? (
              <>
                <UploadEntry
                  disabled={ui === "running" || ui === "waiting_user" || !canGenerate}
                  onFiles={(files) => upload.acceptFiles(files)}
                />
                <details className="mt-3">
                  <summary className="cursor-pointer select-none text-[12.5px] text-faint transition-colors hover:text-muted">
                    没有清晰图？按型号生成（老方式）
                  </summary>
                  <div className="mt-3">
                    <ModelInput
                      submitting={flow.submitting}
                      disabled={ui === "running" || ui === "waiting_user" || !canGenerate}
                      onSubmit={(query) => {
                        track("generation_submitted", { query_len: query.length });
                        void flow.submit(query);
                      }}
                    />
                  </div>
                </details>
              </>
            ) : null}
          </div>
          {flow.restoring ? (
            <p className="mt-3 text-[12.5px] text-faint">正在恢复上次的进度…</p>
          ) : null}
        </PageShell>
      </div>

      {/* 画廊墙：作品与流程 */}
      <main className="w-full bg-[#0a0b1e]">
        <PageShell className="!py-8">
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

          {/* ① 上传体检流程（任务创建前） */}
          {upload.phase !== "empty" ? (
            <div className="mb-12 space-y-5">
              {upload.error ? (
                <Card className="px-5 py-4">
                  <Alert tone="danger" title="出错了">{upload.error.userMessage}</Alert>
                </Card>
              ) : null}
              {upload.phase === "cropping" && upload.image && upload.crop ? (
                <CropConfirm
                  imageUrl={upload.image.dataUrl}
                  imageWidth={upload.image.width}
                  imageHeight={upload.image.height}
                  crop={upload.crop}
                  onCropChange={upload.setCrop}
                  onConfirm={() => void upload.confirmCrop()}
                  onReset={upload.reset}
                  busy={upload.busy}
                  guide={upload.guide}
                />
              ) : null}
              {(upload.phase === "rejected" || upload.phase === "confirm") && upload.inspect ? (
                <InspectOutcome
                  inspect={upload.inspect}
                  busy={upload.busy}
                  onStart={() => void upload.start()}
                  onReCrop={upload.reCrop}
                  onReset={upload.reset}
                />
              ) : null}
            </div>
          ) : null}

          {/* ② 生成流程（按后端真实状态渲染） */}
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

              {archiving && task.artworks.length > 0 ? (
                <Dialog open onOpenChange={(open) => (open ? setArchiving(true) : setArchiving(false))}>
                  <DialogContent className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[calc(100vw-1.5rem)] max-w-[560px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[14px] border border-line bg-[var(--color-surface)] p-5 text-[var(--color-ink)] shadow-2xl sm:p-6">
                    <DialogTitle className="sr-only">归档进鞋柜</DialogTitle>
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
                      onCancel={() => setArchiving(false)}
                    />
                  </DialogContent>
                </Dialog>
              ) : null}

              {task.state === "interrupted" || task.state === "failed" ? (
                <Card className="px-5 py-5 sm:px-6">
                  <h2 className="text-[17px] font-semibold text-ink">
                    {task.state === "interrupted" ? "任务已暂停" : "这次没画好"}
                  </h2>
                  <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
                    {task.error?.message ?? "可以重新生成一次，或换一张更清晰的正侧面图再试。"}
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

          <footer className="mt-12 border-t border-line pt-6 text-[12.5px] leading-relaxed text-faint">
            {/* 品牌 slogan 只在顶栏出现一次（同一屏重复没有必要） */}
            <p className="mt-1">个人纪念性再创作，商标归原品牌所有；图源来自公开检索。</p>
            <p className="mt-1">您的鞋柜只保存在您自己的服务端文件里，默认不外传、不用于训练。</p>
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

      {/* 归档成功提示：非模态轻提示，不挡操作、也没有会和文字重叠的关闭按钮 */}
      {toast ? (
        <div
          role="status"
          aria-live="polite"
          data-theme="card-paper"
          className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-full border border-line bg-[var(--color-surface)] px-5 py-3 text-[14px] text-[var(--color-ink)] shadow-2xl"
        >
          <span className="text-[#2f7d4f]" aria-hidden>
            ✓
          </span>
          <span>{toast}</span>
        </div>
      ) : null}
    </div>
  );
}
