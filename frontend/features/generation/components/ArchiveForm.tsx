"use client";

/**
 * 归档表单（型号 / 时间 / 故事）
 *
 * 现在**以弹窗形式**出现（2026-09-23 反馈：以前挂在页面下方，点「满意归档」像没反应）。
 * 时间框只给"人话"反馈（如「识别为 2021年6月」），不露排序键。
 *
 * 2026-09-25：**型号也放进来了**（产品反馈 14）—— 识别结果可能认错，
 * 与其让人归档完再去详情页改，不如在这里就能直接改。默认带出识别到的型号。
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { parseDateText } from "@/lib/api/tasks";

export function ArchiveForm({
  modelName,
  busy,
  onSubmit,
  onSkip,
  onCancel,
}: {
  /** 体检识别出的型号 —— 作为型号输入框的默认值，用户可以直接改 */
  modelName: string;
  busy: boolean;
  onSubmit: (payload: { model_name: string; date_text: string | null; story: string | null }) => void;
  onSkip: () => void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState(modelName);
  const [date, setDate] = useState("");
  const [story, setStory] = useState("");
  const [parsedHint, setParsedHint] = useState<string | null>(null);
  // 空值时直接给出提示（渲染期计算），避免在 effect 里同步 setState
  const hint = date.trim() ? (parsedHint ?? "") : "留空即可，之后也能补";

  useEffect(() => {
    const text = date.trim();
    if (!text) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const result = await parseDateText(text);
        if (!cancelled) setParsedHint(result.hint);
      } catch {
        if (!cancelled) setParsedHint("");
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [date]);

  return (
    <Card className="border-0 px-0 py-0 shadow-none">
      <h2 className="pr-16 text-[17px] font-semibold text-ink">给「{modelName}」记一笔</h2>
      <p className="mt-2 text-[13px] text-muted">
        型号是识别出来的，认错了可以直接改；时间怎么写都行；故事只有您自己能看到。
        时间与故事可以跳过，之后也能补。
      </p>

      <div className="mt-4 space-y-4">
        <div>
          <label htmlFor="archive-name" className="text-[13px] font-medium text-muted">
            鞋款型号
          </label>
          <Input
            id="archive-name"
            value={name}
            maxLength={80}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如 ASICS GEL-NIMBUS 27"
            className="mt-1.5"
          />
        </div>

        <div>
          <label htmlFor="date-text" className="text-[13px] font-medium text-muted">
            时间 / 日期
          </label>
          <Input
            id="date-text"
            value={date}
            maxLength={40}
            onChange={(event) => setDate(event.target.value)}
            placeholder="2021 / 2021-06-15 / 2021年6月 / 2019–2021 / 高三那年"
            className="mt-1.5"
          />
          <p className="mt-1.5 text-[12.5px] text-faint">{hint}</p>
        </div>

        <div>
          <label htmlFor="story" className="text-[13px] font-medium text-muted">
            故事
          </label>
          <Textarea
            id="story"
            rows={4}
            maxLength={2000}
            value={story}
            onChange={(event) => setStory(event.target.value)}
            placeholder="这双鞋陪您经历了什么？（可不填）"
            className="mt-1.5"
          />
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          className="btn-blurple"
          disabled={busy}
          onClick={() =>
            onSubmit({
              // 型号被清空时退回识别结果，不让用户意外存进一个空标题
              model_name: name.trim() || modelName,
              date_text: date.trim() || null,
              story: story.trim() || null,
            })
          }
        >
          归档进鞋柜
        </Button>
        <Button variant="ghost" onClick={onSkip} disabled={busy}>
          跳过，直接归档
        </Button>
        {onCancel ? (
          <button
            onClick={onCancel}
            disabled={busy}
            className="h-11 rounded-full px-5 text-[14px] text-muted hover:text-ink disabled:opacity-50"
          >
            取消
          </button>
        ) : null}
      </div>
    </Card>
  );
}
