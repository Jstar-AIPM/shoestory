"use client";

/**
 * 「我的鞋柜」首页 —— 入口即产品。
 *
 * 视觉方向（已确认 = 方案 C「黑夜画廊 × 纸白阅读」）：
 *   · 页面底 / 顶栏 / hero / 墙面文字：深色画廊墙（`data-theme="wall"`）
 *     —— 白底黑线的线稿挂在深色墙上，像装裱好的作品，对比最大化
 *   · 卡片 / 表单 / 故事：纸白阅读区（`data-theme="card-paper"`，由 Card/ShoeCard 自带）
 *     —— 中文长文与文书操作保持纸白护眼
 *   两套语义变量来自 设计参考 上 Discord 的设计系统（详见 docs/设计参考调研.md）。
 *
 * 当前进度：3.0 代表页（视觉确认版）
 *   已实现：App Shell、双作用域主题、hero 输入区、鞋柜网格四态、状态胶囊、墙面色调
 *   未实现（后续小步）：真实接口、生成全流程、详情、轮询与恢复 —— 见 docs/阶段开发文档.md
 */
import { useState } from "react";

import { PageShell } from "@/components/layout/PageShell";
import { StatusChip } from "@/components/ui/StatusChip";
import { CabinetGrid, type GridState } from "@/features/cabinet/components/CabinetGrid";
import type { ShoeCardItem } from "@/features/cabinet/components/ShoeCard";
import { ModelInput } from "@/features/generation/components/ModelInput";

const IS_DEV = process.env.NODE_ENV !== "production";

/** 视觉评审用示例数据（自研占位线稿，无任何品牌图像；生产构建不使用） */
const PREVIEW_ITEMS: ShoeCardItem[] = [
  { shoeId: "p1", modelName: "ASICS GEL-NIMBUS 27", artworkUrl: "/preview/sample-1.jpg", dateText: "2026-09-20" },
  { shoeId: "p2", modelName: "Nike KD 12", artworkUrl: "/preview/sample-2.jpg", dateText: "2021年6月" },
  { shoeId: "p3", modelName: "Air Jordan 14", artworkUrl: "/preview/sample-3.jpg", dateText: "2019" },
  { shoeId: "p4", modelName: "adidas Ultraboost Light", artworkUrl: "/preview/sample-4.jpg", dateText: null },
  { shoeId: "p5", modelName: "New Balance 990v6", artworkUrl: "/preview/sample-5.jpg", dateText: "高三那年" },
];

const STATE_LABELS: Array<{ key: GridState | "populated"; label: string }> = [
  { key: "empty", label: "空" },
  { key: "loading", label: "加载中" },
  { key: "populated", label: "有鞋" },
  { key: "failed", label: "失败" },
];

export default function CabinetPage() {
  const [preview, setPreview] = useState<GridState | "populated">("populated");

  // 示例数据**只在开发环境**生效：生产构建渲染真实空态，绝不把示例数据当成真实鞋柜
  const gridState: GridState = !IS_DEV ? "empty" : preview === "populated" ? "ready" : preview;
  const items = IS_DEV && preview === "populated" ? PREVIEW_ITEMS : [];

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
            <StatusChip tone="success">真实模型</StatusChip>
          </div>
        </PageShell>

        <PageShell className="!pt-10 !pb-14 sm:!pt-14 sm:!pb-20">
          <p className="display-upper text-[13px] text-accent">MY SHOE CABINET</p>
          <h1
            className="display-upper mt-3 max-w-[560px] text-[34px] text-white sm:text-[46px]"
          >
            一双鞋，
            <br />
            就是履历上的一行
          </h1>
          <p className="mt-5 max-w-[520px] text-[15px] leading-relaxed text-muted">
            输入鞋款型号，它会变成一张黑白线稿，收进你的鞋柜。线下穿旧的鞋，在这里留下痕迹。
          </p>
          <div className="mt-9 max-w-[640px]">
            <ModelInput />
          </div>
        </PageShell>
      </div>

      {/* 画廊墙：白底黑线的画稿挂在这里 */}
      <main className="w-full bg-[#0a0b1e]">
        <PageShell className="!py-12">
          {/* 质检 / 进度状态（演示；真实数据在 3.2 接入） */}
          <div className="mb-8 flex flex-wrap items-center gap-2.5">
            <StatusChip tone="success">质检通过 0.87</StatusChip>
            <StatusChip tone="progress">生成中 12s</StatusChip>
            <StatusChip tone="warn">Logo 不够清晰</StatusChip>
            <StatusChip tone="danger">两次质检未通过</StatusChip>
          </div>

          <CabinetGrid state={gridState} items={items} />

          <footer className="mt-16 border-t border-line pt-6 text-[12.5px] leading-relaxed text-faint">
            <p>个人纪念性再创作，商标归原品牌所有；图源来自公开检索。</p>
            <p className="mt-1">你的鞋柜只保存在你自己的服务端文件里，默认不外传、不用于训练。</p>
          </footer>
        </PageShell>
      </main>

      {/* 仅开发环境：视觉评审与四态验收用的状态切换器（生产构建不渲染） */}
      {IS_DEV ? (
        <div className="fixed inset-x-3 bottom-3 z-30 mx-auto w-fit max-w-[calc(100vw-1.5rem)] rounded-full border border-line bg-surface/95 px-2 py-1.5 backdrop-blur">
          <div className="flex items-center gap-1 text-[12.5px]">
            <span className="hidden px-2 text-faint sm:inline">预览状态（仅开发环境）</span>
            {STATE_LABELS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setPreview(key)}
                className={
                  preview === key
                    ? "rounded-full bg-[#5865f2] px-2.5 py-1 text-white"
                    : "rounded-full px-2.5 py-1 text-muted hover:text-ink"
                }
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
