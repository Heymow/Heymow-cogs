#version 1.0
#
#Developed by: You
#
import asyncio
from redbot.core import commands, Config, app_commands
from redbot.core.bot import Red
import re
import json
import discord
import os
import pathlib
from datetime import datetime, timedelta

class Extractsongs(commands.Cog):
    song_id = ""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=15703146128)
        default_guild = {
            "listening_channels": [],
            "output_channel": None,  # Channel to send individual songs
            "daily_channel": None,   # Channel to send daily summary
            "notification_channel": None,  # Channel for notification messages
            "saved_songs": {},       # For storing song information
            "last_daily_timestamp": None  # To track the last daily execution
        }
        self.config.register_guild(**default_guild)
        self.listening_channels = {}
        self.output_channels = {}
        self.daily_channels = {}
        self.notification_channels = {}
        
        # Create a folder to save data locally - use data_path for Railway compatibility
        self.data_path = pathlib.Path("./song_cache")
        self.data_path.mkdir(exist_ok=True)
        
        # Start daily summary task
        self.daily_task = self.bot.loop.create_task(self.daily_summary_loop())

    def cog_unload(self):
        """Clean up ongoing tasks when the cog is unloaded."""
        self.daily_task.cancel()

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def clear_data(self, ctx):
        """Clears all channel data for the current guild."""
        await self.config.guild(ctx.guild).clear()
        guild_id = ctx.guild.id
        if guild_id in self.listening_channels:
            del self.listening_channels[guild_id]
        if guild_id in self.output_channels:
            del self.output_channels[guild_id]
        if guild_id in self.daily_channels:
            del self.daily_channels[guild_id]
        if guild_id in self.notification_channels:
            del self.notification_channels[guild_id]
        await self.initialize(ctx.guild)
        await ctx.send(f"Data cleared for guild: {ctx.guild.name}")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def view_data(self, ctx):
        """Shows stored channel data, formatted for readability"""
        guild_data = await self.config.guild(ctx.guild).all()
        
        # Create a formatted embed instead of raw text
        embed = discord.Embed(
            title="📊 Songs Data Overview",
            color=discord.Color.blue()
        )
        
        # Listening channels
        listening_channels = guild_data.get("listening_channels", [])
        if listening_channels:
            channels_text = ', '.join([f"<#{ch_id}>" for ch_id in listening_channels])
            embed.add_field(name="🎧 Listening Channels", value=channels_text, inline=False)
        else:
            embed.add_field(name="🎧 Listening Channels", value="None", inline=False)
    
        # Output channel
        output_channel = guild_data.get("output_channel")
        embed.add_field(
            name="📤 Output Channel", 
            value=f"<#{output_channel}>" if output_channel else "None", 
            inline=True
        )
        
        # Daily channel
        daily_channel = guild_data.get("daily_channel")
        embed.add_field(
            name="📊 Daily Channel", 
            value=f"<#{daily_channel}>" if daily_channel else "None", 
            inline=True
        )
        
        # Notification channel
        notification_channel = guild_data.get("notification_channel")
        embed.add_field(
            name="🔔 Notification Channel", 
            value=f"<#{notification_channel}>" if notification_channel else "None", 
            inline=True
        )
        
        # Songs count
        saved_songs = guild_data.get("saved_songs", {})
        embed.add_field(
            name="🎵 Saved Songs", 
            value=f"{len(saved_songs)} songs", 
            inline=True
        )
        
        # Last daily timestamp
        last_daily = guild_data.get("last_daily_timestamp")
        embed.add_field(
            name="⏰ Last Daily Summary", 
            value=last_daily if last_daily else "Never", 
            inline=True
        )
        
        await ctx.send(embed=embed)
        
        # If there are songs, show them in a separate message
        if saved_songs:
            songs_text = "**Recent Songs:**\n"
            for i, (song_id, data) in enumerate(list(saved_songs.items())[:10]):  # Show only first 10
                songs_text += f"`{song_id}` - <@{data.get('author_id', 'Unknown')}>\n"
            
            if len(saved_songs) > 10:
                songs_text += f"... and {len(saved_songs) - 10} more songs"
            
            await ctx.send(songs_text)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def add_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Add a channel to the listening list."""
        if not channel:
            await ctx.send("Please provide a valid channel.")
            return

        guild = ctx.guild
        listening_channels = await self.config.guild(guild).listening_channels()

        if channel.id not in listening_channels:
            listening_channels.append(channel.id)
            await self.config.guild(guild).listening_channels.set(listening_channels)
            await ctx.send(f"Added {channel.mention} to the listening channels.")
            await self.initialize(ctx.guild)
        else:
            channels_list = ', '.join([f"<#{ch_id}>" for ch_id in listening_channels])
            await ctx.send(
                f"{channel.mention} is already in the listening channels. "
                f"Current listening channels: {channels_list}"
            )

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def remove_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Remove a channel from the listening list."""
        guild = ctx.guild
        listening_channels = await self.config.guild(guild).listening_channels()

        if channel.id in listening_channels:
            listening_channels.remove(channel.id)
            await self.config.guild(guild).listening_channels.set(listening_channels)
            await ctx.send(f"Removed {channel.mention} from the listening channels.")
            await self.initialize(ctx.guild)
        else:
            await ctx.send(f"{channel.mention} is not in the listening channels.")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def list_channels(self, ctx: commands.Context):
        """List all channels in the listening list."""
        guild = ctx.guild
        listening_channels = await self.config.guild(guild).listening_channels()

        if listening_channels:
            channels_list = ', '.join([f"<#{ch_id}>" for ch_id in listening_channels])
            await ctx.send(f"Listening channels: {channels_list}")
        else:
            await ctx.send("No listening channels are currently set.")
            
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def set_output(self, ctx, channel: discord.TextChannel):
        """Set the channel where individual songs will be sent."""
        await self.config.guild(ctx.guild).output_channel.set(channel.id)
        self.output_channels[ctx.guild.id] = channel.id
        await ctx.send(f"Output channel set to {channel.mention}")
        
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def set_daily(self, ctx, channel: discord.TextChannel):
        """Set the channel where daily song summaries will be sent."""
        await self.config.guild(ctx.guild).daily_channel.set(channel.id)
        self.daily_channels[ctx.guild.id] = channel.id
        await ctx.send(f"Daily summary channel set to {channel.mention}")
        
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def set_notification(self, ctx, channel: discord.TextChannel):
        """Set the channel where notification messages will be sent."""
        await self.config.guild(ctx.guild).notification_channel.set(channel.id)
        self.notification_channels[ctx.guild.id] = channel.id
        await ctx.send(f"Notification channel set to {channel.mention}")
        
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def send_summary_now(self, ctx):
        """Force send a summary of songs collected now."""
        await ctx.send("Generating song summary...")
        await self.send_daily_summary(ctx.guild)
        await ctx.send("Summary sent!")

    async def initialize(self, guild: discord.Guild):
        """Loads saved data from the configuration."""
        listening_channels = await self.config.guild(guild).listening_channels()
        self.listening_channels[guild.id] = listening_channels
        
        output_channel = await self.config.guild(guild).output_channel()
        self.output_channels[guild.id] = output_channel
        
        daily_channel = await self.config.guild(guild).daily_channel()
        self.daily_channels[guild.id] = daily_channel
        
        notification_channel = await self.config.guild(guild).notification_channel()
        self.notification_channels[guild.id] = notification_channel

        print(f"Initialized for guild: {guild.name} ({guild.id})")
        print(f"Listening Channels: {listening_channels}")
        print(f"Output Channel: {output_channel}")
        print(f"Daily Summary Channel: {daily_channel}")
        print(f"Notification Channel: {notification_channel}")

    async def cog_load(self):
        for guild in self.bot.guilds:
            await self.initialize(guild)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
    
        guild_id = message.guild.id
        listening_channel_ids = self.listening_channels.get(guild_id, {})
        
        if not listening_channel_ids:
            return
            
        if message.channel.id not in listening_channel_ids:
            return
            
        if "https://suno.com/" in message.content:
            pattern = r"https://suno\.com/(?:song/([a-f0-9\-]+)|s/([a-zA-Z0-9]+))"
            matches = re.findall(pattern, message.content)
            
            if matches:
                for match in matches:
                    # match will be a tuple with (id_format1, id_format2)
                    # Only one of them will be non-empty
                    song_id = match[0] if match[0] else match[1]
                    if song_id:
                        print(f"Found Song ID: {song_id}")
                        
                        # Determine the correct URL format based on which group matched
                        if match[0]:  # Long format from song/ URL
                            correct_song_url = f"https://suno.com/song/{song_id}"
                        elif match[1]:  # Short format from s/ URL
                            correct_song_url = f"https://suno.com/s/{song_id}"
                        else:
                            # Fallback (should not happen)
                            correct_song_url = f"https://suno.com/song/{song_id}"
                        
                        print(f"Detected URL format: {correct_song_url}")
                        
                        success = await self.save_song_locally(message, message.channel, message.guild, song_id, correct_song_url)
                        
                        if success:
                            # Send to output channel if defined
                            output_channel_id = self.output_channels.get(guild_id)
                            if output_channel_id:
                                output_channel = self.bot.get_channel(output_channel_id)
                                if output_channel:
                                    embed = discord.Embed(
                                        title="New Suno song saved",
                                        description=f"ID: {song_id}\nShared by: {message.author.mention}\n[Song link]({correct_song_url})",
                                        color=discord.Color.blue()
                                    )
                                    await output_channel.send(embed=embed)
                        else:
                            # Song already exists - optionally send a different message or just skip silently
                            print(f"Song {song_id} was already saved, skipping notification")

    async def save_song_locally(self, message, channel, guild, song_id, song_url=None):
        """Save the song locally instead of sending to an API."""
        try:
            from datetime import timezone
            
            print(f"save_song_locally called with song_url: {song_url}")
            
            # Check if song already exists
            saved_songs = await self.config.guild(guild).saved_songs()
            if song_id in saved_songs:
                print(f"Song {song_id} already exists, skipping save")
                return False
            
            # Use the provided song_url or determine it based on the song_id
            if not song_url:
                if len(song_id) == 8 and song_id.isalnum():  # Short format like "abc12345"
                    song_url = f"https://suno.com/s/{song_id}"
                elif "-" in song_id:  # Long format like "abc12345-6789-def0-..."
                    song_url = f"https://suno.com/song/{song_id}"
                else:
                    # Default to song format if unsure
                    song_url = f"https://suno.com/song/{song_id}"
        
            print(f"Final song_url used: {song_url}")
            
            # Create a dictionary of song data
            song_data = {
                "song_id": song_id,
                "song_url": song_url,
                "server_name": guild.name,
                "channel_name": channel.name,
                "message_id": message.id,
                "posted_time": message.created_at.replace(tzinfo=timezone.utc).isoformat(),
                "channel_id": channel.id,
                "author_id": message.author.id,
                "author_name": str(message.author)
            }
            
            # Save in Red config
            saved_songs[song_id] = song_data
            await self.config.guild(guild).saved_songs.set(saved_songs)
            
            # Also save locally in a JSON file - using Path for cross-platform compatibility
            file_path = self.data_path / f"{song_id}.json"
            with open(file_path, "w") as f:
                json.dump(song_data, f, indent=2)
                
            print(f"Song {song_id} saved successfully with URL: {song_url}")
            return True
            
        except Exception as e:
            print(f"Error saving song: {str(e)}")
            return False
            
    async def daily_summary_loop(self):
        """Loop that runs continuously to send daily summary."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.now()
            
            # Check and send summary for each guild
            for guild in self.bot.guilds:
                try:
                    last_timestamp = await self.config.guild(guild).last_daily_timestamp()
                    
                    # If never executed or executed more than 24 hours ago
                    if (last_timestamp is None or 
                        (now - datetime.fromisoformat(last_timestamp)).total_seconds() >= 86400):
                        await self.send_daily_summary(guild)
                        await self.config.guild(guild).last_daily_timestamp.set(now.isoformat())
                except Exception as e:
                    print(f"Error in daily summary for server {guild.name}: {str(e)}")
            
            # Wait for next check (every hour)
            await asyncio.sleep(3600)
    
    async def send_daily_summary(self, guild):
        """Send a summary of songs collected in multiple messages if needed."""
        daily_channel_id = self.daily_channels.get(guild.id)
        if not daily_channel_id:
            return
            
        daily_channel = self.bot.get_channel(daily_channel_id)
        if not daily_channel:
            return
            
        # Get all saved songs
        saved_songs = await self.config.guild(guild).saved_songs()
        if not saved_songs:
            return
            
        # Filter songs from the last 24 hours - fix datetime comparison
        from datetime import timezone
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        recent_songs = {}
        
        for song_id, data in saved_songs.items():
            try:
                posted_time = datetime.fromisoformat(data["posted_time"])
                # If posted_time is naive, make it UTC aware
                if posted_time.tzinfo is None:
                    posted_time = posted_time.replace(tzinfo=timezone.utc)
                
                if posted_time >= yesterday:
                    recent_songs[song_id] = data
            except (KeyError, ValueError) as e:
                print(f"Error parsing posted_time for song {song_id}: {str(e)}")
                continue
        
        if not recent_songs:
            # Send to notification channel instead of daily channel if no songs
            notification_channel_id = self.notification_channels.get(guild.id)
            if notification_channel_id:
                notification_channel = self.bot.get_channel(notification_channel_id)
                if notification_channel:
                    await notification_channel.send("No new Suno songs have been shared in the last 24 hours.")
            else:
                await daily_channel.send("No new Suno songs have been shared in the last 24 hours.")
            return
            
        # Convert to list for easier slicing
        recent_songs_list = list(recent_songs.items())
        total_songs = len(recent_songs_list)
        
        # Send songs in batches of 25 maximum
        for batch_start in range(0, total_songs, 25):
            batch_end = min(batch_start + 25, total_songs)
            current_batch = recent_songs_list[batch_start:batch_end]
            
            # Create an embed for this batch
            batch_number = batch_start // 25 + 1
            total_batches = (total_songs + 24) // 25  # Round up
            
            embed = discord.Embed(
                title=f"📊 Suno Songs Summary ({batch_number}/{total_batches})",
                description=f"**{total_songs} songs** shared in the last 24 hours",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            
            # Add songs from this batch to the embed
            for i, (song_id, data) in enumerate(current_batch):
                song_number = batch_start + i + 1
                # Use the stored URL format instead of forcing song format
                song_url = data.get("song_url", f"https://suno.com/song/{song_id}")
                
                embed.add_field(
                    name=f"🎵 Song {song_number}",
                    value=f"[Listen on Suno]({song_url})\n"
                          f"Shared by: <@{data['author_id']}>\n"
                          f"In: <#{data['channel_id']}>",
                    inline=True
                )
                
            embed.set_footer(text=f"Server: {guild.name} • Page {batch_number}/{total_batches}")
            
            # Send the summary for this batch
            await daily_channel.send(embed=embed)
    
        # Delete all processed songs
        for song_id in recent_songs.keys():
            if song_id in saved_songs:
                del saved_songs[song_id]
                
                # Also delete local JSON files
                file_path = self.data_path / f"{song_id}.json"
                if file_path.exists():
                    try:
                        file_path.unlink()  # Cross-platform way to delete a file
                        print(f"Deleted local file for song {song_id}")
                    except Exception as e:
                        print(f"Error deleting file {file_path}: {str(e)}")
        
        # Update config with remaining songs (if any)
        await self.config.guild(guild).saved_songs.set(saved_songs)
        print(f"Removed {total_songs} songs from memory after daily summary for server {guild.name}")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def list_config(self, ctx: commands.Context):
        """List all configured channels."""
        guild = ctx.guild
        listening_channels = await self.config.guild(guild).listening_channels()
        output_channel = await self.config.guild(guild).output_channel()
        daily_channel = await self.config.guild(guild).daily_channel()
        notification_channel = await self.config.guild(guild).notification_channel()
        
        embed = discord.Embed(
            title="📋 Current Configuration",
            color=discord.Color.blue()
        )
        
        # Listening channels
        if listening_channels:
            channels_list = ', '.join([f"<#{ch_id}>" for ch_id in listening_channels])
            embed.add_field(name="🎧 Listening Channels", value=channels_list, inline=False)
        else:
            embed.add_field(name="🎧 Listening Channels", value="None configured", inline=False)
        
        # Output channel
        if output_channel:
            embed.add_field(name="📤 Output Channel", value=f"<#{output_channel}>", inline=True)
        else:
            embed.add_field(name="📤 Output Channel", value="None configured", inline=True)
        
        # Daily summary channel
        if daily_channel:
            embed.add_field(name="📊 Daily Summary Channel", value=f"<#{daily_channel}>", inline=True)
        else:
            embed.add_field(name="📊 Daily Summary Channel", value="None configured", inline=True)
        
        # Notification channel
        if notification_channel:
            embed.add_field(name="🔔 Notification Channel", value=f"<#{notification_channel}>", inline=True)
        else:
            embed.add_field(name="🔔 Notification Channel", value="None configured", inline=True)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Extractsongs(bot))

