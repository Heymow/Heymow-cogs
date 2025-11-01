// API client for the React dashboard
// All endpoints are prefixed with /dashboard/proxy (backend exposes public proxy endpoints there).
// This file centralizes all calls used by the frontend components and provides consistent
// error handling and JSON parsing.
//
// Usage examples:
//  import api from './utils/api'
//  const top = await api.fetchTop('30d', 'time', 10)
//  const member = await api.fetchMember(guildId, memberId, '30d')
//
// Note: keep endpoint paths in sync with the backend (streamroles._proxy_handle_* handlers).

const API_BASE = "/dashboard/proxy";
const DEFAULT_TIMEOUT_MS = 15000;

function timeoutPromise(ms, promise) {
  return new Promise((resolve, reject) => {
    const id = setTimeout(() => reject(new Error("Request timed out")), ms);
    promise
      .then((res) => {
        clearTimeout(id);
        resolve(res);
      })
      .catch((err) => {
        clearTimeout(id);
        reject(err);
      });
  });
}

async function doFetch(
  path,
  {
    method = "GET",
    body = null,
    headers = {},
    timeout = DEFAULT_TIMEOUT_MS,
  } = {}
) {
  const url = `${API_BASE}${path.startsWith("/") ? path : "/" + path}`;
  const opts = { method, headers: { ...headers } };
  if (body != null) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const raw = await timeoutPromise(timeout, fetch(url, opts));
  if (!raw.ok) {
    let msg = `${raw.status} ${raw.statusText}`;
    try {
      const txt = await raw.text();
      // if it's JSON with message, include it
      try {
        const j = JSON.parse(txt);
        if (j && j.error) msg += ` - ${j.error}`;
      } catch {}
      if (txt && txt.length && txt.length < 500) msg += ` - ${txt}`;
    } catch {}
    const err = new Error(`API error: ${msg}`);
    err.status = raw.status;
    throw err;
  }
  const ct = raw.headers.get("content-type") || "";
  if (ct.includes("application/json")) return raw.json();
  return raw.text();
}

export default {
  // Overview
  async fetchTop(period = "30d", metric = "time", limit = 10) {
    return doFetch("/top", {
      method: "POST",
      body: { period, metric, limit },
    });
  },

  // Heatmap (weekly)
  async fetchHeatmap(period = "30d") {
    return doFetch("/heatmap", {
      method: "POST",
      body: { period },
    });
  },

  // All members with stats
  async fetchAllMembers(period = "30d") {
    return doFetch("/all_members", {
      method: "POST",
      body: { period },
    });
  },

  // Badges batch: { member_ids: [id1, id2, ...] }
  async fetchBadgesBatch(memberIds = []) {
    return doFetch("/badges_batch", {
      method: "POST",
      body: { member_ids: memberIds },
    });
  },

  // Achievements (guild-wide)
  async fetchAchievements() {
    return doFetch("/achievements", {
      method: "POST",
      body: {},
    });
  },

  // Community health
  async fetchCommunityHealth(period = "30d") {
    return doFetch("/community_health", {
      method: "POST",
      body: { period },
    });
  },

  // Member details (uses member proxy handler which resolves guild via fixed_guild_id or path)
  // Provide guildId if you want to target specific guild; otherwise pass null/undefined to use fixed_guild_id.
  async fetchMember(guildIdOrNull, memberId, period = "30d") {
    // If guildIdOrNull provided, use path with guild id, else use generic member path (backend will resolve)
    const path = guildIdOrNull
      ? `/member/${guildIdOrNull}/${memberId}`
      : `/member/0/${memberId}`;
    // Note: backend _proxy_handle_member prefers path param, but if 0/invalid used it will fallback to fixed_guild_id.
    return doFetch(path, {
      method: "POST",
      body: { period },
    });
  },

  // Export CSV for a member — returns text/csv body
  async fetchExport(guildIdOrNull, memberId, period = "all") {
    const path = guildIdOrNull
      ? `/export/${guildIdOrNull}/${memberId}`
      : `/export/0/${memberId}`;
    // doFetch returns text for non-json responses
    return doFetch(path, {
      method: "POST",
      body: { period },
    });
  },

  // Single member badges
  async fetchBadges(guildIdOrNull, memberId) {
    const path = guildIdOrNull
      ? `/badges/${guildIdOrNull}/${memberId}`
      : `/badges/${0}/${memberId}`;
    return doFetch(path, { method: "POST", body: {} });
  },

  // Batch utilities for common flows
  async fetchTopAndMembers(period = "30d", metric = "time", limit = 10) {
    // parallel calls: top + all_members (useful for overview + streamer list)
    return Promise.all([
      this.fetchTop(period, metric, limit),
      this.fetchAllMembers(period),
    ]);
  },

  // Other analytical endpoints
  async fetchSchedulePredictor(memberId, period = "30d", guildIdOrNull) {
    const body = { member_id: memberId, period };
    if (guildIdOrNull) body.guild_id = guildIdOrNull;
    return doFetch("/schedule_predictor", { method: "POST", body });
  },

  async fetchAudienceOverlap(memberId, guildIdOrNull) {
    const body = { member_id: memberId };
    if (guildIdOrNull) body.guild_id = guildIdOrNull;
    return doFetch("/audience_overlap", { method: "POST", body });
  },

  async fetchCollaborationMatcher(memberId, guildIdOrNull) {
    const body = { member_id: memberId };
    if (guildIdOrNull) body.guild_id = guildIdOrNull;
    return doFetch("/collaboration_matcher", { method: "POST", body });
  },

  // Low-level helper for when components need custom calls
  postRaw(path, body = {}) {
    return doFetch(path.startsWith("/") ? path : "/" + path, {
      method: "POST",
      body,
    });
  },

  // Optional: change API prefix at runtime if you ever move proxy path
  _setApiPrefix(newPrefix) {
    // internal helper for tests or advanced use
    // Note: not exported as top-level change; mutate API_BASE if needed (not recommended)
    console.warn(
      "Changing API prefix at runtime is unsupported in the bundled client. Preferred: update src/utils/api.js and rebuild."
    );
  },
};
