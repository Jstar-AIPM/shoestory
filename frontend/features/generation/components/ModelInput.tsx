/**
 * 型号输入区（3.0 视觉版：只呈现外观与文案，逻辑在 3.2 接入）
 *
 * 文案原则（前端手册 11.1）：说明"要做什么""为什么"、"会消耗什么"。
 */
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export function ModelInput() {
  return (
    <div>
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="font-display text-[19px] font-semibold text-ink">添加一双鞋</h2>
          <p className="mt-1 text-[13px] text-muted">
            输入鞋款型号，它会变成一张黑白线稿，收进你的鞋柜。
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2.5 sm:flex-row">
        <Input
          placeholder="例如 kd12 / aj14 / asics gel nimbus 27"
          maxLength={60}
          aria-label="鞋款型号"
          className="sm:flex-1"
        />
        <Button variant="primary" className="sm:w-32">
          生成线稿
        </Button>
      </div>

      <p className="mt-2.5 text-[12.5px] text-faint">
        一次生成约 30 秒、消耗 1 次生成额度；生成中可以离开，回来接着看。
      </p>
    </div>
  );
}
