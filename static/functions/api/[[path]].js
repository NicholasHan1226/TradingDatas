// Same-origin proxy for the TradingDatas admin backend.
// Encrypts the browser -> Cloudflare leg so the admin token never crosses plain HTTP.
// The origin is set via TD_API_ORIGIN env in wrangler.toml (default: direct Aliyun).

export async function onRequest(context) {
  const { request, params, env } = context;
  const origin = (env.TD_API_ORIGIN || "http://8.138.181.177:18084").replace(/\/$/, "");
  const suffix = Array.isArray(params.path) ? params.path.join("/") : (params.path || "");
  const incoming = new URL(request.url);
  const target = origin + "/" + suffix + incoming.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("cf-connecting-ip");
  headers.delete("cf-ipcountry");
  headers.delete("cf-ray");
  headers.delete("cf-visitor");
  headers.delete("x-forwarded-for");
  headers.delete("x-forwarded-proto");

  const init = {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "manual",
  };

  const upstream = await fetch(target, init);
  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.set("access-control-allow-origin", "*");
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export async function onRequestOptions() {
  return new Response(null, {
    status: 204,
    headers: {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
      "access-control-allow-headers": "Content-Type, Authorization",
      "access-control-max-age": "86400",
    },
  });
}
