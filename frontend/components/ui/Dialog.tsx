"use client";

/**
 * 对话框：仅引入 Radix Dialog 一个包（无样式组件库），
 * 由它负责焦点约束、Esc 关闭、ARIA 角色（前端工程约定 17 节）。
 * 视觉完全自建，与项目主题一致。
 */
import * as RadixDialog from "@radix-ui/react-dialog";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;

export function DialogContent({
  children,
  className,
  labelledBy,
  onKeyDown,
}: {
  children: React.ReactNode;
  className?: string;
  labelledBy?: string;
  onKeyDown?: React.KeyboardEventHandler<HTMLDivElement>;
}) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm" />
      <RadixDialog.Content
        aria-labelledby={labelledBy}
        onKeyDown={onKeyDown}
        data-theme="card-paper"
        className={
          className ??
          "fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[calc(100vw-1.5rem)] max-w-[880px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[14px] border border-line bg-[var(--color-surface)] p-5 text-[var(--color-ink)] shadow-2xl sm:p-6"
        }
      >
        {children}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}

/** 右上角关闭按钮（与内容区错开，避免与内容里的按钮重叠） */
export function DialogCloseButton() {
  return (
    <RadixDialog.Close
      className="absolute right-3 top-3 rounded-[var(--radius-btn)] border border-line bg-surface px-3 py-1.5 text-[13px] text-muted hover:text-ink"
      aria-label="关闭"
    >
      关闭
    </RadixDialog.Close>
  );
}

export const DialogTitle = RadixDialog.Title;
export const DialogDescription = RadixDialog.Description;
