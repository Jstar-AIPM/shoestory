import { Card, Skeleton } from "@/components/ui/Card";
import { ShoeCard, type ShoeCardItem } from "@/features/cabinet/components/ShoeCard";

export type GridState = "loading" | "empty" | "ready" | "failed";

/**
 * 鞋柜网格。
 *
 * 前端工程约定 9.3 硬要求：loading / empty / failed 必须分开 ——
 * 接口还没回来时**绝不能**先显示"还没有鞋"。
 */
export function CabinetGrid({
  state,
  items,
  onRetry,
  onOpen,
}: {
  state: GridState;
  items: ShoeCardItem[];
  onRetry?: () => void;
  onOpen?: (shoeId: string) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="wall-heading text-[19px] font-semibold text-ink">我的鞋柜</h2>
        <span className="wall-heading text-[13px] text-faint">
          {state === "ready" ? `共 ${items.length} 双` : ""}
        </span>
      </div>

      {/* ② 加载中：骨架屏（3:2 占位，避免页面跳动） */}
      {state === "loading" ? (
        <div className="mt-4 grid min-w-0 grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="overflow-hidden rounded-[var(--radius-card)] border border-line">
              <Skeleton className="frame-3x2 !rounded-none" />
              <div className="px-3 py-3">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="mt-2 h-3 w-16" />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* ① 空：请求成功但确实没有数据 —— 给出下一步动作（压缩高度，首屏要能看到「我的鞋柜」） */}
      {state === "empty" ? (
        <Card className="mt-3 border-dashed px-5 py-5 text-center shadow-none">
          <p className="text-[15px] font-semibold text-ink">鞋柜还是空的</p>
          <p className="mx-auto mt-1.5 max-w-[460px] text-[13px] leading-relaxed text-muted">
            在上面上传一张您那双鞋的照片（白底、正侧面最好），它会变成一张黑白线稿，成为鞋柜里的第一行。
          </p>
        </Card>
      ) : null}

      {/* ③ 失败：说明发生了什么 + 是否可重试 */}
      {state === "failed" ? (
        <Card className="mt-4 border-danger/25 px-6 py-10 text-center shadow-none">
          <p className="text-[15px] text-ink">鞋柜读取失败，正在重试</p>
          <p className="mt-2 text-[13px] text-muted">如果一直失败，请确认后端服务是否在运行。</p>
          <button
            onClick={onRetry}
            className="mt-4 rounded-[var(--radius-btn)] border border-line bg-surface px-4 py-2 text-[13.5px] text-ink hover:border-ink/40"
          >
            重新加载
          </button>
        </Card>
      ) : null}

      {/* ④ 成功：3:2 网格 */}
      {state === "ready" && items.length > 0 ? (
        <div className="mt-4 grid min-w-0 grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((item) => (
            <ShoeCard key={item.shoeId} item={item} onOpen={onOpen} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
