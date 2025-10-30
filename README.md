# Heymow-Cogs

A list of Redbot cogs for Discord with various functions.

- Linkchecker: Checks if a given Suno link is valid, with the two Suno link formats, checks if it's unique and checks if it has already been posted on the same server in the same week. If a link doesn't pass the test, the message is instantly removed and Redbot posts a warning to the user and in the admin channel, with the total count of link rejection per user.
- Extractsongs: Saves every valid Suno song link posted in a list of given channels, into a local database. Every 24 hours, a short summary is posted with every song in memory and flushes the memory. Possibility to require the current list of songs in memory and flush it.
- Pulsify_linkchecker: same as Linkchecker but cross-server
- Channel_fuser: Fuses two different Discord channels into one, keeping the order of the messages and the authors of messages intact.
