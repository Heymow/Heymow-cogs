import re
import time
import discord
import aiohttp
from redbot.core import commands, Config

class ChannelFusion(commands.Cog):
    """Copy messages from one or more channels into a target channel using webhooks."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fusechannels")
    @commands.admin()
    async def fuse_channels(self, ctx, target: discord.TextChannel, *sources: discord.TextChannel):
        """Fuse multiple channels into a target channel (with webhooks), sorted by global message date."""
        if not sources:
            await ctx.send("Please specify at least one source channel.")
            return

        await ctx.send(f"Collecting messages from {len(sources)} channels...")

        all_messages = []

        for source in sources:
            try:
                messages = [msg async for msg in source.history(limit=None, oldest_first=True)]
                all_messages.extend(messages)
            except Exception as e:
                await ctx.send(f"Failed to read from {source.mention}: {e}")

        # Global sort by message creation date
        all_messages.sort(key=lambda m: m.created_at)

        await ctx.send(f"Sending {len(all_messages)} messages to {target.mention}...")

        webhook = await self._get_or_create_webhook(target)

        for msg in all_messages:
            if msg.type != discord.MessageType.default:
                continue

            if msg.content.strip() == "" and not msg.attachments:
                continue

            if msg.author.bot:
                continue

            content = msg.content
            files = []

            try:
                for attachment in msg.attachments:
                    file = await attachment.to_file()
                    files.append(file)

                kwargs = {
                    "content": content,
                    "username": msg.author.display_name,
                    "avatar_url": msg.author.display_avatar.url,
                    "allowed_mentions": discord.AllowedMentions.none(),
                }

                if files:
                    kwargs["files"] = files

                await webhook.send(**kwargs)

            except Exception as e:
                await ctx.send(f"Error sending a message from {msg.author.display_name}: {e}")

        await ctx.send("✅ Fusion complete, messages sent in chronological order!")
