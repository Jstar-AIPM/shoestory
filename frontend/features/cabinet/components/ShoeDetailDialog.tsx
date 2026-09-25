"use client";

/**
 * 鞋款详情（3.3 完整版）
 *
 * 能力：查看 / 编辑（型号·时间·故事）/ 删除（二次确认）/ 上一双·下一双 / 手机左右滑
 * 说明：
 * · 用 Radix Dialog 保证焦点约束、Esc 关闭与 ARIA；
 * · 翻页信息由后端按当前排序算好（position/total/prev_shoe_id/next_shoe_id），前端不自己分页；
 * · 删除是真实删除（后端需 confirm=true），成功后通知外层刷新鞋柜；
 * · 编辑/删除都以后端返回为准，不做乐观更新。
 */
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogCloseButton, DialogContent, DialogTitle } from "@/components/ui/Dialog";
import { Input, Textarea } from "@/components/ui/Input";
import { deleteArchive, getArchive, patchArchive } from "@/lib/api/archive";
import { ApiError } from "@/lib/api/client";
import type { AppError } from "@/lib/api/errors";
import type { ArchiveDetail } from "@/lib/api/types";
import { track } from "@/lib/analytics";
import { artworkFrameClass } from "@/lib/utils/artwork";

type Mode = "view" | "edit" | "confirm-delete";

/** 下载用的文件名：型号可能带 `/`、`:` 等字符，替换掉避免浏览器乱码或截断 */
function downloadName(modelName: string): string {
  const safe = (modelName || "鞋历").replace(/[\\/:*?"<>|]/g, "-").trim() || "鞋历";
  return `${safe}.png`;
}

export function ShoeDetailDialog({
  shoeId,
  onClose,
  onChanged,
  onNavigate,
}: {
  shoeId: string | null;
  onClose: () => void;
  onChanged: () => void;
  onNavigate: (shoeId: string) => void;
}) {
  const [detail, setDetail] = useState<ArchiveDetail | null>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AppError | null>(null);
  //: 中性提示（不是错误）—— 例如"什么都没改"
  const [notice, setNotice] = useState<string | null>(null);

  const [modelName, setModelName] = useState("");
  const [dateText, setDateText] = useState("");
  const [story, setStory] = useState("");

  const touchStartX = useRef<number | null>(null);
  // 由数据本身推导加载态：无数据且无错误 = 正在读取（外层用 key 保证每双鞋重新挂载）
  const loading = !detail && !error;

  // 拉取详情：订阅 Promise 回调，避免在 effect 里同步 setState（React 规则）
  useEffect(() => {
    if (!shoeId) return;
    let cancelled = false;
    getArchive(shoeId)
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
        setModelName(data.model_name);
        setDateText(data.date_text ?? "");
        setStory(data.story ?? "");
        setMode("view");
        setError(null);
        track("detail_opened", { position: data.position ?? null });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setError(
          cause instanceof ApiError
            ? cause.appError
            : { code: "UNKNOWN", userMessage: "读取这双鞋失败。", retryable: true, status: 0 },
        );
      })
      ;
    return () => {
      cancelled = true;
    };
  }, [shoeId]);

  const go = (target: string | null | undefined) => {
    if (target) onNavigate(target);
  };

  const save = async () => {
    if (!detail) return;
    const next = {
      model_name: modelName.trim(),
      date_text: dateText.trim(),
      story: story.trim(),
    };
    // 什么都没改就不打接口（2026-09-25 产品反馈 3）：
    // 让人点一下保存却收到一个报错是最别扭的体验 —— 这里给一句中性提示就够了。
    const unchanged =
      next.model_name === (detail.model_name ?? "").trim() &&
      next.date_text === (detail.date_text ?? "").trim() &&
      next.story === (detail.story ?? "").trim();
    if (unchanged) {
      setError(null);
      setNotice("内容没有变化，保持原样就好。想改的话直接编辑上面的字段再保存。");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await patchArchive(detail.shoe_id, {
        model_name: modelName.trim(),
        date_text: dateText.trim(),
        story: story.trim(),
      });
      setDetail(updated);
      setMode("view");
      onChanged();
      track("shoe_edited");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.appError
          : { code: "UNKNOWN", userMessage: "保存失败，请重试。", retryable: true, status: 0 },
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      await deleteArchive(detail.shoe_id);
      track("shoe_deleted");
      onChanged();
      onClose();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.appError
          : { code: "UNKNOWN", userMessage: "删除失败，请重试。", retryable: true, status: 0 },
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={Boolean(shoeId)} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      {shoeId ? (
        <DialogContent
          labelledBy="shoe-detail-title"
          onKeyDown={(event: React.KeyboardEvent) => {
            if (mode !== "view") return;
            if (event.key === "ArrowLeft") go(detail?.prev_shoe_id);
            if (event.key === "ArrowRight") go(detail?.next_shoe_id);
          }}
        >
          <DialogCloseButton />

          {/* 翻页与位置：统一放左上，与右上角"关闭"错开 */}
          <div className="flex flex-wrap items-center gap-2 pr-[110px]">
            <Button
              size="sm"
              variant="secondary"
              disabled={!detail?.prev_shoe_id}
              onClick={() => go(detail?.prev_shoe_id)}
            >
              ← 上一双
            </Button>
            <span className="text-[12.5px] text-faint">
              {detail?.total ? `第 ${detail.position} / ${detail.total} 双` : ""}
            </span>
            <Button
              size="sm"
              variant="secondary"
              disabled={!detail?.next_shoe_id}
              onClick={() => go(detail?.next_shoe_id)}
            >
              下一双 →
            </Button>
          </div>

          {error ? (
            <div className="mt-3">
              <Alert tone="danger" title="操作没有成功">{error.userMessage}</Alert>
            </div>
          ) : null}

          {loading || !detail ? (
            <p className="px-1 py-16 text-center text-[14px] text-muted">正在读取这双鞋…</p>
          ) : (
            <>
              {/* 画稿：手机可左右滑切换鞋款（与按钮、键盘三种方式并存） */}
              <div
                className={`${artworkFrameClass(detail.style_id)} mx-auto mt-3 w-full max-w-[560px] overflow-hidden rounded-[var(--radius-card)] border border-line`}
                onTouchStart={(event) => {
                  touchStartX.current = event.touches[0]?.clientX ?? null;
                }}
                onTouchEnd={(event) => {
                  const start = touchStartX.current;
                  touchStartX.current = null;
                  if (start == null) return;
                  const delta = (event.changedTouches[0]?.clientX ?? start) - start;
                  if (Math.abs(delta) < 60) return;
                  go(delta < 0 ? detail.next_shoe_id : detail.prev_shoe_id);
                }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={detail.artwork_url}
                  alt={`${detail.model_name} 的插画`}
                  className="frame-3x2"
                  style={{ objectFit: "contain" }}
                />
              </div>

              {mode === "view" ? (
                <>
                  <div className="mt-5 space-y-2.5 pr-16">
                    <DialogTitle id="shoe-detail-title" className="text-[20px] font-semibold text-ink">
                      {detail.model_name}
                    </DialogTitle>
                    {/* 2026-09-25 产品反馈 4：不再显示「风格 xxx v1」「质检 0.9535」这类内部标签 ——
                        它们是给排查用的，对"这是不是我那双鞋"这件事没有帮助，反而像在自证。
                        质检分仍然照常记录在档案里（详情接口里能拿到）。 */}
                    <p className="text-[13.5px] text-accent">
                      {detail.date_text || "未填时间"}
                    </p>
                    <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">
                      {detail.story || "（没有写故事）"}
                    </p>
                    <p className="pt-1 text-[12px] leading-relaxed text-faint">
                      {detail.source?.credit ?? "图源来自公开检索"} · {detail.rights_note}
                    </p>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {/* 下载画稿（产品反馈 5）：同源地址 + download 属性即可，
                        不需要后端额外开接口（画稿本来就是这个地址给的）。 */}
                    <a
                      href={detail.artwork_url}
                      download={downloadName(detail.model_name)}
                      className="inline-flex h-11 items-center justify-center rounded-[var(--radius-btn)] border border-line bg-surface px-5 text-[14px] font-medium text-ink transition-colors hover:border-ink/30"
                    >
                      下载画稿
                    </a>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setNotice(null);
                        setError(null);
                        setMode("edit");
                      }}
                    >
                      编辑信息
                    </Button>
                    <Button variant="danger" onClick={() => setMode("confirm-delete")}>
                      删除这双
                    </Button>
                  </div>
                </>
              ) : null}

              {mode === "edit" ? (
                <div className="mt-5 space-y-4">
                  <div>
                    <label htmlFor="edit-model" className="text-[13px] font-medium text-muted">型号</label>
                    <Input
                      id="edit-model"
                      value={modelName}
                      maxLength={80}
                      onChange={(event) => {
                        setModelName(event.target.value);
                        setNotice(null);
                      }}
                      className="mt-1.5"
                    />
                  </div>
                  <div>
                    <label htmlFor="edit-date" className="text-[13px] font-medium text-muted">时间</label>
                    <Input
                      id="edit-date"
                      value={dateText}
                      maxLength={40}
                      onChange={(event) => {
                        setDateText(event.target.value);
                        setNotice(null);
                      }}
                      className="mt-1.5"
                    />
                  </div>
                  <div>
                    <label htmlFor="edit-story" className="text-[13px] font-medium text-muted">故事</label>
                    <Textarea
                      id="edit-story"
                      rows={4}
                      maxLength={2000}
                      value={story}
                      onChange={(event) => {
                        setStory(event.target.value);
                        setNotice(null);
                      }}
                      className="mt-1.5"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="primary" className="btn-blurple" onClick={() => void save()} disabled={busy}>
                      {busy ? "保存中…" : "保存"}
                    </Button>
                    <Button variant="ghost" onClick={() => setMode("view")} disabled={busy}>
                      取消
                    </Button>
                  </div>
                  {notice ? (
                    <p className="text-[13px] leading-relaxed text-muted" role="status">
                      {notice}
                    </p>
                  ) : null}
                </div>
              ) : null}

              {mode === "confirm-delete" ? (
                <div className="mt-5">
                  <Alert tone="danger" title={`确定删除「${detail.model_name}」吗？`}>
                    画稿文件会一并删除，这个操作不可撤销。
                  </Alert>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button variant="danger" onClick={() => void remove()} disabled={busy}>
                      {busy ? "删除中…" : "确认删除"}
                    </Button>
                    <Button variant="ghost" onClick={() => setMode("view")} disabled={busy}>
                      取消
                    </Button>
                  </div>
                  {notice ? (
                    <p className="text-[13px] leading-relaxed text-muted" role="status">
                      {notice}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          )}
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
