"use client";

/**
 * 标准角度示例（产品反馈 8）
 *
 * 放在上传区右侧，高度与左边的虚线框一致。目的：**先给人看"什么样的图能出好效果"**。
 * 一句"白底、正侧面"的文字说明，远不如两张图直观 —— 用户看一眼就知道该找哪张照片。
 *
 * 两张示例图（`public/examples/`）在入库前做过统一处理：**同为 1200×800（3:2）、
 * 鞋宽都占画布 84%、鞋底对齐在同一条基线** —— 所以并排看起来一样大、一样齐。
 * 换图时请保持这三条（脚本做法：取主体外接框 → 按宽度等比缩放 → 居中、底边对齐）。
 */
import { cn } from "@/lib/utils/cn";

/** 示例图配置：src 为空时渲染占位块 */
const EXAMPLES: { src: string; caption: string }[] = [
  { src: "/examples/example-1.png", caption: "示例一 · 正侧面" },
  { src: "/examples/example-2.png", caption: "示例二 · 正侧面" },
];

export function UploadExamples({ className }: { className?: string }) {
  return (
    <aside
      className={cn(
        "rounded-[var(--radius-card)] border border-line bg-black/[0.02] p-3",
        className,
      )}
      aria-label="推荐的上传角度示例"
    >
      <p className="text-[12.5px] font-medium text-ink">
        上传如下角度的图片，效果更好
      </p>
      {/* JSX 不渲染 Markdown —— 这里要用 <strong>，写成 ** 会原样显示出来（自测发现过） */}
      <p className="mt-1 text-[12px] leading-relaxed text-muted">
        单只鞋、干净的背景、<strong className="font-medium text-ink">鞋头朝左的正侧面</strong>
        ，整只鞋都在画面里。
      </p>

      <div className="mt-2.5 grid grid-cols-2 gap-2.5">
        {EXAMPLES.map((item) => (
          <figure key={item.caption} className="min-w-0">
            <div className="frame-3x2 overflow-hidden rounded-[var(--radius-btn)] border border-dashed border-line bg-white">
              {item.src ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={item.src} alt={item.caption} className="h-full w-full object-contain" />
              ) : (
                <span className="flex h-full w-full items-center justify-center text-[11.5px] text-faint">
                  示例图待放
                </span>
              )}
            </div>
            <figcaption className="mt-1 text-[11.5px] text-faint">{item.caption}</figcaption>
          </figure>
        ))}
      </div>
    </aside>
  );
}
