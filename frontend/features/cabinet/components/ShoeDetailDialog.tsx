"use client";

/**
 * 鞋款详情（3.2 只做只读查看；编辑 / 删除 / 上一双下一双 / 左右滑 在 3.3 实现）
 * 用 Radix Dialog 保证焦点约束、Esc 关闭与 ARIA（前端手册 17 节）。
 */
import { Dialog, DialogCloseButton, DialogContent, DialogTitle } from "@/components/ui/Dialog";
import type { ArchiveDetail } from "@/lib/api/types";

export function ShoeDetailDialog({
  open,
  detail,
  loading,
  onClose,
}: {
  open: boolean;
  detail: ArchiveDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      {open ? (
        <DialogContent labelledBy="shoe-detail-title">
          <DialogCloseButton />
          {loading || !detail ? (
            <p className="px-1 py-10 text-center text-[14px] text-muted">正在读取这双鞋…</p>
          ) : (
            <>
              <div className="mx-auto w-full max-w-[560px] overflow-hidden rounded-[var(--radius-card)] border border-line bg-white">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={detail.artwork_url}
                  alt={`${detail.model_name} 的黑白线稿`}
                  className="frame-3x2"
                  style={{ objectFit: "contain" }}
                />
              </div>

              <div className="mt-5 space-y-2.5 pr-16">
                <DialogTitle id="shoe-detail-title" className="text-[20px] font-semibold text-ink">
                  {detail.model_name}
                </DialogTitle>
                <p className="text-[13.5px] text-accent">
                  {detail.date_text ? `${detail.date_text}（排序键 ${detail.date_sort_key ?? "无"}）` : "未填时间"}
                </p>
                <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">
                  {detail.story || "（没有写故事）"}
                </p>
                <p className="pt-1 text-[12px] leading-relaxed text-faint">
                  {detail.source?.credit ?? "图源来自公开检索"} · {detail.rights_note}
                </p>
              </div>
            </>
          )}
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
