# lavamusic
Discord Music Bot (Wavelink/Lavalink Integration)

A high-performance Discord music bot built with Python, discord.py, and Wavelink. This project demonstrates asynchronous programming, external API integration (Lavalink), and state management for features like track queuing and looping.
Features

    High-Quality Audio: Powered by Lavalink for stable and low-latency audio streaming.

    SoundCloud Integration: Supports direct searching and playback from SoundCloud.

    Queue Management: Robust queuing system including track skipping and playlist support.

    Loop Mode: Toggleable repeat functionality for individual tracks.

    Dynamic UI: Uses Discord Embeds for a clean and professional user interface.

System Architecture

The bot operates as a client that communicates with a Lavalink server via WebSockets. The Lavalink node handles the heavy lifting of audio decoding and streaming, allowing the bot to remain responsive and lightweight.
Technical Stack

    Language: Python 3.8+

    Library: discord.py

    Audio Wrapper: Wavelink

    Backend: Lavalink

Installation & Setup
1. Prerequisites

    A Discord Bot Token (via Discord Developer Portal)

    A running Lavalink server instance.

    Python 3.8 or higher.

2. Install Dependencies
Bash

pip install discord.py wavelink python-dotenv

3. Configuration

Create a .env file in the root directory and add your bot token:
Code snippet

TOKEN=your_discord_bot_token_here

4. Running the Bot
Bash

python main.py

Commands
Command	Description
a!play <query>	Searches SoundCloud and adds the result to the queue.
a!loop	Toggles loop mode for the currently playing track.
a!skip	Skips the current track and disables loop mode.
a!queue	Displays the current playback queue and status.
a!stop	Stops playback and disconnects the bot from the voice channel.
