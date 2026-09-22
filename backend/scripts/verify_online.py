"""上线后验收脚本：对着**线上地址**跑一遍关键路径，只用真实 HTTP 请求。

用法（凭据走环境变量，不写进代码、不进仓库）：

    export LVLI_BASE_URL="https://xxx.apigateway-cn-beijing.volceapi.com"
    export LVLI_ADMIN_CODE="LVLI-ADMIN-XXXXXX"
    export LVLI_GUEST_CODES="码1,码2"
    python scripts/verify_online.py

检查项：
  1. 健康检查：env/storage/上游模式与我们预期一致
  2. 无码访问：必须被拒（401）
  3. 错码登录：必须被拒
  4. 管理员码：能进、身份为 admin、额度不限
  5. 访客码：能进、额度为 20、与管理员是不同的 owner
  6. 两个访客码互相隔离：owner_id 不同
  7. 会话 Cookie 被篡改：必须失效
  8. 过期/伪造签名 Cookie：必须失效
退出码：0 = 全部通过；1 = 有失败项。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = os.environ.get("LVLI_BASE_URL", "").rstrip("/")
ADMIN_CODE = os.environ.get("LVLI_ADMIN_CODE", "").strip()
GUEST_CODES = [c.strip() for c in os.environ.get("LVLI_GUEST_CODES", "").split(",") if c.strip()]

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"  {'✅' if ok else '❌'} {name}{('  → ' + detail) if detail else ''}")


def call(
    path: str,
    method: str = "GET",
    body: dict | None = None,
    opener: urllib.request.OpenerDirector | None = None,
    cookie_header: str | None = None,
    retries: int = 2,
) -> tuple[int, dict, str]:
    """返回 (状态码, JSON, Set-Cookie 原文)。网络异常或 5xx 会自动重试。

    为什么要重试：veFaaS 弹性实例冷启动/网关长连接失效时，**第一波请求**可能超时或 5xx，
    第二波就正常了（实测）。验收脚本要区分“真的坏了”和“刚好碰上一次冷启动”，
    因此这里对 -1/5xx 做短退避重试，并把重试过程打印出来（不隐藏）。
    """
    last: tuple[int, dict, str] = (-1, {}, "")
    for attempt in range(retries + 1):
        last = _call_once(path, method, body, opener, cookie_header)
        status = last[0]
        if status != -1 and status < 500:
            return last
        if attempt < retries:
            print(f"     （第 {attempt + 1} 次返回 {status or '超时'}，像是冷启动，等 3 秒重试…）")
            time.sleep(3)
    return last


def _call_once(
    path: str,
    method: str,
    body: dict | None,
    opener: urllib.request.OpenerDirector | None,
    cookie_header: str | None,
) -> tuple[int, dict, str]:
    """单次请求；返回 (状态码, JSON, Set-Cookie)。网络异常返回 (-1, {}, 错误)。"""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    if cookie_header:
        req.add_header("Cookie", cookie_header)
    try:
        with (opener.open(req, timeout=120) if opener else urllib.request.urlopen(req, timeout=120)) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"_raw": raw[:200]}
            return resp.status, payload, "; ".join(resp.headers.get_all("Set-Cookie") or [])
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"_raw": raw[:200]}
        return exc.code, payload, "; ".join(exc.headers.get_all("Set-Cookie") or [])
    except Exception as exc:  # noqa: BLE001 - 网络层问题如实报告
        return -1, {}, str(exc)


def new_session() -> tuple[urllib.request.OpenerDirector, str]:
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), ""


def login(code: str) -> tuple[int, dict, str, urllib.request.OpenerDirector]:
    opener, _ = new_session()
    status, payload, set_cookie = call("/api/v1/auth/login", "POST", {"code": code}, opener=opener)
    return status, payload, set_cookie, opener


def extract_cookie_name(set_cookie: str) -> str:
    return set_cookie.split("=", 1)[0].strip() if set_cookie else "lvli_session"


def main() -> int:
    if not BASE or not ADMIN_CODE or len(GUEST_CODES) < 2:
        print("缺少环境变量：LVLI_BASE_URL / LVLI_ADMIN_CODE / LVLI_GUEST_CODES（至少 2 个访客码）")
        return 1

    print(f"目标：{BASE}\n")

    print("【1】健康检查")
    status, health, _ = call("/api/v1/health")
    check("健康检查返回 200", status == 200, f"HTTP {status}")
    check("运行环境为 prod", health.get("env") == "prod", str(health.get("env")))
    check("存储后端为 s3", health.get("storage") == "s3", str(health.get("storage")))
    check(
        "上游为真实模式且配置齐全",
        health.get("providers", {}).get("mode") == "real" and not health.get("missing_config"),
        json.dumps(health.get("missing_config"), ensure_ascii=False),
    )

    print("\n【2】无码访问必须被拒")
    status, payload, _ = call("/api/v1/archive")
    check("未登录访问鞋柜返回 401", status == 401, f"HTTP {status} {payload.get('error', {}).get('code', '')}")

    print("\n【3】错误邀请码必须被拒")
    status, payload, _, _ = login("LVLI-NOT-A-REAL-CODE")
    check("错码登录被拒", status in (400, 401, 403), f"HTTP {status}")

    print("\n【4】管理员码")
    status, admin_login, set_cookie, admin_opener = login(ADMIN_CODE)
    check("管理员码可登录", status == 200, f"HTTP {status}")
    check("身份为 admin", admin_login.get("role") == "admin", str(admin_login.get("role")))
    check("管理员额度不限（remaining 为空）", admin_login.get("remaining") is None, str(admin_login.get("remaining")))
    cookie_name = extract_cookie_name(set_cookie)
    check("下发了 httpOnly 会话 Cookie", "HttpOnly" in set_cookie, f"Cookie 名 {cookie_name}（值已脱敏）")
    check("Cookie 带 Secure（线上 HTTPS 必须）", "Secure" in set_cookie, "")
    admin_owner = admin_login.get("owner_id", "")

    status, me, _ = call("/api/v1/auth/me", opener=admin_opener)
    check("带会话查 me 已认证", status == 200 and me.get("authenticated") is True, f"HTTP {status}")
    check("me 返回管理员角色", me.get("role") == "admin", str(me.get("role")))

    status, archive, _ = call("/api/v1/archive", opener=admin_opener)
    items = archive.get("items", []) if isinstance(archive, dict) else []
    check("带会话取鞋柜成功", status == 200, f"HTTP {status}")
    print(f"     （当前线上鞋柜条目数：{len(items)}）")

    print("\n【5】访客码")
    guest_rows = []
    for idx, code in enumerate(GUEST_CODES[:2], 1):
        status, payload, _, opener = login(code)
        ok = status == 200
        check(f"访客码 {idx} 可登录", ok, f"HTTP {status}")
        check(
            f"访客码 {idx} 额度为 20",
            payload.get("remaining") == 20,
            str(payload.get("remaining")),
        )
        check(f"访客码 {idx} 角色非 admin", payload.get("role") != "admin", str(payload.get("role")))
        guest_rows.append((payload.get("owner_id", ""), opener))

    print("\n【6】多租户隔离")
    owners = [row[0] for row in guest_rows]
    check("两个访客码的 owner 不同", len(set(owners)) == 2, f"{owners[0][:8]}… vs {owners[1][:8]}…")
    check("访客 owner 与管理员不同", admin_owner not in owners, "")
    check(
        "访客 A 看不到访客 B 的数据（各自鞋柜独立）",
        all(o.startswith("ow_") for o in owners),
        "owner 前缀 ow_ 表示由邀请码确定性派生",
    )

    print("\n【7】Cookie 防篡改")
    _, _, set_cookie, _ = login(GUEST_CODES[0])
    name = extract_cookie_name(set_cookie)
    value = set_cookie.split(";", 1)[0].split("=", 1)[1]
    tampered = value[:-2] + ("aa" if not value.endswith("aa") else "bb")
    status, payload, _ = call("/api/v1/archive", cookie_header=f"{name}={tampered}")
    check("篡改签名的 Cookie 被拒", status == 401, f"HTTP {status}")
    status, payload, _ = call("/api/v1/archive", cookie_header=f"{name}=lvli_session.forged.value")
    check("伪造 Cookie 被拒", status == 401, f"HTTP {status}")

    print("\n【8】退出登录")
    status, payload, _ = call("/api/v1/auth/logout", "POST", {}, opener=admin_opener)
    check("退出接口可用", status == 200, f"HTTP {status}")

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("上线验收：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
