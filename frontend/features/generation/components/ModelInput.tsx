/**
 * 型号输入区（位于画廊墙上的 hero 里）
 *
 * 视觉：胶囊输入 + 深底白雪按钮（来自 设计参考 上 Discord 的设计语言）。
 * 文案原则（前端手册 11.1）：说明"要做什么""为什么""会消耗什么"。
 */
export function ModelInput() {
  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          placeholder="例如 kd12 / asics gel nimbus 27"
          maxLength={60}
          aria-label="鞋款型号"
          className="h-12 w-full rounded-full border border-line bg-black/20 px-5 text-[15px] text-ink placeholder:text-faint focus:border-[#5865f2] focus:outline-none sm:max-w-[420px]"
        />
        <button className="btn-snow h-12 shrink-0 rounded-full border px-7 text-[15px] font-semibold transition-colors">
          生成线稿
        </button>
      </div>
      <p className="mt-3 text-[12.5px] text-faint">
        一次生成约 30 秒、消耗 1 次生成额度；生成中可以离开，回来接着看。
      </p>
    </div>
  );
}
