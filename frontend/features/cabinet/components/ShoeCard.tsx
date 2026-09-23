import { cn } from "@/lib/utils/cn";

export type ShoeCardItem = {
  shoeId: string;
  modelName: string;
  artworkUrl: string;
  dateText?: string | null;
};

/**
 * 鞋柜网格卡片：外框固定 3:2（与画稿画布比例一致）
 * —— 不论鞋型如何，网格永远不参差。
 */
export function ShoeCard({
  item,
  className,
  onOpen,
}: {
  item: ShoeCardItem;
  className?: string;
  onOpen?: (shoeId: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen?.(item.shoeId)}
      data-theme="card-paper"
      className={cn(
        // min-w-0：grid 子项默认 min-width:auto，遇到长型号名会把整列撑爆（手机端表现为页面横向溢出）
        "group block w-full min-w-0 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface text-left",
        "shadow-[var(--shadow-soft)] transition-colors hover:border-ink/30",
        className,
      )}
    >
      <span className="artwork-paper frame-3x2 border-b border-line">
        {/* 画稿是绝对主角：3:2 容器 + contain，绝不裁切 */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={item.artworkUrl} alt={`${item.modelName} 的黑白线稿`} loading="lazy" />
      </span>
      <span className="block min-w-0 px-3 py-2.5">
        {/* 型号最多两行：手机端单行截断会让人认不出是哪双鞋 */}
        <span
          className="line-clamp-2 text-[14px] font-medium leading-snug text-ink"
          title={item.modelName}
        >
          {item.modelName}
        </span>
        <span className="mt-0.5 block text-[12.5px] text-accent">
          {item.dateText || <span className="text-faint">未填时间</span>}
        </span>
      </span>
    </button>
  );
}
