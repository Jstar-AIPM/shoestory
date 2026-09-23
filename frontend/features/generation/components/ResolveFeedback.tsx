"use client";

/** 型号校对反馈：确认"是这双吗"的第一步（命中 / 没找到 + 相近候选） */
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { TaskOut } from "@/lib/api/types";

export function ResolveFeedback({
  task,
  onPickCandidate,
  onReset,
}: {
  task: TaskOut;
  onPickCandidate: (name: string) => void;
  onReset: () => void;
}) {
  const info = task.normalize;
  const notFound = task.state === "model_not_found";

  return (
    <Card className="px-5 py-5 sm:px-6">
      {notFound ? (
        <>
          <h2 className="text-[17px] font-semibold text-ink">没找到「{task.query}」这个型号</h2>
          <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
            我不会硬编一个型号糊弄您。可以选一个相近的型号重新试，或直接改输入：
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(info?.candidates ?? []).map((candidate) => (
              <Button key={candidate.name} size="sm" onClick={() => onPickCandidate(candidate.name)}>
                {candidate.name}
              </Button>
            ))}
          </div>
          {info?.candidates?.[0]?.reason ? (
            <p className="mt-3 text-[12.5px] text-faint">相近理由：{info.candidates[0].reason}</p>
          ) : null}
          <div className="mt-4">
            <Button variant="ghost" size="sm" onClick={onReset}>
              重新输入型号
            </Button>
          </div>
        </>
      ) : (
        <>
          <h2 className="text-[17px] font-semibold text-ink">
            识别为：{info?.normalized ?? task.query}
          </h2>
          {info?.note ? <p className="mt-2 text-[13px] text-faint">{info.note}</p> : null}
          <p className="mt-3 text-[13.5px] text-muted">
            接下来请确认参考图 —— 这一步只需 1 秒，能避免画错、白花一次生成额度。
          </p>
          {task.error ? (
            <div className="mt-3">
              <Alert tone="warn" title="这一步没有拿到图片">
                {task.error.message}
              </Alert>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
