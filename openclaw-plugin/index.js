/**
 * OpenClaw mem0 Memory Plugin
 *
 * Hooks into OpenClaw's agent lifecycle to:
 * - Write conversation turns to mem0 (agent_end hook)
 * - Inject relevant memories into system prompt (before_prompt_build hook)
 * - Flush conversation to mem0 before compaction (before_compaction hook)
 */

const DEFAULT_CONFIG = {
  mem0Url: "http://localhost:8230",
  userId: "boss",
  agentIds: ["dev", "main", "pm", "researcher", "pjm", "prototype"],
  enableWrite: true,
  enableInject: true,
  injectLimit: 5,
  injectMaxChars: 800,
  debounceMs: 60000, // 1 minute debounce per sessionKey
  injectTimeoutMs: 3000,
};

// Debounce map: sessionKey -> last write timestamp
const lastWriteMap = new Map();

function getConfig(pluginConfig) {
  return { ...DEFAULT_CONFIG, ...(pluginConfig || {}) };
}

function shouldProcess(agentId, cfg) {
  if (!agentId) return false;
  if (!cfg.agentIds || cfg.agentIds.length === 0) return true;
  return cfg.agentIds.includes(agentId);
}

function isDebounced(sessionKey, cfg) {
  if (!sessionKey) return false;
  const last = lastWriteMap.get(sessionKey);
  if (!last) return false;
  return Date.now() - last < cfg.debounceMs;
}

function markWritten(sessionKey) {
  if (sessionKey) {
    lastWriteMap.set(sessionKey, Date.now());
  }
}

/**
 * Extract the last user+assistant exchange from messages array.
 * OpenClaw message format: [{role: 'user'|'assistant', content: string|array}, ...]
 */
function extractLastExchange(messages) {
  if (!Array.isArray(messages) || messages.length === 0) return null;

  let lastAssistant = null;
  let lastUser = null;

  // Walk backwards to find last assistant, then user before it
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (!msg || !msg.role) continue;

    if (!lastAssistant && msg.role === "assistant") {
      lastAssistant = extractTextContent(msg.content);
    } else if (lastAssistant && !lastUser && msg.role === "user") {
      lastUser = extractTextContent(msg.content);
      break;
    }
  }

  if (!lastAssistant && !lastUser) return null;

  const parts = [];
  if (lastUser) parts.push(`User: ${lastUser}`);
  if (lastAssistant) parts.push(`Assistant: ${lastAssistant}`);

  return parts.join("\n\n");
}

function extractTextContent(content) {
  if (!content) return "";
  if (typeof content === "string") return content.slice(0, 2000);
  if (Array.isArray(content)) {
    return content
      .filter((c) => c && c.type === "text" && c.text)
      .map((c) => c.text)
      .join(" ")
      .slice(0, 2000);
  }
  return String(content).slice(0, 2000);
}

async function writeToMem0(cfg, agentId, text) {
  const url = `${cfg.mem0Url}/memory/add`;
  const body = JSON.stringify({
    text,
    user_id: cfg.userId,
    agent_id: agentId,
    infer: true,
  });

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: AbortSignal.timeout(5000),
  });

  if (!resp.ok) {
    const errText = await resp.text().catch(() => "unknown");
    throw new Error(`mem0 add failed: ${resp.status} ${errText}`);
  }

  return await resp.json();
}

async function searchMem0(cfg, agentId, query) {
  const params = new URLSearchParams({
    query,
    user_id: cfg.userId,
    agent_id: agentId,
    limit: String(cfg.injectLimit),
  });

  const url = `${cfg.mem0Url}/memory/search?${params}`;
  const resp = await fetch(url, {
    signal: AbortSignal.timeout(cfg.injectTimeoutMs),
  });

  if (!resp.ok) {
    throw new Error(`mem0 search failed: ${resp.status}`);
  }

  const data = await resp.json();
  return data.results || [];
}

function formatMemoriesForInjection(results, maxChars) {
  if (!results || results.length === 0) return null;

  const lines = results
    .filter((r) => r && r.memory)
    .map((r) => `- ${r.memory}`);

  if (lines.length === 0) return null;

  const text = lines.join("\n");
  const truncated = text.slice(0, maxChars);

  return `## Relevant Memories\n${truncated}`;
}

// ──────────────────────────────────────────────
// Plugin Definition
// ──────────────────────────────────────────────

const plugin = {
  id: "mem0-memory-plugin",
  name: "Mem0 Memory Plugin",
  description:
    "Integrates mem0 memory service with OpenClaw via agent lifecycle hooks for real-time memory write and injection.",

  register(api) {
    const cfg = getConfig(api.pluginConfig);
    console.log(
      `[mem0-plugin] Registered. mem0Url=${cfg.mem0Url} userId=${cfg.userId} agentIds=${cfg.agentIds.join(",")}`
    );
    console.log(
      `[mem0-plugin] enableWrite=${cfg.enableWrite} enableInject=${cfg.enableInject}`
    );

    // ── 1. agent_end: write conversation turn to mem0 ──
    if (cfg.enableWrite) {
      api.on("agent_end", async (event, ctx) => {
        try {
          if (!event.success) return;
          const agentId = ctx.agentId;
          if (!shouldProcess(agentId, cfg)) return;
          if (isDebounced(ctx.sessionKey, cfg)) {
            console.log(
              `[mem0-plugin] agent_end debounced for session=${ctx.sessionKey}`
            );
            return;
          }

          const exchange = extractLastExchange(event.messages);
          if (!exchange) return;

          await writeToMem0(cfg, agentId, exchange);
          markWritten(ctx.sessionKey);
          console.log(
            `[mem0-plugin] agent_end: wrote to mem0 agent=${agentId} session=${ctx.sessionKey}`
          );
        } catch (err) {
          console.error(`[mem0-plugin] agent_end error:`, err.message);
        }
      });

      // ── 3. before_compaction: flush to mem0 before compaction ──
      api.on("before_compaction", async (event, ctx) => {
        try {
          const agentId = ctx.agentId;
          if (!shouldProcess(agentId, cfg)) return;

          const messages = event.messages;
          if (!Array.isArray(messages) || messages.length === 0) return;

          const exchange = extractLastExchange(messages);
          if (!exchange) return;

          await writeToMem0(cfg, agentId, exchange);
          markWritten(ctx.sessionKey);
          console.log(
            `[mem0-plugin] before_compaction: flushed to mem0 agent=${agentId}`
          );
        } catch (err) {
          console.error(`[mem0-plugin] before_compaction error:`, err.message);
        }
      });
    }

    // ── 2. before_prompt_build: inject memories into system prompt ──
    if (cfg.enableInject) {
      api.on("before_prompt_build", async (event, ctx) => {
        try {
          const agentId = ctx.agentId;
          if (!shouldProcess(agentId, cfg)) return;

          const query = (event.prompt || "").slice(0, 200);
          if (!query.trim()) return;

          const results = await searchMem0(cfg, agentId, query);
          const injected = formatMemoriesForInjection(results, cfg.injectMaxChars);

          if (!injected) return;

          console.log(
            `[mem0-plugin] before_prompt_build: injecting ${results.length} memories agent=${agentId}`
          );

          return { prependContext: injected };
        } catch (err) {
          // Timeout or search failure — silently skip injection
          if (err.name === "TimeoutError" || err.name === "AbortError") {
            console.log(`[mem0-plugin] before_prompt_build: search timed out, skipping injection`);
          } else {
            console.error(`[mem0-plugin] before_prompt_build error:`, err.message);
          }
          return;
        }
      });
    }
  },
};

export { plugin as default };
