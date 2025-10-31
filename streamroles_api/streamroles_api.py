"""
Minimal API endpoints (aiohttp) integrated into the StreamRoles cog,
plus a tiny static frontend serving endpoint.

Endpoints (require header Authorization: Bearer <token>):
- GET /api/guild/{guild_id}/member/{member_id}?period=7d|30d|all
  -> JSON: sessions + aggregates for the member
- GET /api/guild/{guild_id}/top?metric=time|count&period=7d|30d|all&limit=10
  -> JSON: top list (member id, display_name, value)
- GET /api/guild/{guild_id}/export/member/{member_id}?period=7d|30d|all
  -> CSV file download (same columns as cog export)

Static frontend:
- GET /dashboard -> serves a small HTML/JS dashboard (calls the API)

Security:
- A guild-level API token is used to authenticate requests. Set it with
  the command: streamrole setapitoken <token>
- The server listens on host/port configured in the cog (defaults: 127.0.0.1:8080).
  Exposing it publicly without reverse proxy & TLS is not recommended.

Notes:
- This file assumes the StreamRoles cog from earlier is loaded and exposes the
  helpers: _get_member_sessions, _format_seconds, and config structure used.
- Keep this implementation minimal and lightweight: no DB, no heavy caching.
"""
import asyncio
import csv
import io
import json
import logging
import time
from typing import Optional

import aiohttp
from aiohttp import web
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red

log = logging.getLogger("red.streamroles.api")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

UNIQUE_API_CONF = 0x923476AF  # reuse or separate identifier as desired


class StreamRolesAPI(commands.Cog):
    """Minimal HTTP API + frontend for StreamRoles stats."""

    def __init__(self, bot: Red, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        super().__init__()
        self.bot: Red = bot
        self.host = host
        self.port = port
        # store per-guild api token in same config used by StreamRoles cog (guild.stats_* exists)
        # fallback to a cog-level attribute for quick setup
        self.conf = Config.get_conf(self, force_registration=True, identifier=UNIQUE_API_CONF)
        self.conf.register_guild(api_token=None)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._app: Optional[web.Application] = None

    # ---------- Commands to manage API ----------
    @commands.is_owner()
    @commands.group()
    async def streamrole(self, ctx):
        """Compatibility group: subcommands provided below for admin usage."""
        # This mirrors group in main cog; used only to attach subcommands here.
        pass

    @streamrole.command()
    async def setapitoken(self, ctx: commands.Context, token: Optional[str]):
        """
        Set or clear the API token for this guild.

        Usage:
        - streamrole setapitoken <token>   -> sets the token (must be provided in API calls)
        - streamrole setapitoken none      -> clears the token (disables auth requirement)
        Note: Only guild admins / owner should set tokens, and protect them.
        """
        if token is None or token.lower() == "none":
            await self.conf.guild(ctx.guild).api_token.set(None)
            await ctx.send("Cleared API token for this guild. The API will not accept requests for this guild until a token is set.")
            return
        await self.conf.guild(ctx.guild).api_token.set(token)
        await ctx.send("API token stored for this guild. Keep it secret.")

    # ---------- Startup / teardown ----------
    async def cog_load(self) -> None:
        """Start aiohttp app when cog is loaded."""
        await self._start_app()

    async def cog_unload(self) -> None:
        """Stop aiohttp app when cog is unloaded."""
        await self._stop_app()

    async def _start_app(self):
        if self._runner:
            return
        app = web.Application()
        app.add_routes(
            [
                web.get("/api/guild/{guild_id}/member/{member_id}", self._handle_member_stats),
                web.get("/api/guild/{guild_id}/top", self._handle_top),
                web.get("/api/guild/{guild_id}/export/member/{member_id}", self._handle_export_csv),
                web.get("/dashboard", self._handle_dashboard),
                web.get("/", self._handle_index),
            ]
        )
        # small static resources could be added here; for brevity dashboard returns single HTML
        runner = web.AppRunner(app)
        # await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self._runner = runner
        self._site = site
        self._app = app
        log.info("StreamRoles API started on http://%s:%s", self.host, self.port)

    async def _stop_app(self):
        if self._runner:
            try:
                await self._runner.cleanup()
                log.info("StreamRoles API stopped")
            except Exception:
                log.exception("Error stopping StreamRoles API")
            finally:
                self._runner = None
                self._site = None
                self._app = None

    # ---------- Utilities ----------
    async def _authorize(self, request: web.Request, guild_id: int) -> bool:
        """Simple header token auth. Returns True if authorized."""
        # If guild has no token configured, deny (safer). Admin can clear token to disable auth.
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return False
        token = await self.conf.guild(guild).api_token()
        if not token:
            # if no token set, we consider the API disabled for this guild
            return False
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            provided = header[len("Bearer ") :].strip()
            return provided == token
        return False

    def _parse_period(self, period: str):
        """Return cutoff epoch for period or 0 for all."""
        now = int(time.time())
        if not period or period == "all":
            return 0
        if period.endswith("d"):
            try:
                days = int(period[:-1])
            except Exception:
                return None
            return now - int(days) * 86400
        return None

    # ---------- Handlers ----------
    async def _handle_index(self, request: web.Request):
        return web.Response(text="StreamRoles API is running.", content_type="text/plain")

    async def _handle_dashboard(self, request: web.Request):
        """Serve embedded frontend HTML/JS (minimal)."""
        # Very small single-page app that prompts for token and guild id
        html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>StreamRoles Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    input, select { margin: 5px; }
  </style>
</head>
<body>
  <h2>StreamRoles - Minimal Dashboard</h2>
  <div>
    <label>Guild ID: <input id="guild" /></label>
    <label>Token: <input id="token" /></label>
    <label>Period:
      <select id="period"><option value="7d">7d</option><option value="30d" selected>30d</option><option value="all">all</option></select>
    </label>
    <button id="fetchTop">Fetch Top by Time</button>
  </div>
  <canvas id="topChart" width="800" height="300"></canvas>
  <script>
    async function fetchTop() {
      const guild = document.getElementById('guild').value;
      const token = document.getElementById('token').value;
      const period = document.getElementById('period').value;
      if(!guild || !token) { alert('Guild and token required'); return; }
      const url = `/api/guild/${guild}/top?metric=time&period=${period}&limit=10`;
      const resp = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token }});
      if(!resp.ok) { alert('Error: ' + resp.status); return; }
      const data = await resp.json();
      const labels = data.map(x => x.display_name);
      const values = data.map(x => x.value_hours);
      const ctx = document.getElementById('topChart').getContext('2d');
      if(window._topChart) window._topChart.destroy();
      window._topChart = new Chart(ctx, {
        type: 'bar',
        data: { labels: labels, datasets: [{ label: 'Hours', data: values, backgroundColor: 'rgba(54,162,235,0.6)' }]},
        options: { responsive: true, scales: { y: { beginAtZero: true } } }
      });
    }
    document.getElementById('fetchTop').onclick = fetchTop;
  </script>
</body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    async def _handle_member_stats(self, request: web.Request):
        guild_id = request.match_info.get("guild_id")
        member_id = request.match_info.get("member_id")
        if not await self._authorize(request, int(guild_id)):
            return web.Response(status=401, text="Unauthorized")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return web.Response(status=404, text="Guild not found")
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")
        period = request.query.get("period", "30d")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        # find the StreamRoles cog instance that has _get_member_sessions helper
        sr = self._find_streamroles_cog()
        if sr is None:
            return web.Response(status=500, text="StreamRoles cog not loaded")
        sessions = await sr._get_member_sessions(member, guild)
        if cutoff:
            sessions = [s for s in sessions if s.get("start", 0) >= cutoff]
        total_streams = len(sessions)
        total_time = sum(s.get("duration", 0) for s in sessions)
        avg_duration = total_time / total_streams if total_streams else 0
        response = {
            "member_id": member.id,
            "display_name": member.display_name,
            "period": period,
            "total_streams": total_streams,
            "total_time_seconds": total_time,
            "avg_duration_seconds": avg_duration,
            "sessions": sessions,
        }
        return web.json_response(response)

    async def _handle_top(self, request: web.Request):
        guild_id = request.match_info.get("guild_id")
        if not await self._authorize(request, int(guild_id)):
            return web.Response(status=401, text="Unauthorized")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return web.Response(status=404, text="Guild not found")
        metric = request.query.get("metric", "time")
        period = request.query.get("period", "7d")
        limit = int(request.query.get("limit", "10"))
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        sr = self._find_streamroles_cog()
        if sr is None:
            return web.Response(status=500, text="StreamRoles cog not loaded")
        results = []
        for member in guild.members:
            sessions = await sr._get_member_sessions(member, guild)
            if cutoff:
                filtered = [s for s in sessions if s.get("start", 0) >= cutoff]
            else:
                filtered = sessions
            if not filtered:
                continue
            if metric == "time":
                val_sec = sum(s.get("duration", 0) for s in filtered)
            else:
                val_sec = len(filtered)
            results.append({"member_id": member.id, "display_name": member.display_name, "value": val_sec})
        results.sort(key=lambda x: x["value"], reverse=True)
        top = results[:limit]
        # augment for convenience: include hours for time metric
        for r in top:
            r["value_hours"] = round(r["value"] / 3600, 2) if metric == "time" else r["value"]
        return web.json_response(top)

    async def _handle_export_csv(self, request: web.Request):
        guild_id = request.match_info.get("guild_id")
        member_id = request.match_info.get("member_id")
        if not await self._authorize(request, int(guild_id)):
            return web.Response(status=401, text="Unauthorized")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return web.Response(status=404, text="Guild not found")
        member = guild.get_member(int(member_id))
        if not member:
            return web.Response(status=404, text="Member not found")
        period = request.query.get("period", "all")
        cutoff = self._parse_period(period)
        if cutoff is None:
            return web.Response(status=400, text="Invalid period")
        sr = self._find_streamroles_cog()
        if sr is None:
            return web.Response(status=500, text="StreamRoles cog not loaded")
        sessions = await sr._get_member_sessions(member, guild)
        if cutoff:
            sessions = [s for s in sessions if s.get("start", 0) >= cutoff]
        # build CSV in-memory
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["start_iso", "end_iso", "start_epoch", "end_epoch", "duration_seconds", "game", "platform", "url"])
        for s in sessions:
            start = s.get("start")
            end = s.get("end")
            writer.writerow([
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)) if start else "",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end)) if end else "",
                start or "",
                end or "",
                s.get("duration", ""),
                s.get("game", "") or "",
                s.get("platform", "") or "",
                s.get("url", "") or "",
            ])
        data = buf.getvalue().encode("utf-8")
        return web.Response(body=data, headers={
            "Content-Type": "text/csv",
            "Content-Disposition": f'attachment; filename="{member.display_name}-stream-stats-{period}.csv"'
        })

    def _find_streamroles_cog(self):
        """Find the loaded StreamRoles cog instance in the bot that provides helpers."""
        # look for cog with attribute _get_member_sessions
        for cog in self.bot.cogs.values():
            if hasattr(cog, "_get_member_sessions"):
                return cog
        return None