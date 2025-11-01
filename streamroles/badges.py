"""Badge and Achievement definitions for StreamRoles."""
import time
from typing import Dict, List, Tuple


class BadgeDefinition:
    """Definition of a streaming badge."""
    
    def __init__(self, badge_id: str, name: str, description: str, emoji: str, 
                 check_func, category: str = "general"):
        self.id = badge_id
        self.name = name
        self.description = description
        self.emoji = emoji
        self.check_func = check_func
        self.category = category
    
    def check(self, member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
        """
        Check if badge is earned.
        Returns (earned: bool, progress: float 0-1).
        """
        return self.check_func(member_data, guild_data)


class AchievementDefinition:
    """Definition of a guild-wide achievement (competitive)."""
    
    def __init__(self, achievement_id: str, name: str, description: str, emoji: str,
                 calc_func, minimum_value: float):
        self.id = achievement_id
        self.name = name
        self.description = description
        self.emoji = emoji
        self.calc_func = calc_func
        self.minimum_value = minimum_value
    
    def calculate_value(self, member_data: dict) -> float:
        """Calculate the value for this achievement for a member."""
        return self.calc_func(member_data)


# Helper functions for badge checks
def _total_stream_time(sessions: list) -> int:
    """Calculate total streaming time from sessions."""
    return sum(s.get("duration", 0) for s in sessions)


def _total_stream_count(sessions: list) -> int:
    """Count total streams."""
    return len(sessions)


def _check_consecutive_days(sessions: list, required_days: int) -> Tuple[bool, int]:
    """
    Check for consecutive streaming days.
    Returns (achieved, max_streak).
    """
    if not sessions:
        return False, 0
    
    # Group sessions by day (using formatted string for clarity)
    days_streamed = set()
    for s in sessions:
        start = s.get("start")
        if start:
            tm = time.gmtime(start)
            # Use formatted string: "YYYY-DDD" where DDD is day of year
            day_key = f"{tm.tm_year}-{tm.tm_yday:03d}"
            days_streamed.add(day_key)
    
    if not days_streamed:
        return False, 0
    
    # Convert back to comparable integers for streak calculation
    sorted_days = sorted([int(d.replace("-", "")) for d in days_streamed])
    max_streak = 1
    current_streak = 1
    
    for i in range(1, len(sorted_days)):
        # Check if consecutive (considering year boundary)
        if sorted_days[i] == sorted_days[i-1] + 1:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
    
    return max_streak >= required_days, max_streak


def _check_weekly_hours(sessions: list, required_hours: int) -> Tuple[bool, int]:
    """
    Check if member streamed required hours in any single week.
    Returns (achieved, max_weekly_hours).
    """
    if not sessions:
        return False, 0
    
    # Group by week
    weeks = {}
    for s in sessions:
        start = s.get("start")
        duration = s.get("duration", 0)
        if start:
            # ISO week number
            year_week = time.strftime("%Y-%W", time.gmtime(start))
            weeks[year_week] = weeks.get(year_week, 0) + duration
    
    if not weeks:
        return False, 0
    
    max_weekly_seconds = max(weeks.values())
    max_weekly_hours = max_weekly_seconds // 3600
    
    return max_weekly_hours >= required_hours, max_weekly_hours


def _check_monthly_hours(sessions: list, required_hours: int) -> Tuple[bool, int]:
    """Check if member streamed required hours in any single month."""
    if not sessions:
        return False, 0
    
    months = {}
    for s in sessions:
        start = s.get("start")
        duration = s.get("duration", 0)
        if start:
            year_month = time.strftime("%Y-%m", time.gmtime(start))
            months[year_month] = months.get(year_month, 0) + duration
    
    if not months:
        return False, 0
    
    max_monthly_seconds = max(months.values())
    max_monthly_hours = max_monthly_seconds // 3600
    
    return max_monthly_hours >= required_hours, max_monthly_hours


def _longest_stream(sessions: list) -> int:
    """Get longest single stream duration in seconds."""
    if not sessions:
        return 0
    return max(s.get("duration", 0) for s in sessions)


# Badge check functions
def check_first_stream(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """First stream badge."""
    sessions = member_data.get("sessions", [])
    earned = len(sessions) >= 1
    return earned, 1.0 if earned else 0.0


def check_10_streams(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """10 streams badge."""
    sessions = member_data.get("sessions", [])
    count = _total_stream_count(sessions)
    return count >= 10, min(count / 10.0, 1.0)


def check_50_streams(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """50 streams badge."""
    sessions = member_data.get("sessions", [])
    count = _total_stream_count(sessions)
    return count >= 50, min(count / 50.0, 1.0)


def check_100_streams(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """100 streams badge."""
    sessions = member_data.get("sessions", [])
    count = _total_stream_count(sessions)
    return count >= 100, min(count / 100.0, 1.0)


def check_10_hours(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """10 hours streamed badge."""
    sessions = member_data.get("sessions", [])
    total_seconds = _total_stream_time(sessions)
    target_seconds = 10 * 3600
    return total_seconds >= target_seconds, min(total_seconds / target_seconds, 1.0)


def check_50_hours(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """50 hours streamed badge."""
    sessions = member_data.get("sessions", [])
    total_seconds = _total_stream_time(sessions)
    target_seconds = 50 * 3600
    return total_seconds >= target_seconds, min(total_seconds / target_seconds, 1.0)


def check_100_hours(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """100 hours streamed badge."""
    sessions = member_data.get("sessions", [])
    total_seconds = _total_stream_time(sessions)
    target_seconds = 100 * 3600
    return total_seconds >= target_seconds, min(total_seconds / target_seconds, 1.0)


def check_300_hours(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """300 hours streamed badge."""
    sessions = member_data.get("sessions", [])
    total_seconds = _total_stream_time(sessions)
    target_seconds = 300 * 3600
    return total_seconds >= target_seconds, min(total_seconds / target_seconds, 1.0)


def check_2_day_streak(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """2 day streaming streak badge."""
    sessions = member_data.get("sessions", [])
    achieved, max_streak = _check_consecutive_days(sessions, 2)
    return achieved, min(max_streak / 2.0, 1.0)

def check_3_day_streak(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """3 day streaming streak badge."""
    sessions = member_data.get("sessions", [])
    achieved, max_streak = _check_consecutive_days(sessions, 3)
    return achieved, min(max_streak / 3.0, 1.0)

def check_5_day_streak(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """5 day streaming streak badge."""
    sessions = member_data.get("sessions", [])
    achieved, max_streak = _check_consecutive_days(sessions, 5)
    return achieved, min(max_streak / 5.0, 1.0)





def check_8_hours_week(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """8 hours in a week badge."""
    sessions = member_data.get("sessions", [])
    achieved, max_hours = _check_weekly_hours(sessions, 8)
    return achieved, min(max_hours / 8.0, 1.0)


def check_15_hours_week(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """15 hours in a week badge."""
    sessions = member_data.get("sessions", [])
    achieved, max_hours = _check_weekly_hours(sessions, 15)
    return achieved, min(max_hours / 15.0, 1.0)


def check_40_hours_month(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """40 hours in a month badge."""
    sessions = member_data.get("sessions", [])
    achieved, max_hours = _check_monthly_hours(sessions, 40)
    return achieved, min(max_hours / 40.0, 1.0)


def check_marathon_session(member_data: dict, guild_data: dict = None) -> Tuple[bool, float]:
    """Marathon session (6+ hours) badge."""
    sessions = member_data.get("sessions", [])
    longest = _longest_stream(sessions)
    target = 6 * 3600
    return longest >= target, min(longest / target, 1.0)


# Define all badges (15 badges)
BADGES = [
    BadgeDefinition(
        "first_stream",
        "First Steps",
        "Complete your first stream",
        "🌱",
        check_first_stream,
        "beginner"
    ),
    BadgeDefinition(
        "10_streams",
        "Getting Started",
        "Complete 10 streams",
        "🌿",
        check_10_streams,
        "streams"
    ),
    BadgeDefinition(
        "50_streams",
        "Regular Streamer",
        "Complete 50 streams",
        "🍃",
        check_50_streams,
        "streams"
    ),
    BadgeDefinition(
        "100_streams",
        "Streaming Veteran",
        "Complete 100 streams",
        "🌳",
        check_100_streams,
        "streams"
    ),
    BadgeDefinition(
        "10_hours",
        "10 Hour Club",
        "Stream for a total of 10 hours",
        "⏰",
        check_10_hours,
        "time"
    ),
    BadgeDefinition(
        "50_hours",
        "50 Hour Club",
        "Stream for a total of 50 hours",
        "⌚",
        check_50_hours,
        "time"
    ),
    BadgeDefinition(
        "100_hours",
        "Century Streamer",
        "Stream for a total of 100 hours",
        "⏳",
        check_100_hours,
        "time"
    ),
    BadgeDefinition(
        "300_hours",
        "Legendary Streamer",
        "Stream for a total of 300 hours",
        "🏆",
        check_300_hours,
        "time"
    ),
    BadgeDefinition(
        "2_day_streak",
        "On a Roll",
        "Stream for 2 consecutive days",
        "🔥",
        check_2_day_streak,
        "consistency"
    ),
    BadgeDefinition(
        "3_day_streak",
        "Stream Warrior",
        "Stream for 3 consecutive days",
        "💪",
        check_3_day_streak,
        "consistency"
    ),
    BadgeDefinition(
        "5_day_streak",
        "Unstoppable",
        "Stream for 5 consecutive days",
        "⚡",
        check_5_day_streak,
        "consistency"
    ),
    BadgeDefinition(
        "8_hours_week",
        "Weekly Grind",
        "Stream 8 hours in a single week",
        "📅",
        check_8_hours_week,
        "dedication"
    ),
    BadgeDefinition(
        "15_hours_week",
        "Week Warrior Pro",
        "Stream 15 hours in a single week",
        "💎",
        check_15_hours_week,
        "dedication"
    ),
    BadgeDefinition(
        "40_hours_month",
        "Monthly Champion",
        "Stream 40 hours in a single month",
        "👑",
        check_40_hours_month,
        "dedication"
    ),
    BadgeDefinition(
        "marathon_session",
        "Marathon Runner",
        "Complete a single stream of 6+ hours",
        "🏃",
        check_marathon_session,
        "endurance"
    ),
]

# Create badge lookup dictionary
BADGES_BY_ID = {badge.id: badge for badge in BADGES}


# Achievement calculation functions
def calc_longest_stream(member_data: dict) -> float:
    """Calculate longest single stream duration in hours."""
    sessions = member_data.get("sessions", [])
    return _longest_stream(sessions) / 3600.0


def calc_most_consistent(member_data: dict) -> float:
    """Calculate consistency score (max consecutive days)."""
    sessions = member_data.get("sessions", [])
    _, max_streak = _check_consecutive_days(sessions, 1)
    return float(max_streak)


def calc_total_hours(member_data: dict) -> float:
    """Calculate total hours streamed."""
    sessions = member_data.get("sessions", [])
    return _total_stream_time(sessions) / 3600.0


def calc_most_streams(member_data: dict) -> float:
    """Calculate total number of streams."""
    sessions = member_data.get("sessions", [])
    return float(_total_stream_count(sessions))


def calc_best_week(member_data: dict) -> float:
    """Calculate best weekly hours."""
    sessions = member_data.get("sessions", [])
    _, max_hours = _check_weekly_hours(sessions, 0)
    return float(max_hours)


def calc_best_month(member_data: dict) -> float:
    """Calculate best monthly hours."""
    sessions = member_data.get("sessions", [])
    _, max_hours = _check_monthly_hours(sessions, 0)
    return float(max_hours)


# Define achievements (competitive, guild-wide)
ACHIEVEMENTS = [
    AchievementDefinition(
        "marathon_king",
        "Marathon King/Queen",
        "Longest single stream session in the community (minimum 1 hour)",
        "👑",
        calc_longest_stream,
        1.0
    ),
    AchievementDefinition(
        "consistency_master",
        "Consistency Master",
        "Longest streaming streak in the community (minimum 2 days)",
        "🎯",
        calc_most_consistent,
        2.0
    ),
    AchievementDefinition(
        "time_champion",
        "Time Champion",
        "Most total hours streamed in the community (minimum 1 hour)",
        "⏱️",
        calc_total_hours,
        1.0
    ),
    AchievementDefinition(
        "stream_champion",
        "Stream Champion",
        "Most streams completed in the community (minimum 1 stream)",
        "🏅",
        calc_most_streams,
        1.0
    ),
    AchievementDefinition(
        "weekly_legend",
        "Weekly Legend",
        "Most hours in a single week in the community (minimum 1 hour)",
        "📆",
        calc_best_week,
        1.0
    ),
    AchievementDefinition(
        "monthly_master",
        "Monthly Master",
        "Most hours in a single month in the community (minimum 1 hour)",
        "📊",
        calc_best_month,
        1.0
    ),
]

# Create achievement lookup dictionary
ACHIEVEMENTS_BY_ID = {achievement.id: achievement for achievement in ACHIEVEMENTS}


def calculate_member_badges(sessions: list) -> Dict[str, dict]:
    """
    Calculate all badges for a member.
    Returns dict of badge_id -> {earned, progress, name, description, emoji, category}
    """
    member_data = {"sessions": sessions}
    result = {}
    
    for badge in BADGES:
        earned, progress = badge.check(member_data)
        result[badge.id] = {
            "earned": earned,
            "progress": progress,
            "name": badge.name,
            "description": badge.description,
            "emoji": badge.emoji,
            "category": badge.category
        }
    
    return result


def calculate_guild_achievements(all_member_data: Dict[int, dict]) -> Dict[str, dict]:
    """
    Calculate achievements across all guild members.
    Returns dict of achievement_id -> {holder_id, holder_name, value, name, description, emoji}
    """
    result = {}
    
    for achievement in ACHIEVEMENTS:
        best_member_id = None
        best_member_name = None
        best_value = 0.0
        
        for member_id, member_data in all_member_data.items():
            value = achievement.calculate_value(member_data)
            if value >= achievement.minimum_value and value > best_value:
                best_value = value
                best_member_id = member_id
                best_member_name = member_data.get("display_name", "Unknown")
        
        result[achievement.id] = {
            "holder_id": best_member_id,
            "holder_name": best_member_name,
            "value": best_value,
            "name": achievement.name,
            "description": achievement.description,
            "emoji": achievement.emoji,
            "minimum_value": achievement.minimum_value,
            "has_holder": best_member_id is not None
        }
    
    return result
