"""Twitch channel watching functionality for StreamRoles.

This module handles watching Discord channels for Twitch links and tracking Twitch channels.
"""
import logging
import re
from typing import List, Optional, Set

import discord

log = logging.getLogger("red.streamroles.twitch_watcher")


class TwitchWatcher:
    """Handles Twitch channel link detection and tracking."""
    
    # Regex patterns for detecting Twitch links
    TWITCH_URL_PATTERNS = [
        re.compile(r'(?:https?://)?(?:www\.)?twitch\.tv/([a-zA-Z0-9_]{4,25})(?:/|$|\s)', re.IGNORECASE),
        re.compile(r'(?:https?://)?(?:m\.)?twitch\.tv/([a-zA-Z0-9_]{4,25})(?:/|$|\s)', re.IGNORECASE),
    ]
    
    def __init__(self, config):
        """Initialize the Twitch watcher.
        
        Args:
            config: Red Config instance for storing data
        """
        self.config = config
    
    async def initialize_guild_config(self, guild: discord.Guild):
        """Initialize guild-specific configuration.
        
        Args:
            guild: The Discord guild to initialize config for
        """
        # Ensure guild has the required config keys
        current = await self.config.guild(guild).all()
        if 'watched_channels' not in current:
            await self.config.guild(guild).watched_channels.set([])
        if 'tracked_twitch_channels' not in current:
            await self.config.guild(guild).tracked_twitch_channels.set([])
    
    def extract_twitch_username(self, text: str) -> Optional[str]:
        """Extract Twitch username from text.
        
        Args:
            text: Text to search for Twitch URLs
            
        Returns:
            Twitch username if found, None otherwise
        """
        for pattern in self.TWITCH_URL_PATTERNS:
            match = pattern.search(text)
            if match:
                username = match.group(1).lower()
                # Exclude common non-channel paths
                if username not in ['videos', 'directory', 'settings', 'subscriptions', 'inventory', 'messages', 'friends', 'prime']:
                    return username
        return None
    
    def extract_all_twitch_usernames(self, text: str) -> Set[str]:
        """Extract all Twitch usernames from text.
        
        Args:
            text: Text to search for Twitch URLs
            
        Returns:
            Set of unique Twitch usernames found
        """
        usernames = set()
        for pattern in self.TWITCH_URL_PATTERNS:
            for match in pattern.finditer(text):
                username = match.group(1).lower()
                # Exclude common non-channel paths
                if username not in ['videos', 'directory', 'settings', 'subscriptions', 'inventory', 'messages', 'friends', 'prime']:
                    usernames.add(username)
        return usernames
    
    async def is_channel_watched(self, guild: discord.Guild, channel_id: int) -> bool:
        """Check if a channel is being watched for Twitch links.
        
        Args:
            guild: Discord guild
            channel_id: Channel ID to check
            
        Returns:
            True if channel is watched, False otherwise
        """
        watched = await self.config.guild(guild).watched_channels()
        return channel_id in watched
    
    async def add_watched_channel(self, guild: discord.Guild, channel_id: int):
        """Add a channel to the watch list.
        
        Args:
            guild: Discord guild
            channel_id: Channel ID to watch
        """
        async with self.config.guild(guild).watched_channels() as watched:
            if channel_id not in watched:
                watched.append(channel_id)
                log.info(f"Started watching channel {channel_id} in guild {guild.id}")
    
    async def remove_watched_channel(self, guild: discord.Guild, channel_id: int):
        """Remove a channel from the watch list.
        
        Args:
            guild: Discord guild
            channel_id: Channel ID to stop watching
        """
        async with self.config.guild(guild).watched_channels() as watched:
            if channel_id in watched:
                watched.remove(channel_id)
                log.info(f"Stopped watching channel {channel_id} in guild {guild.id}")
    
    async def get_watched_channels(self, guild: discord.Guild) -> List[int]:
        """Get list of watched channel IDs.
        
        Args:
            guild: Discord guild
            
        Returns:
            List of watched channel IDs
        """
        return await self.config.guild(guild).watched_channels()
    
    async def is_twitch_channel_tracked(self, guild: discord.Guild, username: str) -> bool:
        """Check if a Twitch channel is already tracked.
        
        Args:
            guild: Discord guild
            username: Twitch username
            
        Returns:
            True if channel is tracked, False otherwise
        """
        tracked = await self.config.guild(guild).tracked_twitch_channels()
        return username.lower() in [t.lower() for t in tracked]
    
    async def add_twitch_channel(self, guild: discord.Guild, username: str):
        """Add a Twitch channel to tracking.
        
        Args:
            guild: Discord guild
            username: Twitch username to track
        """
        username_lower = username.lower()
        async with self.config.guild(guild).tracked_twitch_channels() as tracked:
            if username_lower not in [t.lower() for t in tracked]:
                tracked.append(username_lower)
                log.info(f"Started tracking Twitch channel {username_lower} in guild {guild.id}")
    
    async def remove_twitch_channel(self, guild: discord.Guild, username: str) -> bool:
        """Remove a Twitch channel from tracking.
        
        Args:
            guild: Discord guild
            username: Twitch username to remove
            
        Returns:
            True if channel was removed, False if not found
        """
        username_lower = username.lower()
        async with self.config.guild(guild).tracked_twitch_channels() as tracked:
            # Find and remove (case-insensitive)
            for i, channel in enumerate(tracked):
                if channel.lower() == username_lower:
                    tracked.pop(i)
                    log.info(f"Removed Twitch channel {username_lower} from guild {guild.id}")
                    return True
        return False
    
    async def get_tracked_twitch_channels(self, guild: discord.Guild) -> List[str]:
        """Get list of tracked Twitch channels.
        
        Args:
            guild: Discord guild
            
        Returns:
            List of tracked Twitch usernames
        """
        return await self.config.guild(guild).tracked_twitch_channels()
    
    async def clear_all_twitch_channels(self, guild: discord.Guild):
        """Clear all tracked Twitch channels.
        
        Args:
            guild: Discord guild
        """
        await self.config.guild(guild).tracked_twitch_channels.set([])
        log.info(f"Cleared all tracked Twitch channels in guild {guild.id}")
    
    async def process_message_for_twitch_links(self, message: discord.Message) -> List[str]:
        """Process a message for Twitch links and add new channels.
        
        Args:
            message: Discord message to process
            
        Returns:
            List of newly added Twitch usernames
        """
        if not message.guild:
            return []
        
        # Check if channel is watched
        if not await self.is_channel_watched(message.guild, message.channel.id):
            return []
        
        # Extract all Twitch usernames from message
        usernames = self.extract_all_twitch_usernames(message.content)
        
        newly_added = []
        for username in usernames:
            # Check if already tracked
            if not await self.is_twitch_channel_tracked(message.guild, username):
                await self.add_twitch_channel(message.guild, username)
                newly_added.append(username)
                log.debug(f"Auto-added Twitch channel {username} from message in guild {message.guild.id}")
        
        return newly_added
    
    async def scan_channel_history(
        self, 
        channel: discord.TextChannel, 
        limit: int = 100
    ) -> tuple[int, List[str]]:
        """Scan channel history for Twitch links.
        
        Args:
            channel: Discord text channel to scan
            limit: Maximum number of messages to scan
            
        Returns:
            Tuple of (messages_scanned, newly_added_channels)
        """
        if not channel.guild:
            return 0, []
        
        newly_added = []
        messages_scanned = 0
        
        try:
            async for message in channel.history(limit=limit):
                messages_scanned += 1
                usernames = self.extract_all_twitch_usernames(message.content)
                
                for username in usernames:
                    if not await self.is_twitch_channel_tracked(channel.guild, username):
                        await self.add_twitch_channel(channel.guild, username)
                        if username not in newly_added:
                            newly_added.append(username)
        except discord.Forbidden:
            log.warning(f"No permission to read history in channel {channel.id}")
        except Exception as e:
            log.exception(f"Error scanning channel history: {e}")
        
        return messages_scanned, newly_added
