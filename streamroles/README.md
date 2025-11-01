# StreamRoles

A comprehensive Discord cog for tracking Twitch streaming activity, awarding badges, managing achievements, and providing advanced analytics for streaming communities.

## Features

### 🏆 Badge System (15 Badges)

Members can earn badges by reaching various streaming milestones:

#### Beginner
- **First Steps** 🌱 - Complete your first stream

#### Stream Count
- **Getting Started** 🌿 - Complete 10 streams
- **Regular Streamer** 🍃 - Complete 50 streams
- **Streaming Veteran** 🌳 - Complete 100 streams

#### Total Time
- **10 Hour Club** ⏰ - Stream for 10 hours total
- **50 Hour Club** ⌚ - Stream for 50 hours total
- **Century Streamer** ⏳ - Stream for 100 hours total
- **Legendary Streamer** 🏆 - Stream for 500 hours total

#### Consistency
- **On a Roll** 🔥 - Stream for 3 consecutive days
- **Week Warrior** 💪 - Stream for 7 consecutive days
- **Unstoppable** ⚡ - Stream for 30 consecutive days

#### Dedication
- **Weekly Grind** 📅 - Stream 15 hours in a single week
- **Week Warrior Pro** 💎 - Stream 30 hours in a single week
- **Monthly Champion** 👑 - Stream 100 hours in a single month

#### Endurance
- **Marathon Runner** 🏃 - Complete a single stream of 8+ hours

### 🏅 Achievement System (6 Achievements)

Guild-wide competitive achievements awarded to the top performers:

- **Marathon King/Queen** 👑 - Longest single stream session (min. 8 hours)
- **Consistency Master** 🎯 - Longest streaming streak (min. 7 days)
- **Time Champion** ⏱️ - Most total hours streamed (min. 100 hours)
- **Stream Champion** 🏅 - Most streams completed (min. 50 streams)
- **Weekly Legend** 📆 - Most hours in a single week (min. 30 hours)
- **Monthly Master** 📊 - Most hours in a single month (min. 100 hours)

### 📊 Advanced Analytics

#### Optimal Schedule Predictor
- Analyzes historical streaming data to suggest the best times to stream
- Shows your top-performing time slots
- Identifies low-competition time windows for growth opportunities

#### Audience Overlap Analysis
- Shows which streamers share similar time slots
- Calculates overlap percentages
- Helps understand audience competition

#### Collaboration Matcher
- Suggests streamers for potential collaborations
- Based on complementary schedules (low overlap = better collab potential)
- Considers activity levels for quality matches

#### Community Health Score
- Overall community activity grade (F to A+)
- Tracks active streamers and engagement
- Shows growth trends (streamer count and stream volume)
- Provides actionable insights for community managers

### 🎮 Core Streaming Features

- **Automatic Role Assignment** - Assigns roles to members streaming on Twitch
- **Stream Alerts** - Real-time notifications when community members go live
- **Statistics Tracking** - Comprehensive session tracking with duration, games, and timestamps
- **Whitelist/Blacklist** - Fine-grained control over who receives the streamer role
- **Game Filtering** - Optionally restrict to specific games
- **Data Export** - Export streaming statistics to CSV

## Installation

1. Add the cog repository to your Red-DiscordBot:
```
[p]repo add Heymow-cogs https://github.com/Heymow/Heymow-cogs
```

2. Install the StreamRoles cog:
```
[p]cog install Heymow-cogs streamroles
```

3. Load the cog:
```
[p]load streamroles
```

## Configuration

### Basic Setup

1. Set the streamer role:
```
[p]streamrole setrole @StreamerRole
```

2. Enable stream alerts (optional):
```
[p]streamrole alerts setenabled true
[p]streamrole alerts setchannel #stream-alerts
```

3. Configure stats retention (optional):
```
[p]streamrole setstatsretention 365
```

### API Configuration

For the dashboard to work, you need to configure the API token:

1. Set an API token for your guild (bot owner only):
```
[p]streamrole setapitoken YOUR_SECRET_TOKEN
```

2. Set a fixed guild ID (optional, bot owner only):
```
[p]streamrole setfixedguild YOUR_GUILD_ID
```

### Advanced Configuration

**Whitelist/Blacklist Members or Roles:**
```
[p]streamrole whitelist add @User
[p]streamrole blacklist add @Role
```

**Game Filtering:**
```
[p]streamrole games add "Game Name"
[p]streamrole games show
```

**Required Role:**
```
[p]streamrole setrequiredrole @MemberRole
```

## Dashboard

The cog includes a web dashboard accessible at `http://HOST:PORT/dashboard` (default: `http://localhost:8080/dashboard`).

### Dashboard Features

- **Overview Tab** - Top streamers and community statistics
- **Weekly Heatmap Tab** - Visual representation of streaming activity by day/hour
- **All Streamers Tab** - Complete list with badges and stats
- **Streamer Details Tab** - Individual member statistics and session history
- **Badges & Achievements Tab** - Badge collection and guild achievements
- **Insights Tab** - Community health score and analytics

### Environment Variables

- `HOST` - API server host (default: 0.0.0.0)
- `PORT` - API server port (default: 8080)

## Commands

### Administration Commands

- `[p]streamrole setrole <role>` - Set the role given to streamers
- `[p]streamrole setrequiredrole <role>` - Set required role to receive streamer role
- `[p]streamrole setmode <blacklist|whitelist>` - Set filter mode
- `[p]streamrole forceupdate` - Force update of all members
- `[p]streamrole togglestats <true|false>` - Enable/disable stats collection
- `[p]streamrole setstatsretention <days>` - Set data retention period

### Whitelist/Blacklist Commands

- `[p]streamrole whitelist add <user_or_role>` - Add to whitelist
- `[p]streamrole whitelist remove <user_or_role>` - Remove from whitelist
- `[p]streamrole whitelist show` - Show whitelist

- `[p]streamrole blacklist add <user_or_role>` - Add to blacklist
- `[p]streamrole blacklist remove <user_or_role>` - Remove from blacklist
- `[p]streamrole blacklist show` - Show blacklist

### Game Filter Commands

- `[p]streamrole games add <game>` - Add game to whitelist
- `[p]streamrole games remove <game>` - Remove game from whitelist
- `[p]streamrole games show` - Show game whitelist
- `[p]streamrole games clear` - Clear game whitelist

### Alert Commands

- `[p]streamrole alerts setenabled <true|false>` - Enable/disable alerts
- `[p]streamrole alerts setchannel <channel>` - Set alert channel
- `[p]streamrole alerts autodelete <true|false>` - Auto-delete alerts when stream ends

### Statistics Commands

- `[p]streamrole stats show [member] [period]` - Show streaming statistics
  - Period examples: `7d`, `30d`, `all`
- `[p]streamrole stats export [member] [period]` - Export stats to CSV
- `[p]streamrole stats top [metric] [period] [limit]` - Show top streamers
  - Metrics: `time`, `count`

### API Commands (Bot Owner Only)

- `[p]streamrole setapitoken <token>` - Set API token for guild
- `[p]streamrole setfixedguild <guild_id>` - Set fixed guild ID

## API Endpoints

### Public Dashboard Proxy Endpoints

All dashboard proxy endpoints are publicly accessible:

- `POST /dashboard/proxy/top` - Get top streamers
- `POST /dashboard/proxy/heatmap` - Get streaming heatmap data
- `POST /dashboard/proxy/all_members` - Get all members with stats
- `POST /dashboard/proxy/badges/{guild_id}/{member_id}` - Get member badges
- `POST /dashboard/proxy/badges_batch` - Get badges for multiple members (batch)
- `POST /dashboard/proxy/achievements` - Get guild achievements
- `POST /dashboard/proxy/schedule_predictor` - Get optimal streaming times
- `POST /dashboard/proxy/audience_overlap` - Get audience overlap analysis
- `POST /dashboard/proxy/collaboration_matcher` - Get collaboration suggestions
- `POST /dashboard/proxy/community_health` - Get community health metrics
- `POST /dashboard/proxy/member/{guild_id}/{member_id}` - Get member details
- `POST /dashboard/proxy/export/{guild_id}/{member_id}` - Export member stats (CSV)

### Internal API Endpoints

Internal endpoints are restricted to localhost only:

- `GET /api/guild/{guild_id}/member/{member_id}` - Get member stats (requires auth)
- `GET /api/guild/{guild_id}/top` - Get top streamers (requires auth)
- `GET /api/guild/{guild_id}/export/member/{member_id}` - Export CSV (requires auth)

## Badge Progress Tracking

Members can see their progress toward locked badges:
- Badges show progress bars (0-100%) for locked badges
- Hover over badges to see requirements
- Earned badges are highlighted in green
- Locked badges are grayed out

## Data Storage

All streaming data is stored in Red-DiscordBot's Config system:
- Member statistics (sessions, durations, games)
- Badge progress (automatically calculated)
- Guild achievements (recalculated on request)
- Alert message IDs (for auto-deletion)

## Requirements

- Red-DiscordBot 3.4+
- aiohttp 3.8+
- Discord.py

## Privacy & Security

- All features are public (no authentication required for dashboard)
- API token required for guild configuration (owner only)
- Internal API endpoints restricted to localhost
- No personal data collected beyond Discord IDs and streaming activity
- Session caching prevents duplicate data fetching

## Performance Considerations

- Batch badge endpoint reduces HTTP requests by up to 20x
- Session caching in community health calculations
- Optimized query patterns to avoid N+1 problems
- Automatic data pruning based on retention settings

## Support

For issues, feature requests, or contributions, please visit:
https://github.com/Heymow/Heymow-cogs

## License

This cog is part of the Heymow-cogs repository.

## Credits

- Created by Heymow
- Badge system inspired by streaming achievement platforms
- Analytics features powered by historical data analysis
