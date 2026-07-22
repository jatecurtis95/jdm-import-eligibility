import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import type { BrainEnv } from "./supabase";
import { registerTools } from "./tools";

// Remote MCP server ("the brain") over the ROVER register + model intel that
// the daily scraper keeps fresh in the jdm-connect Supabase project. All data
// served is public-read; the Worker holds no privileged credentials.
export class RoverBrain extends McpAgent<BrainEnv> {
  server = new McpServer({
    name: "jdm-rover-brain",
    version: "1.0.0",
  });

  async init(): Promise<void> {
    registerTools(this.server, this.env);
  }
}

export default {
  fetch(request: Request, env: BrainEnv, ctx: ExecutionContext): Response | Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/mcp" || url.pathname.startsWith("/mcp/")) {
      return RoverBrain.serve("/mcp", { binding: "ROVER_BRAIN" }).fetch(request, env, ctx);
    }
    if (url.pathname === "/") {
      return new Response(
        "jdm-brain: remote MCP server over the ROVER eligibility register. Connect an MCP client to /mcp.",
        { headers: { "Content-Type": "text/plain" } },
      );
    }
    return new Response("Not found", { status: 404 });
  },
};
