// Optional Cloudflare Worker relay in front of the bridge.
//
// Only needed if Claude's connector broker cannot reach your origin directly
// (symptom: "Couldn't reach the server" while the same URL works in Claude
// Code and your access logs show zero inbound requests — see docs/troubleshooting.md).
// Fronting the origin with a workers.dev URL fixes it.
//
// Only the tokened MCP path, /healthz and the Resend inbound webhook pass
// through; everything else is rejected without touching the origin.
//
// The webhook is relayed too so a single hostname covers the whole bridge.
// That adds no exposure: the origin verifies the Svix signature itself and
// fails closed when no signing secret is configured, so an unsigned request
// reaching it is rejected there.

export default {
  async fetch(request, env) {
    if (!env.ORIGIN || !env.MCP_TOKEN) {
      return new Response("worker not configured: set ORIGIN and MCP_TOKEN", {
        status: 500,
      });
    }
    const url = new URL(request.url);
    const mcpPath = `/${env.MCP_TOKEN}/mcp`;
    const allowed =
      url.pathname === "/healthz" ||
      url.pathname === "/webhook/inbound" ||
      url.pathname === mcpPath ||
      url.pathname.startsWith(`${mcpPath}/`);
    if (!allowed) {
      return new Response("not found", { status: 404 });
    }
    const upstream = new URL(url.pathname + url.search, env.ORIGIN);
    return fetch(new Request(upstream, request));
  },
};
