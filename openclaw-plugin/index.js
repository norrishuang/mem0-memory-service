/**
 * OpenClaw mem0 Memory Plugin
 *
 * Hooks into OpenClaw's agent lifecycle to:
 * - Write conversation turns to diary file (agent_end hook, enableRawWrite)
 * - Write conversation turns to mem0 with infer (agent_end hook, enableWrite)
 * - Inject relevant memories into system prompt (before_prompt_build hook)
 * - Flush conversation to mem0 before compaction (before_compaction hook)
 */

import { appendFileSync, existsSync, mkdirSync, writeFileSync } from "fs";
import { join } from "path";

/**
 * Resolve an agent's workspace dir from OpenClaw config object.
 * Reads agents.list[].workspace if configured, otherwise falls back to
 * ~/.openclaw/workspace-<agentId>.
 */
function resolveWorkspaceDirFromConfig(config, agentId) {
  try {
    const list = config?.agents?.list;
    if (Array.isArray(list)) {
      const entry = list.find((a) => a && a.id === agentId);
      if (entry?.workspace) return entry.workspace;
    }
    // Check defaults.workspace
    const defaultsWs = config?.agents?.defaults?.workspace;
    // Find default agent id
    const defaultId = config?.agent?.id || "main";
    if (agentId === defaultId && defaultsWs) return defaultsWs;
  } catch (_) {}
  return null;
}

const DEFAULT_CONFIG = {
  mem0Url: "http://localhost:8230",
  userId: "boss",
  agentIds: ["dev", "main", "pm", "researcher", "pjm", "prototype"],
  enableWrite: false,
  enableRawWrite: true, // write diary file (replaces raw mem0 write)
  enableInject: false,
  enableCompactionFlush: true,
  minExchangeLength: 100,
  injectLimit: 5,
  injectMaxChars: 800,
  debounceMs: 60000, // 1 minute debounce per sessionKey
  injectTimeoutMs: 3000,
  compactionMaxChars: 8000, // max chars to flush before compaction
  diaryBasePath:
    process.env.OPENCLAW_BASE ||
    join(process.env.HOME || "/root", ".openclaw", "workspace-dev"),
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

/**
 * Extract all messages as a single text block for compaction flush.
 * Format: "User: ...\n\nAssistant: ...\n\nUser: ...\n\n..."
 * Truncated to maxChars total.
 */
function extractAllMessages(messages, maxChars = 8000) {
  if (!Array.isArray(messages) || messages.length === 0) return null;

  const parts = [];
  for (const msg of messages) {
    if (!msg || !msg.role) continue;
    if (msg.role !== "user" && msg.role !== "assistant") continue;
    const text = extractTextContent(msg.content);
    if (!text.trim()) continue;
    const role = msg.role === "user" ? "User" : "Assistant";
    parts.push(`${role}: ${text}`);
  }

  if (parts.length === 0) return null;

  const full = parts.join("\n\n");
  return full.slice(0, maxChars);
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

/**
 * Get workspace base path for a given agentId.
 * Prefers reading workspace from OpenClaw config over hardcoded paths.
 * Falls back to ~/.openclaw/workspace-<agentId> if not configured.
 */
function getWorkspaceBase(agentId, apiConfig = null) {
  // Best path: read from live OpenClaw config (handles custom workspace dirs like main → /home/ec2-user/clawd)
  if (apiConfig) {
    const fromConfig = resolveWorkspaceDirFromConfig(apiConfig, agentId);
    if (fromConfig) return fromConfig;
  }
  // Fallback: legacy hardcoded path
  const openclawBase =
    process.env.OPENCLAW_BASE ||
    join(process.env.HOME || "/root", ".openclaw");
  if (!agentId) return join(openclawBase, "workspace-dev");
  return join(openclawBase, `workspace-${agentId}`);
}

function isNoise(text) {
  if (!text || text.trim().length < 15) return true;
  const lower = text.toLowerCase();
  if (lower.includes('heartbeat') && !text.includes('HEARTBEAT.md')) return true;
  if (text.startsWith('$ ') || text.startsWith('> ')) return true;
  if (text.trim() === 'NO_REPLY') return true;
  const fillerRe = /^(好的|收到|明白了?|了解|OK|Done|Sure|Got it|Yes|No|嗯|对|是的)[.。]?$/i;
  if (fillerRe.test(text.trim())) return true;
  return false;
}

function cleanContent(text) {
  if (!text || !text.trim()) return '';
  text = text.replace(/\[message_id=om_[a-zA-Z0-9]+\]\s*/g, '');
  text = text.replace(
    /(?:Conversation info|Sender|Inbound Context|Replied message)\s*\(.*?\):\s*```json[\s\S]*?```/g,
    ''
  );
  text = text.replace(/^Runtime:\s*agent=.*$/mg, '');
  text = text.replace(/^## \/home\/.*?\.md\b[\s\S]*?(?=^## |\z)/mg, '');
  text = text.replace(
    /^##\s+(?:Group Chat Context|Inbound Context \(trusted metadata\)|Dynamic Project Context|Silent Replies|Authorized Senders)[\s\S]*?(?=^## |\z)/mg,
    ''
  );
  text = text.replace(
    /```(?:json)?\s*\n(?:\s*[{\["'].*\n){3,}[\s\S]*?```/g,
    '[...output omitted...]'
  );
  text = text.replace(
    /```(?:bash|sh|shell|console|text)?\s*\n(?:.*\n){5,}?```/g,
    '[...output omitted...]'
  );
  text = text.replace(/\n{3,}/g, '\n\n');
  text = text.replace(/[ \t]+/g, ' ');
  text = text.trim();
  return text;
}

/**
 * Append a conversation exchange to today's diary file.
 * Format matches session_snapshot.py output for consistency.
 */
function writeDiaryEntry(cfg, agentId, sessionKey, messages, apiConfig = null) {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const hhmm = now.toISOString().slice(11, 16);

  const workspaceBase = getWorkspaceBase(agentId, apiConfig);
  const diaryDir = join(workspaceBase, "memory");
  const diaryPath = join(diaryDir, `${today}.md`);

  // Extract last user + assistant messages
  let lastAssistant = null;
  let lastUser = null;
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

  // Clean content and filter noise before truncation
  if (lastAssistant) {
    lastAssistant = cleanContent(lastAssistant);
    if (isNoise(lastAssistant)) lastAssistant = null;
    else lastAssistant = lastAssistant.slice(0, 500);
  }
  if (lastUser) {
    lastUser = cleanContent(lastUser);
    if (isNoise(lastUser)) lastUser = null;
    else lastUser = lastUser.slice(0, 500);
  }

  if (!lastAssistant && !lastUser) return false;

  // Short session name: last segment of colon-separated key, max 20 chars
  const shortSession = (sessionKey || "unknown").split(":").pop().slice(0, 20);

  // Ensure directory exists
  if (!existsSync(diaryDir)) {
    mkdirSync(diaryDir, { recursive: true });
  }

  // Create file header if new
  if (!existsSync(diaryPath)) {
    writeFileSync(diaryPath, `# ${today} - Dev Agent 日记\n\n## Session 记录\n\n`);
  }

  // Build entry
  const lines = [`### [${hhmm}] Session ${agentId}:${shortSession}`];
  if (lastUser) lines.push(`- Boss: ${lastUser}`);
  if (lastAssistant) lines.push(`- ${agentId}: ${lastAssistant}`);
  lines.push(""); // trailing blank line

  appendFileSync(diaryPath, lines.join("\n") + "\n");
  return true;
}

async function writeToMem0(cfg, agentId, text, infer = true, timeoutMs = 5000) {
  const url = `${cfg.mem0Url}/memory/add`;
  const body = JSON.stringify({
    text,
    user_id: cfg.userId,
    agent_id: agentId,
    infer,
  });

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: AbortSignal.timeout(timeoutMs),
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
      `[mem0-plugin] enableWrite=${cfg.enableWrite} enableRawWrite=${cfg.enableRawWrite} enableInject=${cfg.enableInject}`
    );

    // ── 1. agent_end: write conversation turn to mem0 ──
    if (cfg.enableWrite || cfg.enableRawWrite) {
      api.on("agent_end", async (event, ctx) => {
        try {
          if (!event.success) return;
          const agentId = ctx.agentId;
          if (!shouldProcess(agentId, cfg)) return;

          if (cfg.enableWrite) {
            // infer=true，让 mem0 自动提炼，保留 debounce
            if (isDebounced(ctx.sessionKey, cfg)) return;
            const exchange = extractLastExchange(event.messages);
            if (!exchange || exchange.length < cfg.minExchangeLength) return;
            await writeToMem0(cfg, agentId, exchange, true);
            markWritten(ctx.sessionKey);
            console.log(`[mem0-plugin] agent_end: infer write agent=${agentId}`);
          } else if (cfg.enableRawWrite) {
            // 写日记文件，不 debounce，每轮都写
            const ok = writeDiaryEntry(cfg, agentId, ctx.sessionKey, event.messages, api.config);
            if (ok) {
              console.log(`[mem0-plugin] agent_end: diary write agent=${agentId} workspace=${getWorkspaceBase(agentId, api.config)}`);
            }
          }
        } catch (err) {
          console.error(`[mem0-plugin] agent_end error:`, err.message);
        }
      });
    }

    // ── 3. before_compaction: flush to mem0 before compaction ──
    if (cfg.enableCompactionFlush) {
      api.on("before_compaction", async (event, ctx) => {
        try {
          const agentId = ctx.agentId;
          if (!shouldProcess(agentId, cfg)) return;

          const messages = event.messages;
          if (!Array.isArray(messages) || messages.length === 0) return;

          const fullContext = extractAllMessages(messages, cfg.compactionMaxChars);
          if (!fullContext) return;

          await writeToMem0(cfg, agentId, fullContext, true, 120000); // 120s timeout for large flush
          markWritten(ctx.sessionKey);
          console.log(
            `[mem0-plugin] before_compaction: flushed ${fullContext.length} chars agent=${agentId}`
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
