import discord
import wavelink
from discord.ext import commands

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def setup_nodes(self):
        """Initialize Wavelink nodes."""
        # Note: Replace these placeholder values with your actual Lavalink credentials
        nodes = [wavelink.Node(uri="http://localhost:2333", password="youshallnotpass")]
        await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)

    @commands.command(name='play')
    async def play(self, ctx, *, query: str):
        """Search and play a track from SoundCloud."""
        if not ctx.voice_client:
            vc: wavelink.Player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            vc: wavelink.Player = ctx.voice_client

        try:
            # Searching SoundCloud as specified in your original logic
            tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
        except Exception as e:
            return await ctx.send(f"Search error: {e}")

        if not tracks:
            return await ctx.send("No results found. Please provide a direct link or a more specific query.")

        if isinstance(tracks, wavelink.Playlist):
            for track in tracks:
                vc.queue.put(track)
            await ctx.send(f"Added playlist: {tracks.name}")
        else:
            track = tracks[0]
            vc.queue.put(track)
            await ctx.send(f"Added to queue: {track.title} by {track.author}")

        if not vc.playing:
            await vc.play(vc.queue.get())

    @commands.command(name='loop', aliases=['repeat'])
    async def loop(self, ctx):
        """Toggle loop mode for the current track."""
        player: wavelink.Player = ctx.voice_client
        
        if not player or not player.playing:
            return await ctx.send("No media is currently playing.")

        # Initialize loop_mode attribute if not present
        if not hasattr(player, "loop_mode"):
            player.loop_mode = False

        player.loop_mode = not player.loop_mode
        
        status = "enabled" if player.loop_mode else "disabled"
        await ctx.send(f"Loop mode {status}.")

    @commands.command(name='skip')
    async def skip(self, ctx):
        """Skip the current track."""
        player: wavelink.Player = ctx.voice_client
        if player and player.playing:
            # Disable loop mode on manual skip to proceed to the next item
            if hasattr(player, "loop_mode") and player.loop_mode:
                player.loop_mode = False
                await ctx.send("Loop mode disabled for manual skip.")

            await player.skip(force=True)
            await ctx.send("Track skipped.")
        else:
            await ctx.send("No track is currently playing.")

    @commands.command(name='stop')
    async def stop(self, ctx):
        """Stop playback and disconnect from the voice channel."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Playback stopped and disconnected.")

    @commands.command(name='queue')
    async def queue_cmd(self, ctx):
        """Display the current playback queue."""
        player: wavelink.Player = ctx.voice_client
        if not player or (player.queue.is_empty and not player.playing):
            return await ctx.send("The queue is currently empty.")

        embed = discord.Embed(title="Playback Queue", color=discord.Color.blue())
        
        loop_status = " (Loop Enabled)" if hasattr(player, "loop_mode") and player.loop_mode else ""

        if player.playing:
            embed.add_field(
                name=f"Currently Playing{loop_status}", 
                value=player.current.title, 
                inline=False
            )

        if not player.queue.is_empty:
            queue_list = ""
            for i, track in enumerate(player.queue):
                if i >= 10: 
                    queue_list += "..."
                    break
                queue_list += f"{i+1}. {track.title}\n"
            embed.add_field(name="Up Next", value=queue_list, inline=False)

        await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as: {bot.user}")
    print("------")
    music_cog = MusicCog(bot)
    await bot.add_cog(music_cog)
    await music_cog.setup_nodes()
    await bot.change_presence(activity=discord.Game(name="a!play | music services"))
    print("Music System: Operational")

if TOKEN:
    bot.run(TOKEN)
else:
    print("Critical Error: Discord Token not found in environment variables.")
