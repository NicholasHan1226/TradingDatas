export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request);
    const url = new URL(request.url);
    const normalizedPath = url.pathname.replace(/\/+$/, "") || "/";
    const terminalSegment = normalizedPath.slice(normalizedPath.lastIndexOf("/") + 1);
    const isAppRoute =
      normalizedPath !== "/" &&
      !normalizedPath.startsWith("/api/") &&
      !normalizedPath.startsWith("/assets/") &&
      !terminalSegment.includes(".");

    if (response.status !== 404 || !isAppRoute || !["GET", "HEAD"].includes(request.method)) {
      return response;
    }

    const indexUrl = new URL(url);
    indexUrl.pathname = "/index.html";
    indexUrl.search = "";
    return env.ASSETS.fetch(new Request(indexUrl, request));
  },
};
