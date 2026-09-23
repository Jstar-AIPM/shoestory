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
        className={`block w-full rounded-[var(--radius-card)] border-2 border-dashed px-6 py-10 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          dragging
            ? "border-[#5865f2] bg-[#5865f2]/10"
            : "border-line bg-black/10 hover:border-[#5865f2]/60"
        }`}
      >
        <span className="block text-[15px] font-semibold text-ink">上传一张球鞋图</span>
        <span className="mt-2 block text-[13px] leading-relaxed text-muted">
          拖进来、点这里选相册，或直接 <kbd className="rounded border border-line bg-white/80 px-1.5 py-0.5 font-mono text-[11px]">⌘V</kbd> 粘贴
        </span>
        <span className="mt-3 block text-[12.5px] leading-relaxed text-faint">
          最好用商品详情页的图：白底、正侧面、只有一双鞋。列表页或多只鞋会被提示重新框选。
        </span>
      </button>
    </div>
  );
}
