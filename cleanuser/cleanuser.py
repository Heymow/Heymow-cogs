# cleanuser/cleanuser.py
from __future__ import annotations
import asyncio
from typing import Optional, Union
import discord
from redbot.core import commands, checks
from redbot.core.bot import Red

ChannelLike = Union[discord.TextChannel, discord.Thread, discord.ForumChannel]


class CleanUser(commands.Cog):
    """
    Delete messages from a user (even if they already left the server).
    Can target a specific channel or the entire server.
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot

    @commands.guild_only()
    @checks.admin_or_permissions(manage_messages=True)
    @commands.command(name="purgeuser", aliases=["cleanuser", "cleanupuser"])
    async def purge_user_command(
        self,
        ctx: commands.Context,
        user_id: int,
        channel: Optional[discord.TextChannel | discord.Thread | discord.ForumChannel] = None,
        *,
        flags: Optional[str] = None,
    ):
        """
        Delete messages from a given user by ID.

        **Usage**
        ```
        [p]purgeuser <user_id>                → current channel
        [p]purgeuser <user_id> #channel       → specific channel
        [p]purgeuser <user_id> --all          → all accessible text channels
        [p]purgeuser <user_id> #channel --dry-run  → simulate deletion in one channel
        [p]purgeuser <user_id> --all --dry-run     → simulate deletion server-wide
        ```

        **Notes**
        - Works even if the user has already left the server.
        - Deletes messages individually (bypasses 14-day bulk delete limit).
        - The bot needs *Read Message History* and *Manage Messages* permissions.
        """
        flags = (flags or "").lower()
        scan_all = "--all" in flags
        dry_run = "--dry-run" in flags or "--dryrun" in flags

        guild = ctx.guild
        if not guild:
            await ctx.send("❌ This command can only be used in a server.")
            return

        # Determine which channels to scan
        if scan_all:
            channels: list[ChannelLike] = [
                ch for ch in guild.channels if isinstance(ch, (discord.TextChannel, discord.ForumChannel))
            ]
            for ch in guild.text_channels:
                channels.extend(ch.threads)
        elif channel:
            channels = [channel]
        else:
            if isinstance(ctx.channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
                channels = [ctx.channel]
            else:
                await ctx.send("❌ Unsupported channel type.")
                return

        # Check permissions
        def can_manage(ch: ChannelLike) -> bool:
            perms = ch.permissions_for(guild.me)
            return perms.read_messages and perms.read_message_history and perms.manage_messages

        invalid_channels = [ch for ch in channels if not can_manage(ch)]
        if invalid_channels:
            await ctx.send(
                f"⚠️ Missing permissions in {len(invalid_channels)} channel(s). They will be skipped."
            )
            channels = [ch for ch in channels if can_manage(ch)]

        if not channels:
            await ctx.send("❌ No valid channels to scan.")
            return

        # Confirmation
        scope = f"the entire server ({len(channels)} channels)" if scan_all else f"#{channels[0].name}"
        note = "Dry-run mode (no deletions)." if dry_run else "Messages will be **permanently deleted**."

        await ctx.send(
            f"You are about to purge messages from user **{user_id}** in **{scope}**.\n"
            f"{note}\nType `yes` to confirm (30s timeout)…"
        )

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            resp = await ctx.bot.wait_for("message", timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Cancelled (no confirmation).")
            return

        if resp.content.strip().lower() not in {"yes", "y"}:
            await ctx.send("❌ Cancelled.")
            return

        progress = await ctx.send("🔎 Scanning messages… please wait.")

        total_deleted = 0

        async def throttled_delete(msg: discord.Message):
            nonlocal total_deleted
            try:
                await msg.delete()
                total_deleted += 1
            except (discord.NotFound, discord.Forbidden):
                pass
            except discord.HTTPException:
                await asyncio.sleep(1.0)

        for ch in channels:
            await self._scan_channel(ch, user_id, dry_run, throttled_delete, progress)
            await asyncio.sleep(0.2)

        await progress.edit(
            content=f"✅ Done. {'Simulated' if dry_run else 'Deleted'} messages: **{total_deleted}**."
        )

    async def _scan_channel(
        self,
        ch: ChannelLike,
        user_id: int,
        dry_run: bool,
        delete_fn,
        progress_msg: discord.Message,
    ):
        found = 0
        deleted = 0

        try:
            async for msg in ch.history(limit=None, oldest_first=True):
                if msg.author and msg.author.id == user_id:
                    found += 1
                    if not dry_run:
                        await delete_fn(msg)
                        deleted += 1

                if found % 50 == 0:
                    await progress_msg.edit(
                        content=f"🔎 #{ch.name}: found {found}, "
                                f"{'deleted' if not dry_run else 'simulated'} {deleted}…"
                    )
        except discord.Forbidden:
            await progress_msg.edit(content=f"⚠️ No access to #{ch.name}.")
        except discord.HTTPException:
            await asyncio.sleep(1.0)

        await progress_msg.edit(
            content=f"✅ #{ch.name}: found {found}, "
                    f"{'deleted' if not dry_run else 'simulated'} {deleted}."
        )


async def setup(bot: Red):
    await bot.add_cog(CleanUser(bot))
