"use client";

/**
 * 「我的鞋柜」首页 —— 入口即产品。
 *
 * 当前进度：**3.0 代表页（视觉确认版）**
 *   - 已实现：App Shell、设计变量、型号输入区、鞋柜网格（加载/空/成功/失败 四态）、顶栏与运行模式徽标
 *   - 未实现（后续小步）：真实接口、生成全流程、详情弹窗、恢复与轮询 —— 见 docs/阶段开发文档.md
 *
 * 开发环境提供一个「预览状态」切换器：用于视觉评审与四态验收（生产构建中不渲染）。
 */
import { useState } from "react";

import { PageShell } from "@/components/layout/PageShell";
import { TopBar } from "@/components/layout/TopBar";
import { Card } from "@/components/ui/Card";
import { CabinetGrid, type GridState } from "@/features/cabinet/components/CabinetGrid";
import type { ShoeCardItem } from "@/features/cabinet/components/ShoeCard";
import { ModelInput } from "@/features/generation/components/ModelInput";
import { cn } from "@/lib/utils/cn";

const IS_DEV = process.env.NODE_ENV !== "production";

/** 视觉评审用示例数据（自研占位线稿，无任何品牌图像；生产版本不使用） */
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
    <>
      <TopBar mode="real" taskLabel={null} />

      <PageShell>
        {/* 输入区：入口即产品，永远在最上面 */}
        <Card className="px-5 py-5 sm:px-6 sm:py-6">
          <ModelInput />
        </Card>

        {/* 鞋柜 */}
        <div className="mt-10">
          <CabinetGrid state={gridState} items={items} />
        </div>

        <footer className="mt-14 border-t border-line pt-5 text-[12.5px] leading-relaxed text-faint">
          <p>个人纪念性再创作，商标归原品牌所有；图源来自公开检索。</p>
          <p className="mt-1">
            你的鞋柜只保存在你自己的服务端文件里，默认不外传、不用于训练。
          </p>
        </footer>
      </PageShell>

      {/* 仅开发环境：视觉评审与四态验收用的状态切换器（生产构建不渲染） */}
      {IS_DEV ? (
        <div className="fixed inset-x-3 bottom-3 z-30 mx-auto w-fit max-w-[calc(100vw-1.5rem)] rounded-full border border-line bg-surface/95 px-2 py-1.5 shadow-[var(--shadow-soft)] backdrop-blur">
          <div className="flex items-center gap-1 text-[12.5px]">
            <span className="hidden px-2 text-faint sm:inline">预览状态（仅开发环境）</span>
            {STATE_LABELS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setPreview(key)}
                className={cn(
                  "rounded-full px-2.5 py-1",
                  preview === key ? "bg-ink text-white" : "text-muted hover:text-ink",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
