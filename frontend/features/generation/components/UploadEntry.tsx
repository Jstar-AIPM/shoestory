"use client";

/**
 * 上传入口（V2 输入方式）：拖拽 / ⌘V 粘贴 / 相册，三种方式都归到同一个 onFiles。
 * 引导文案来自实测结论：商品详情页的白底、正侧面、单只鞋最好（列表页/合影会被拒）。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export function UploadEntry({
  onFiles,
  disabled,
}: {
  onFiles: (files: FileList | File[] | null) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const openPicker = useCallback(() => {
    if (disabled) return;
    inputRef.current?.click();
  }, [disabled]);

  // 全局 ⌘V / Ctrl+V 粘贴：不用让用户先点进某个输入框
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (disabled) return;
      const items = event.clipboardData?.items;
      if (!items) return;
      const files: File[] = [];
      for (const item of Array.from(items)) {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
      if (files.length > 0) {
        event.preventDefault();
        onFiles(files);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [disabled, onFiles]);

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          onFiles(event.target.files);
          event.target.value = ""; // 允许重复选同一张
        }}
      />
      <button
        type="button"
        onClick={openPicker}
        disabled={disabled}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!disabled) onFiles(event.dataTransfer.files);
        }}
        aria-label="上传球鞋图片"
        // h-full + flex-col：让这个框撑满容器高度（与右侧示例区齐平），
        // 文案在上半区垂直居中，主按钮压在下边 —— 2026-09-25 反馈 2 的排版要求。
        className={`group flex h-full w-full flex-col justify-between gap-4 rounded-[var(--radius-card)] border-2 border-dashed px-5 py-5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          dragging
            ? "border-[#5865f2] bg-[#5865f2]/15"
            : "border-[#5865f2]/45 bg-black/10 hover:border-[#5865f2] hover:bg-[#5865f2]/10"
        }`}
      >
        {/* 上半区：文案（在这一块里垂直居中） */}
        <span className="flex min-w-0 flex-1 flex-col justify-center">
          <span className="block text-[14px] font-semibold text-ink">上传一张球鞋图，或拖进来</span>
          <span className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12.5px] text-muted">
            <span>也可以直接粘贴：</span>
            <kbd className="rounded border border-white/25 bg-white px-1.5 py-0.5 font-mono text-[11.5px] font-semibold text-[#111111]">
              ⌘V
            </kbd>
            <span className="text-faint">（Windows 用 Ctrl+V）</span>
          </span>
          {/* 措辞不写"白底"：两张示例图都是纯白底，说"干净的背景"更准也更少废话（反馈 6） */}
          <span className="mt-1.5 block text-[12.5px] leading-relaxed text-faint">
            最好用商品详情页的图：干净的背景、正侧面、只有一双鞋。
          </span>
        </span>
        {/* 主按钮压在下边（整块区域都可点/可拖，这里只是视觉主体） */}
        <span className="btn-blurple pointer-events-none inline-flex h-12 w-full shrink-0 items-center justify-center gap-2 rounded-full px-6 text-[15px] font-semibold text-white shadow-[0_6px_18px_rgba(88,101,242,0.35)]">
          <span aria-hidden className="text-[17px] leading-none">＋</span>
          选择照片
        </span>
      </button>
    </div>
  );
}
