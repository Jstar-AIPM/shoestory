"use client";

/**
 * 归档表单（时间 / 故事，均可跳过）
 * 时间框实时显示后端解析出的排序键 —— 让"自由文本"的排序规则对用户可见（前端工程约定 13.1）。
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
}: {
  modelName: string;
  busy: boolean;
  onSubmit: (payload: { date_text: string | null; story: string | null }) => void;
  onSkip: () => void;
}) {
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
    <Card className="px-5 py-5 sm:px-6">
      <h2 className="text-[17px] font-semibold text-ink">给「{modelName}」记一笔（选填）</h2>
      <p className="mt-2 text-[13px] text-muted">
        时间怎么写都行；故事只有你自己能看到。两项都可以跳过。
      </p>

      <div className="mt-4 space-y-4">
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
            placeholder="这双鞋陪你经历了什么？（可不填）"
            className="mt-1.5"
          />
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          className="btn-blurple"
          disabled={busy}
          onClick={() => onSubmit({ date_text: date.trim() || null, story: story.trim() || null })}
        >
          归档进鞋柜
        </Button>
        <Button variant="ghost" onClick={onSkip} disabled={busy}>
          跳过，直接归档
        </Button>
      </div>
    </Card>
  );
}
