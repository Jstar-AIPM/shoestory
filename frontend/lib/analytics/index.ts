/**
 * 产品行为埋点（本地版）
 *
 * 依据前端工程约定 20.2：只在 PRD/指标方案明确后实施 —— 本项目已有指标定义（PRD 4.10），
 * 但**本阶段不接第三方**：事件名先按业务语义定稿，只写本地（console + localStorage 环形缓冲，
 * 最多 200 条），阶段 4 接观测时直接复用这些事件名。
 *
 * 两条硬约束：
 * 1) 埋点失败绝不影响主流程（全部 try/catch）；
 * 2) 不记录故事全文、不记录任何密钥（只记事件名与必要计数/枚举）。
 */
export type AnalyticsEvent =
  | "generation_submitted"
  | "source_confirmed"
  | "generated"
  | "generation_failed"
  | "regenerated"
  | "archived"
  | "detail_opened"
  | "shoe_edited"
  | "shoe_deleted"
  | "cabinet_loaded";

const STORAGE_KEY = "lvli.analytics";
const MAX_ENTRIES = 200;

export type AnalyticsRecord = {
  at: string;
  event: AnalyticsEvent;
  props?: Record<string, string | number | boolean | null>;
};

/** 供开发/验收查看（控制台执行：JSON.parse(localStorage.getItem("lvli.analytics"))） */
export function track(event: AnalyticsEvent, props?: AnalyticsRecord["props"]): void {
  try {
    const record: AnalyticsRecord = { at: new Date().toISOString(), event, props };
    if (process.env.NODE_ENV !== "production") {
      console.debug("[analytics]", record);
    }
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const list: AnalyticsRecord[] = raw ? JSON.parse(raw) : [];
    list.push(record);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(-MAX_ENTRIES)));
  } catch {
    /* 埋点失败不影响任何业务流程 */
  }
}
