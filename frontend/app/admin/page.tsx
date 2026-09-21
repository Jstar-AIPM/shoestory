"use client";

/**
 * 管理员控制台（阶段 4）
 *
 * 给项目所有者用的最小运维面：
 *   · 看每个邀请码用了多少次、各自建了几双鞋
 *   · 新建邀请码 / 作废邀请码
 *   · 一键清理某个访客的数据（演示几个月后避免对象存储堆垃圾）
 * 非管理员访问 → 明确提示"需要管理员码登录"，不泄露任何数据。
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PageShell } from "@/components/layout/PageShell";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { StatusChip } from "@/components/ui/StatusChip";
import { createCode, listCodes, me, purgeOwner, revokeCode } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import type { AppError } from "@/lib/api/errors";
import type { CodeInfo, MeOut } from "@/lib/api/types";

export default function AdminPage() {
  const [identity, setIdentity] = useState<MeOut | null>(null);
  const [codes, setCodes] = useState<CodeInfo[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AppError | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const fail = (cause: unknown) =>
    setError(
      cause instanceof ApiError
        ? cause.appError
        : { code: "UNKNOWN", userMessage: "操作失败，请重试。", retryable: true, status: 0 },
    );

  const refresh = useCallback(async () => {
    try {
      setCodes((await listCodes()).items);
      setError(null);
    } catch (cause) {
      fail(cause);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((data) => {
        if (!cancelled) setIdentity(data);
      })
      .catch(() => undefined);
    listCodes()
      .then((data) => {
        if (!cancelled) setCodes(data.items);
      })
      .catch((cause: unknown) => {
        if (!cancelled) fail(cause);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const add = async () => {
    setBusy(true);
    try {
      const created = await createCode({ note: note.trim() });
      setNote("");
      setToast(`已创建邀请码：${created.code}（${created.remaining} 次 / 到期 ${created.expires_at?.slice(0, 10)}）`);
      await refresh();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (code: string) => {
    setBusy(true);
    try {
      await revokeCode(code);
      setToast(`已作废：${code}`);
      await refresh();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  const purge = async (ownerId: string) => {
    if (!window.confirm("确定清理这个访客的全部数据吗？档案与画稿都会删除，不可撤销。")) return;
    setBusy(true);
    try {
      const result = await purgeOwner(ownerId);
      setToast(`已清理 ${ownerId}（删除 ${result.removed_files} 个文件）`);
      await refresh();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-theme="wall" className="min-h-screen">
      <div className="wall-gradient w-full">
        <PageShell className="!py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-baseline gap-3">
              <span className="text-[20px] font-extrabold tracking-wide text-white">履历 · 管理员</span>
              <span className="hidden text-[12.5px] text-muted sm:inline">邀请码与访客数据管理</span>
            </div>
            <div className="flex items-center gap-2">
              {identity?.role === "admin" ? (
                <StatusChip tone="progress">管理员模式</StatusChip>
              ) : (
                <StatusChip tone="warn">需要管理员码</StatusChip>
              )}
              <Link href="/" className="text-[13px] text-muted underline underline-offset-4 hover:text-ink">
                回鞋柜
              </Link>
            </div>
          </div>
        </PageShell>
      </div>

      <main className="bg-[#0a0b1e]">
        <PageShell className="!py-10">
          {error ? (
            <div className="mb-6">
              <Card className="px-5 py-4">
                <Alert tone="danger" title="操作没有成功">
                  {error.userMessage}
                  {error.code === "FORBIDDEN" || error.code === "AUTH_REQUIRED" ? (
                    <span> 请先用管理员码在首页登录。</span>
                  ) : null}
                </Alert>
              </Card>
            </div>
          ) : null}

          {toast ? (
            <div className="mb-6">
              <Card className="px-5 py-4">
                <Alert tone="info" title="已完成">
                  <span className="break-all">{toast}</span>
                </Alert>
              </Card>
            </div>
          ) : null}

          <Card className="px-5 py-5 sm:px-6">
            <h2 className="text-[17px] font-semibold text-ink">新建邀请码</h2>
            <p className="mt-1.5 text-[13px] text-muted">
              默认：有效期 30 天、最多 20 次生成。备注只你自己看得到（例如&quot;给 A 公司面试官&quot;）。
            </p>
            <div className="mt-4 flex flex-col gap-3 sm:flex-row">
              <Input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="备注（可选）"
                maxLength={120}
                aria-label="备注"
              />
              <Button variant="primary" className="btn-blurple shrink-0" onClick={() => void add()} disabled={busy}>
                创建
              </Button>
            </div>
          </Card>

          <div className="mt-8 overflow-x-auto">
            <Card className="min-w-[720px]">
              <table className="w-full text-left text-[13.5px]">
                <thead className="border-b border-line text-[12.5px] text-muted">
                  <tr>
                    <th className="px-4 py-3">邀请码</th>
                    <th className="px-4 py-3">备注</th>
                    <th className="px-4 py-3">已用 / 上限</th>
                    <th className="px-4 py-3">鞋柜</th>
                    <th className="px-4 py-3">到期</th>
                    <th className="px-4 py-3">状态</th>
                    <th className="px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {codes.map((item) => (
                    <tr key={item.code} className="border-b border-line/60 align-middle">
                      <td className="break-all px-4 py-3 font-mono text-[12.5px] text-ink">{item.code}</td>
                      <td className="px-4 py-3 text-muted">{item.note || "—"}</td>
                      <td className="px-4 py-3">
                        {item.used_count} / {item.max_uses ?? "不限"}
                      </td>
                      <td className="px-4 py-3">{item.archived_count} 双</td>
                      <td className="px-4 py-3 text-faint">{item.expires_at?.slice(0, 10) ?? "不过期"}</td>
                      <td className="px-4 py-3">
                        {item.status === "revoked" ? (
                          <StatusChip tone="danger">已作废</StatusChip>
                        ) : item.expired ? (
                          <StatusChip tone="warn">已过期</StatusChip>
                        ) : item.role === "admin" ? (
                          <StatusChip tone="progress">管理员</StatusChip>
                        ) : (
                          <StatusChip tone="success">可用</StatusChip>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          {item.role === "admin" ? (
                            <span className="text-[12px] text-faint">不可作废</span>
                          ) : (
                            <Button size="sm" variant="ghost" disabled={busy || item.status === "revoked"} onClick={() => void revoke(item.code)}>
                              作废
                            </Button>
                          )}
                          {item.role === "admin" ? null : (
                            <Button size="sm" variant="danger" disabled={busy} onClick={() => void purge(item.owner_id)}>
                              清理数据
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {codes.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-muted">
                        还没有邀请码 —— 先在上面创建一个，或把初始邀请码放进环境变量 INVITE_CODES。
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Card>
          </div>

          <p className="mt-6 text-[12.5px] leading-relaxed text-faint">
            提示：作废邀请码不会删除访客已归档的数据（只是不能再生成）；
            &quot;清理数据&quot;才会真正删除该访客的档案与画稿，且不可撤销。
          </p>
        </PageShell>
      </main>
    </div>
  );
}
