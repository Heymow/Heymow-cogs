![Save Song Logo](./save-song.png)

# SAVE SONG
# For Red-DiscordBot (cog)

"Save Song" (extractsongs) is a Red-DiscordBot cog that listens for Suno song links shared in configured channels, saves song metadata locally and in Red's Config, and posts daily summaries of collected songs. It supports per-guild configuration for listening channels, output channels, notification channels, and a log channel.
---
## Features
- Detects Suno links in messages (formats like `https://suno.com/song/<uuid>` and `https://suno.com/s/<shortid>`).
- Stores detected song metadata in Red's Config and as local JSON files in `./song_cache`.
- Optional immediate notifications to a configured output channel when a new song is saved.
- Daily summary task that posts songs shared in the past 24 hours to a configured daily channel (sent in batches when necessary).
- Notification to a configured notification channel when no songs were shared in the last 24 hours.
- Commands to manage channels, view stored data, and force send summaries.
- Basic logging to a configured log channel and to the console.
---
## Installation
1. Place the cog folder (extractsongs/) inside your Red bot's `cogs/` directory, preserving the file `extractsongs.py`.
2. Ensure your bot has the necessary Python dependencies. This cog uses the standard library and Red's API (Red-DiscordBot).
3. Restart or reload your bot.
4. Load the cog (if not automatically loaded) with:
   - `[p]cog install /path/to/extractsongs` or use your usual method to add the cog.
   - Or in Red: `[p]load extractsongs` (depending on your setup).
---
## Configuration & Permissions
- The cog uses Red's per-guild Config to store:
  - listening_channels: list of channel IDs where the cog watches messages
  - output_channel: ID to send individual-song notifications
  - daily_channel: ID for daily summaries
  - notification_channel: ID for "no songs" notices
  - log_channel: ID for log/debug messages
  - saved_songs: dict of stored songs
  - last_daily_timestamp: ISO timestamp of last daily summary run

- Bot permissions required in configured channels:
  - Read Messages / View Channel
  - Send Messages
  - Embed Links (to send embeds)
  - (Optional) Manage Messages when using management commands. Commands below require Manage Messages permission.
---
## Commands
All commands require the caller to have Manage Messages permission.

- [p]add_channel <#channel>
  - Add a channel to the listening list (the cog will watch messages there for Suno links).

- [p]remove_channel <#channel>
  - Remove a channel from the listening list.

- [p]list_channels
  - Show the channels currently being listened to.

- [p]set_output <#channel>
  - Set the channel where a notification will be sent whenever a new song is saved.

- [p]set_daily <#channel>
  - Set the channel where daily summaries will be posted.

- [p]set_notification <#channel>
  - Set the channel where "no new songs" notifications will be posted when there were none in the last 24 hours.

- [p]set_log <#channel>
  - Set the channel where internal logs/debug messages will be posted.

- [p]send_summary_now
  - Force the cog to generate and send the daily summary immediately for the guild.

- [p]view_data
  - Shows the stored configuration, number of saved songs, last daily timestamp, and up to 10 recent saved songs (IDs and authors).

- [p]clear_data
  - Clears stored configuration for the current guild (listening/output/daily/notification/log and saved songs). Use with caution.

- [p]list_config
  - Print a formatted embed summarizing the current configuration for the guild.
---
## How it works
- The cog registers a background task (daily_summary_loop) that wakes every hour and checks if 24 hours have passed since the last daily summary; if so, it sends a summary for each guild which has a configured daily channel.
- When a message in a configured listening channel contains a Suno link, the cog extracts the song id, normalizes the URL form, and stores metadata including the message author, channel, timestamp, and the song URL.
- Song metadata is saved in two places:
  - Red's persistent Config for the guild (under `saved_songs`)
  - a local JSON file in the `song_cache` directory named `<song_id>.json`
- During daily summary, only songs posted in the last 24 hours are included. After successfully sending summaries, those songs are removed from the Config and their JSON files deleted.
---
## File storage
- A folder named `song_cache` is created next to the cog at runtime (path `./song_cache`) and holds individual JSON files per detected song. This is intended for compatibility with hosting providers that allow writing to the working directory (e.g., Railway).
- If you host the bot in an environment where the working directory is ephemeral or not writeable, consider disabling or changing that behavior.
---
## Notes & Caveats
- The cog assumes the bot's system clock is correct and uses UTC-aware datetimes to compare timestamps.
- If a saved song's posted_time cannot be parsed, that entry is skipped during daily summary.
- The daily task is scheduled when the cog is initialized. When unloading the cog, the task is cancelled.
- The cog prints diagnostic messages to console and to the configured log channel (if set). Check logs for troubleshooting.
- The code is designed for Red-DiscordBot's API and permissions. Command prefixes shown as [p] represent your bot's configured prefix.
---
## Contributing
If you find issues or want enhancements:
- Open an issue or a PR on the repository.
- Include steps to reproduce, logs (if applicable), and desired behavior.
---
## Contact
- Repo owner: Heymow (see repository for links and more details).
---
## Thank you for using the Save Song cog! If you need help configuring it for your server, provide details of your setup and I'll help walk you through it.
