/**
 * 画稿展示层的风格适配。
 *
 * 背景：画稿本身的前景内容是天差地别的两类 ——
 * - **黑白线稿**：白底黑线，直接贴在页面上会显得"空"。所以叠一层**牛皮纸底**，
 *   再用 `mix-blend-mode: multiply` 让白底变透明、黑线透出纸色。
 * - **水彩**：画稿**自带暖白纸底**（实测 RGB 250,246,240）。如果再叠牛皮纸 + multiply，
 *   整张会被染成褐色、颜色被压暗 —— 等于把作品毁掉。
 *
 * 所以按风格切换。默认（未登记的风格）走"不叠纸"这条：
 * 彩色画稿被染色的代价远大于"少一层纸感"，**宁可保守**。
 */
const KRAFT_PAPER_STYLE_IDS = new Set<string>(["bw_lineart"]);

export function usesKraftPaperLayer(styleId?: string | null): boolean {
  return !!styleId && KRAFT_PAPER_STYLE_IDS.has(styleId);
}

/** 画稿容器的类名：叠加层按风格给。 */
export function artworkFrameClass(styleId?: string | null): string {
  return usesKraftPaperLayer(styleId) ? "artwork-paper" : "artwork-plain";
}
