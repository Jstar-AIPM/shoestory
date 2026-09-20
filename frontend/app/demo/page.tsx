"use client";

/**
 * 风格对比页：设计参考(Discord) 融合的两个方向
 *   方向 B：全深色画廊（Dark Gallery）
 *   方向 C：深色墙 + 白卡（展示深色 / 阅读纸白）
 *
 * 来源：用户指定的 设计参考 风格页（Discord 设计系统）。
 * 融合原则：取它的深色底 / 强对比 / 胶囊圆角 / 状态三色，
 *          保留我们产品的核心 —— 画稿永远是页面最大元素。
 *
 * 页内右上角开关可实时切换 B / C，便于一眼对比（不改动白纸版首页 `/`）。
 */
import { useState } from "react";

import { CabinetGrid, type GridState } from "@/features/cabinet/components/CabinetGrid";
import type { ShoeCardItem } from "@/features/cabinet/components/ShoeCard";
import { cn } from "@/lib/utils/cn";

const IS_DEV = process.env.NODE_ENV !== "production";

const ITEMS: ShoeCardItem[] = [
  { shoeId: "p1", modelName: "ASICS GEL-NIMBUS 27", artworkUrl: "/preview/sample-1.jpg", dateText: "2026-09-20" },
  { shoeId: "p2", modelName: "Nike KD 12", artworkUrl: "/preview/sample-2.jpg", dateText: "2021年6月" },
  { shoeId: "p3", modelName: "Air Jordan 14", artworkUrl: "/preview/sample-3.jpg", dateText: "2019" },
  { shoeId: "p4", modelName: "adidas Ultraboost Light", artworkUrl: "/preview/sample-4.jpg", dateText: null },
  { shoeId: "p5", modelName: "New Balance 990v6", artworkUrl: "/preview/sample-5.jpg", dateText: "高三那年" },
];

export default function GalleryDemoPage() {
  const [variant, setVariant] = useState<"gallery" | "hybrid">("hybrid");
  const [preview, setPreview] = useState<GridState | "populated">("populated");
  const gridState: GridState = !IS_DEV ? "empty" : preview === "populated" ? "ready" : preview;
  const items = IS_DEV && preview === "populated" ? ITEMS : [];

  return (
    <div data-theme="gallery">
      {/* 顶部：Discord 式深色渐变带 */}
      <header
        className="w-full"
        style={{ background: "linear-gradient(135deg,#0e0f2d 0%,#1a1d5e 50%,#0a0b1e 100%)" }}
      >
        <div className="mx-auto flex w-full max-w-[1200px] items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div className="flex items-baseline gap-3">
            <span className="display-strong text-[22px] text-white">履历</span>
            <span className="hidden text-[12.5px] text-[#babcd9] sm:inline">
              履（鞋）＋ 历（经历）
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-full border border-[#2f336e] bg-[#0e0f2d]/70 p-1 text-[12.5px]">
              <button
                onClick={() => setVariant("gallery")}
                className={cn("rounded-full px-3 py-1", variant === "gallery" ? "bg-[#5865f2] text-white" : "text-[#babcd9] hover:text-white")}
              >
                B 全深色
              </button>
              <button
                onClick={() => setVariant("hybrid")}
                className={cn("rounded-full px-3 py-1", variant === "hybrid" ? "bg-[#5865f2] text-white" : "text-[#babcd9] hover:text-white")}
              >
                C 深色墙+白卡
              </button>
            </div>
            <span className="hidden rounded-full border border-[#57f287]/30 bg-[#57f287]/10 px-3 py-1 text-[12px] text-[#57f287] sm:inline">
              真实模型
            </span>
          </div>
        </div>
      </header>

      {/* Hero：全大写展示标题（Discord 的招牌）+ 我们的产品语言 */}
      <section
        className="w-full"
        style={{ background: "linear-gradient(135deg,#0e0f2d 0%,#1a1d5e 50%,#0a0b1e 100%)" }}
      >
        <div className="mx-auto w-full max-w-[1200px] px-5 pt-12 pb-16 sm:px-8 sm:pt-16 sm:pb-20">
          <p className="display-upper text-[13px] text-[#a5adff]">MY SHOE CABINET</p>
          <h1 className="display-upper mt-3 max-w-[560px] text-[34px] text-white sm:text-[46px]">
            一双鞋，<br />就是履历上的一行
          </h1>
          <p className="mt-5 max-w-[520px] text-[15px] leading-relaxed text-[#babcd9]">
            输入鞋款型号，它会变成一张黑白线稿，收进你的鞋柜。线下穿旧的鞋，在这里留下痕迹。
          </p>

          {/* 输入区：胶囊输入 + 白雪主按钮（Discord 经典） */}
          <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              placeholder="例如 kd12 / asics gel nimbus 27"
              maxLength={60}
              aria-label="鞋款型号"
              className="h-12 w-full rounded-full border border-[#2f336e] bg-[#0e0f2d]/60 px-5 text-[15px] text-white placeholder:text-[#8b8fc7] focus:border-[#5865f2] focus:outline-none sm:max-w-[420px]"
            />
            <button className="btn-snow h-12 shrink-0 rounded-full border px-7 text-[15px] font-semibold transition-colors">
              生成线稿
            </button>
          </div>
          <p className="mt-3 text-[12.5px] text-[#8b8fc7]">
            一次生成约 30 秒、消耗 1 次生成额度；生成中可以离开，回来接着看。
          </p>
        </div>
      </section>

      {/* 主体：装裱在深色墙上的画 */}
      <main className="mx-auto w-full max-w-[1200px] px-5 py-12 sm:px-8">
        {/* 质检/状态徽标演示（Discord 三色） */}
        <div className="mb-8 flex flex-wrap items-center gap-2.5">
          {[
            { label: "质检通过 0.87", cls: "border-[#57f287]/30 bg-[#57f287]/10 text-[#57f287]" },
            { label: "生成中 12s", cls: "border-[#a5adff]/30 bg-[#5865f2]/15 text-[#a5adff]" },
            { label: "Logo 不够清晰", cls: "border-[#faa220]/30 bg-[#faa220]/10 text-[#faa220]" },
            { label: "两次质检未通过", cls: "border-[#de2761]/30 bg-[#de2761]/10 text-[#de2761]" },
          ].map((chip) => (
            <span key={chip.label} className={cn("rounded-full border px-3 py-1 text-[12.5px]", chip.cls)}>
              {chip.label}
            </span>
          ))}
        </div>

        <CabinetGrid state={gridState} items={items} />

        <footer className="mt-16 border-t border-[#2f336e] pt-6 text-[12.5px] leading-relaxed text-[#8b8fc7]">
          <p>个人纪念性再创作，商标归原品牌所有；图源来自公开检索。</p>
          <p className="mt-1">你的鞋柜只保存在你自己的服务端文件里，默认不外传、不用于训练。</p>
        </footer>
      </main>

      {IS_DEV ? (
        <div className="fixed inset-x-3 bottom-3 z-30 mx-auto w-fit max-w-[calc(100vw-1.5rem)] rounded-full border border-[#2f336e] bg-[#1c1f4a]/95 px-2 py-1.5 backdrop-blur">
          <div className="flex items-center gap-1 text-[12.5px]">
            <span className="hidden px-2 text-[#8b8fc7] sm:inline">预览状态</span>
            {([
              { key: "empty", label: "空" },
              { key: "loading", label: "加载中" },
              { key: "populated", label: "有鞋" },
              { key: "failed", label: "失败" },
            ] as const).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setPreview(key)}
                className={cn(
                  "rounded-full px-2.5 py-1",
                  preview === key ? "bg-[#5865f2] text-white" : "text-[#babcd9] hover:text-white",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
