import discord
from discord.ext import commands
import wavelink
import os
from dotenv import load_dotenv
import asyncio
import urllib.parse # Нужно для кодирования текста в ссылку
import json

# Загрузка переменных
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="a!", intents=intents)

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def setup_nodes(self):
        """Подключаемся к нодам."""
        await self.bot.wait_until_ready()
        
        # Список нод (Non-SSL, HTTP) - тот, который у тебя заработал
        nodes_data = [
            {
                "id": "Hatry-Node",
                "uri": "http://lavahatry4.techbyte.host:3000",
                "pwd": "naig.is-a.dev"
            },
            {
                "id": "Jirayu-Node",
                "uri": "http://lavalink.jirayu.net:13592",
                "pwd": "youshallnotpass"
            },
        ]

        # Создаем объекты нод
        wavelink_nodes = []
        for n in nodes_data:
            wavelink_nodes.append(wavelink.Node(identifier=n["id"], uri=n["uri"], password=n["pwd"]))

        # Пытаемся подключиться
        print(f"🔄 Попытка подключения к {len(wavelink_nodes)} HTTP серверам...")
        try:
            await wavelink.Pool.connect(nodes=wavelink_nodes, client=self.bot, cache_capacity=100)
        except Exception as e:
            print(f"Инициализация пула завершена (ошибки подключения ожидаемы): {e}")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"✅ УСПЕХ: Нода '{payload.node.identifier}' подключена и готова!")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """
        Срабатывает, когда трек заканчивается.
        Здесь мы проверяем, нужно ли повторять трек.
        """
        player = payload.player
        if not player:
            return

        # ПРОВЕРКА ЗАЦИКЛИВАНИЯ
        # getattr(obj, name, default) безопасен, если атрибута еще нет
        if getattr(player, "loop_mode", False):
            # Если включен повтор -> играем тот же трек (payload.track) заново
            await player.play(payload.track)
        elif not player.queue.is_empty:
            # Если повтор выключен -> берем следующий из очереди
            await player.play(player.queue.get())

    # --- КОМАНДЫ ---

    @commands.command(name='join')
    async def join(self, ctx):
        if not ctx.author.voice:
            return await ctx.send("Сначала зайди в голосовой канал!")
        if not ctx.voice_client:
            try:
                await ctx.author.voice.channel.connect(cls=wavelink.Player)
                await ctx.send(f"Подключился к **{ctx.author.voice.channel}**")
            except wavelink.InvalidNodeException:
                await ctx.send("❌ Жду подключения серверов... (Попробуйте через 10 сек)")
            except Exception as e:
                await ctx.send(f"Ошибка: {e}")
        else:
            await ctx.send("Я уже тут.")

    @commands.command(name='play')
    async def play(self, ctx, *, query: str):
        # 1. Проверяем наличие живых нод
        try:
            wavelink.Pool.get_node()
        except wavelink.InvalidNodeException:
            return await ctx.send("⚠️ **Серверы еще подключаются.** Подождите немного и попробуйте снова.")

        # 2. Подключение
        if not ctx.voice_client:
            try:
                if ctx.author.voice:
                    await ctx.author.voice.channel.connect(cls=wavelink.Player)
                else:
                    return await ctx.send("Зайдите в голосовой канал!")
            except Exception as e:
                return await ctx.send(f"Ошибка подключения: {e}")
        
        player: wavelink.Player = ctx.voice_client
        player.autoplay = wavelink.AutoPlayMode.disabled

        # 3. Поиск (SoundCloud приоритет)
        await ctx.send(f"🔍 Ищу: `{query}`...")
        try:
            if query.startswith("http"):
                tracks = await wavelink.Playable.search(query)
            else:
                tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
        except Exception as e:
            return await ctx.send(f"Ошибка поиска: {e}")

        if not tracks:
            return await ctx.send("Ничего не найдено (попробуйте прямую ссылку).")

        if isinstance(tracks, wavelink.Playlist):
            for track in tracks:
                player.queue.put(track)
            await ctx.send(f"Добавлен плейлист **{tracks.name}**.")
        else:
            track = tracks[0]
            player.queue.put(track)
            await ctx.send(f"Трек **{track.title}** ({track.author}) добавлен в очередь.")

        if not player.playing:
            await player.play(player.queue.get())

    @commands.command(name='loop', aliases=['repeat'])
    async def loop(self, ctx):
        """Включает или выключает повтор текущего трека."""
        player: wavelink.Player = ctx.voice_client
        
        if not player or not player.playing:
            return await ctx.send("Сейчас ничего не играет.")

        # Если атрибута loop_mode нет, создаем его (False по умолчанию)
        if not hasattr(player, "loop_mode"):
            player.loop_mode = False

        # Переключаем состояние (True -> False, False -> True)
        player.loop_mode = not player.loop_mode

        if player.loop_mode:
            await ctx.send("🔂 **Повтор включен**: Текущий трек будет играть по кругу.")
        else:
            await ctx.send("➡️ **Повтор выключен**: Играем дальше по очереди.")

    @commands.command(name='skip')
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.playing:
            # Если включен луп, при скипе мы, вероятно, хотим перейти к следующему треку, а не снова играть этот же
            player: wavelink.Player = ctx.voice_client
            if hasattr(player, "loop_mode") and player.loop_mode:
                player.loop_mode = False # Выключаем луп при ручном пропуске
                await ctx.send("🔂 Повтор выключен из-за пропуска.")

            await ctx.voice_client.skip(force=True)
            await ctx.send("Пропущено.")
        else:
            await ctx.send("Ничего не играет.")

    @commands.command(name='stop')
    async def stop(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Стоп.")

    @commands.command(name='queue')
    async def queue_cmd(self, ctx):
        player: wavelink.Player = ctx.voice_client
        if not player or (player.queue.is_empty and not player.playing):
            return await ctx.send("Очередь пуста.")

        embed = discord.Embed(title="Очередь", color=discord.Color.green())
        
        # Статус
        status = ""
        if hasattr(player, "loop_mode") and player.loop_mode:
            status = " (🔂 Повтор включен)"

        if player.playing:
            embed.add_field(name=f"Сейчас играет{status}", value=f"**{player.current.title}**", inline=False)

        if not player.queue.is_empty:
            queue_list = ""
            for i, track in enumerate(player.queue):
                if i >= 10: break
                queue_list += f"{i+1}. {track.title}\n"
            embed.add_field(name="Далее", value=queue_list, inline=False)

        await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Бот запущен: {bot.user}')
    print('------')
    music_cog = MusicCog(bot)
    await bot.add_cog(music_cog)
    await music_cog.setup_nodes()
    await bot.change_presence(activity=discord.Game(name="a!play | a!talk"))
    print("✅ Все системы загружены: Музыка")


if TOKEN:
    bot.run(TOKEN)
else:
    print("ОШИБКА: Токен не найден в .env")







