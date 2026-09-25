# 前端部署（veFaaS / Next.js standalone）

```bash
cd frontend
vefaas deploy --yes \
  --buildCommand "BACKEND_URL=https://s0elk3ogikiojvt96erdp.apigateway-cn-beijing.volceapi.com npm run build && cp -r .next/static .next/standalone/.next/static && cp -r public .next/standalone/public" \
  --outputPath .next/standalone
```

## 两个必须记住的坑

**① `BACKEND_URL` 必须在构建时注入。**
`next.config` 里的 rewrites 在 `npm run build` 时就固化了，部署后再配环境变量没用 ——
表现为"页面能开，但所有接口 404"。

**② `public/` 与 `.next/static` 都要手动拷进 standalone 产物。**
Next 的 standalone 输出**只带 server 代码**，静态资源不会自动进去。
漏了 `.next/static` → 样式/JS 全挂；漏了 `public/` → `public/` 下的图片一律 404
（2026-09-25 踩到：示例图线上 404，本地却好好的，就是因为这里少了 `cp -r public ...`）。

部署后自检（30 秒）：

```bash
BASE=https://sf7d7f90oeokpqnk7mllk.apigateway-cn-beijing.volceapi.com
curl -s -o /dev/null -w "首页 %{http_code}\n" "$BASE/"
curl -s -o /dev/null -w "静态图 %{http_code}\n" "$BASE/examples/example-1.png"   # 应该是 200
curl -s "$BASE/api/v1/health" | python3 -m json.tool | grep -E 'status|missing_prompts'
```
