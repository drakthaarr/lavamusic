import discord
from discord.ext import commands
import wavelink
import os
from dotenv import load_dotenv
import asyncio
import random

# Загрузка переменных
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="a!", intents=intents, help_command=None)

# ─────────────────────────────────────────────
#  Режимы зацикливания
# ─────────────────────────────────────────────
LOOP_OFF   = "off"
LOOP_TRACK = "track"
LOOP_QUEUE = "queue"

LOOP_LABELS = {
    LOOP_OFF:   "➡️  Без повтора",
    LOOP_TRACK: "🔂 Повтор трека",
    LOOP_QUEUE: "🔁 Повтор очереди",
}

def _get_loop(player) -> str:
    return getattr(player, "loop_mode", LOOP_OFF)

def _set_loop(player, mode: str):
    player.loop_mode = mode

def _get_history(player) -> list:
    """Возвращает список треков-«историю» для повтора очереди."""
    if not hasattr(player, "queue_history"):
        player.queue_history = []
    return player.queue_history


# ─────────────────────────────────────────────
#  Вспомогательная: progress bar
# ─────────────────────────────────────────────
def make_progress_bar(position_ms: int, length_ms: int, size: int = 15) -> str:
    if not length_ms:
        return "─" * size
    filled = int(size * position_ms / length_ms)
    bar = "▬" * filled + "🔘" + "─" * (size - filled)
    return bar


def fmt_time(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


# ─────────────────────────────────────────────
#  Cog
# ─────────────────────────────────────────────
class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def setup_nodes(self):
        await self.bot.wait_until_ready()
        nodes_data = [
            {"id": "Hatry-Node",   "uri": "http://lavahatry4.techbyte.host:3000",   "pwd": "naig.is-a.dev"},
        ]
        wavelink_nodes = [
            wavelink.Node(identifier=n["id"], uri=n["uri"], password=n["pwd"])
            for n in nodes_data
        ]
        print(f"🔄 Подключаемся к {len(wavelink_nodes)} серверам...")
        connected = 0
        for node in wavelink_nodes:
            try:
                await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
                connected += 1
            except Exception as e:
                print(f"⚠️ Нода {node.identifier} недоступна: {e}")
        if connected == 0:
            print("❌ Ни одна нода не подключилась! Музыка работать не будет.")
        else:
            print(f"✅ Подключено нод: {connected}/{len(wavelink_nodes)}")

    # ── события ──────────────────────────────

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"✅ Нода '{payload.node.identifier}' готова!")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if not player:
            return

        loop = _get_loop(player)

        if loop == LOOP_TRACK:
            # Повторяем тот же трек
            await player.play(payload.track)

        elif loop == LOOP_QUEUE:
            # Кладём завершённый трек в конец очереди и берём следующий
            player.queue.put(payload.track)
            if not player.queue.is_empty:
                await player.play(player.queue.get())

        else:
            # Обычное воспроизведение следующего
            if not player.queue.is_empty:
                await player.play(player.queue.get())

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Авто-отключение, если в канале никого не осталось."""
        if member.bot:
            return
        vc: wavelink.Player = member.guild.voice_client
        if not vc:
            return
        channel = vc.channel
        if channel and len([m for m in channel.members if not m.bot]) == 0:
            await asyncio.sleep(30)  # ждём 30 сек
            # Проверяем ещё раз — вдруг кто вернулся
            if len([m for m in channel.members if not m.bot]) == 0:
                await vc.disconnect()

    # ── join / leave ─────────────────────────

    @commands.command(name='join')
    async def join(self, ctx):
        """Подключиться к голосовому каналу."""
        if not ctx.author.voice:
            return await ctx.send("❌ Сначала зайди в голосовой канал!")
        if not ctx.voice_client:
            try:
                await ctx.author.voice.channel.connect(cls=wavelink.Player)
                await ctx.send(f"✅ Подключился к **{ctx.author.voice.channel}**")
            except wavelink.InvalidNodeException:
                await ctx.send("❌ Серверы ещё подключаются... (попробуй через 10 сек)")
            except Exception as e:
                await ctx.send(f"❌ Ошибка: {e}")
        else:
            await ctx.send("Я уже тут.")

    @commands.command(name='leave', aliases=['disconnect', 'dc'])
    async def leave(self, ctx):
        """Отключиться от голосового канала."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 Отключился.")
        else:
            await ctx.send("Я не в канале.")

    # ── play ─────────────────────────────────

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx, *, query: str):
        """Найти и воспроизвести трек или плейлист."""
        try:
            wavelink.Pool.get_node()
        except wavelink.InvalidNodeException:
            return await ctx.send("⚠️ Серверы ещё подключаются. Подождите немного.")

        if not ctx.voice_client:
            if ctx.author.voice:
                try:
                    await ctx.author.voice.channel.connect(cls=wavelink.Player)
                except Exception as e:
                    return await ctx.send(f"❌ Ошибка подключения: {e}")
            else:
                return await ctx.send("❌ Зайдите в голосовой канал!")

        player: wavelink.Player = ctx.voice_client
        player.autoplay = wavelink.AutoPlayMode.disabled

        await ctx.send(f"🔍 Ищу: `{query}`...")
        try:
            tracks = (
                await wavelink.Playable.search(query)
                if query.startswith("http")
                else await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
            )
        except Exception as e:
            return await ctx.send(f"❌ Ошибка поиска: {e}")

        if not tracks:
            return await ctx.send("😕 Ничего не найдено.")

        # Определяем: играет ли сейчас что-то
        # player.current надёжнее чем player.playing в wavelink 3.x
        is_playing = player.current is not None

        if isinstance(tracks, wavelink.Playlist):
            first_track = None
            for i, track in enumerate(tracks):
                if i == 0 and not is_playing:
                    first_track = track  # первый трек играем сразу
                else:
                    player.queue.put(track)
            msg = f"📃 Добавлен плейлист **{tracks.name}** ({len(tracks)} треков)."
            if first_track:
                try:
                    await player.play(first_track)
                    await ctx.send(msg)
                except Exception as e:
                    await ctx.send(f"❌ Не могу воспроизвести: `{e}`")
            else:
                await ctx.send(msg)
        else:
            track = tracks[0]
            if not is_playing:
                # Ничего не играет → запускаем сразу
                try:
                    await player.play(track)
                    await ctx.send(f"▶️ Играю: **{track.title}** — *{track.author}*")
                except Exception as e:
                    await ctx.send(f"❌ Не могу воспроизвести: `{e}`")
            else:
                # Уже играет → в очередь
                player.queue.put(track)
                pos = len(player.queue)
                await ctx.send(f"🎵 **{track.title}** — *{track.author}* добавлен в очередь (позиция {pos}).")

    # ── playskip ─────────────────────────────

    @commands.command(name='playskip', aliases=['ps'])
    async def playskip(self, ctx, *, query: str):
        """Найти трек и немедленно начать его воспроизведение, добавив в начало очереди."""
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале. Используй `a!join`.")

        await ctx.send(f"🔍 Ищу: `{query}`...")
        try:
            tracks = (
                await wavelink.Playable.search(query)
                if query.startswith("http")
                else await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
            )
        except Exception as e:
            return await ctx.send(f"❌ Ошибка поиска: {e}")

        if not tracks:
            return await ctx.send("😕 Ничего не найдено.")

        track = tracks[0] if not isinstance(tracks, wavelink.Playlist) else tracks[0]
        # Вставляем в начало очереди
        player.queue.put_at(0, track)
        if player.current is not None:
            await player.skip(force=True)
        else:
            await player.play(player.queue.get())
        await ctx.send(f"⏭️ Сейчас играет: **{track.title}** — *{track.author}*")

    # ── loop ─────────────────────────────────

    @commands.command(name='loop', aliases=['repeat', 'l'])
    async def loop(self, ctx, mode: str = None):
        """
        Режим повтора: `off` / `track` / `queue`
        Без аргумента — переключает по кругу.
        """
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале.")

        current = _get_loop(player)
        cycle = [LOOP_OFF, LOOP_TRACK, LOOP_QUEUE]

        if mode:
            mode = mode.lower()
            aliases = {"off": LOOP_OFF, "0": LOOP_OFF,
                       "track": LOOP_TRACK, "трек": LOOP_TRACK, "1": LOOP_TRACK,
                       "queue": LOOP_QUEUE, "очередь": LOOP_QUEUE, "playlist": LOOP_QUEUE, "2": LOOP_QUEUE}
            if mode not in aliases:
                return await ctx.send("❓ Варианты: `off`, `track`, `queue`")
            new_mode = aliases[mode]
        else:
            # Переключаем по кругу
            idx = cycle.index(current) if current in cycle else 0
            new_mode = cycle[(idx + 1) % len(cycle)]

        _set_loop(player, new_mode)
        await ctx.send(f"{LOOP_LABELS[new_mode]}")

    # ── skip ─────────────────────────────────

    @commands.command(name='skip', aliases=['s', 'next'])
    async def skip(self, ctx, amount: int = 1):
        """Пропустить `amount` треков (по умолчанию 1)."""
        player: wavelink.Player = ctx.voice_client
        if not player or player.current is None:
            return await ctx.send("❌ Ничего не играет.")

        # При пропуске снимаем loop_track, чтобы не застрять
        if _get_loop(player) == LOOP_TRACK:
            _set_loop(player, LOOP_OFF)
            await ctx.send("🔂 Повтор трека снят.")

        skipped = 0
        # Пропускаем лишние треки из очереди
        for _ in range(amount - 1):
            if player.queue.is_empty:
                break
            player.queue.get()
            skipped += 1

        await player.skip(force=True)
        total = skipped + 1
        await ctx.send(f"⏭️ Пропущено треков: **{total}**.")

    # ── pause / resume ───────────────────────

    @commands.command(name='pause')
    async def pause(self, ctx):
        """Поставить на паузу."""
        player: wavelink.Player = ctx.voice_client
        if not player or player.current is None:
            return await ctx.send("❌ Ничего не играет.")
        if player.paused:
            return await ctx.send("Уже на паузе. Используй `a!resume`.")
        await player.pause(True)
        await ctx.send("⏸️ Пауза.")

    @commands.command(name='resume', aliases=['unpause'])
    async def resume(self, ctx):
        """Снять с паузы."""
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Ничего не играет.")
        if not player.paused:
            return await ctx.send("Не на паузе.")
        await player.pause(False)
        await ctx.send("▶️ Продолжаю.")

    # ── stop ─────────────────────────────────

    @commands.command(name='stop')
    async def stop(self, ctx):
        """Остановить музыку, очистить очередь и отключиться."""
        player: wavelink.Player = ctx.voice_client
        if player:
            player.queue.clear()
            _set_loop(player, LOOP_OFF)
            try:
                await player.disconnect()
            except Exception:
                pass
            await ctx.send("⏹️ Стоп. Очередь очищена.")
        else:
            await ctx.send("❌ Не в канале.")

    # ── volume ───────────────────────────────

    @commands.command(name='volume', aliases=['vol', 'v'])
    async def volume(self, ctx, vol: int = None):
        """Громкость от 0 до 200. Без аргумента — показать текущую."""
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале.")
        if vol is None:
            return await ctx.send(f"🔊 Текущая громкость: **{player.volume}%**")
        if not 0 <= vol <= 200:
            return await ctx.send("❌ Громкость должна быть от 0 до 200.")
        await player.set_volume(vol)
        emoji = "🔇" if vol == 0 else "🔉" if vol < 50 else "🔊"
        await ctx.send(f"{emoji} Громкость: **{vol}%**")

    # ── nowplaying ───────────────────────────

    @commands.command(name='nowplaying', aliases=['np', 'current'])
    async def nowplaying(self, ctx):
        """Показать текущий трек с прогресс-баром."""
        player: wavelink.Player = ctx.voice_client
        if not player or player.current is None:
            return await ctx.send("❌ Ничего не играет.")

        track = player.current
        pos  = player.position   # ms
        length = track.length    # ms

        bar = make_progress_bar(pos, length)
        loop_label = LOOP_LABELS.get(_get_loop(player), "")

        embed = discord.Embed(
            title="🎵 Сейчас играет",
            description=f"**[{track.title}]({track.uri})**\n*{track.author}*",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="Прогресс",
            value=f"`{fmt_time(pos)}` {bar} `{fmt_time(length)}`",
            inline=False
        )
        embed.add_field(name="Режим",     value=loop_label or "➡️ Без повтора", inline=True)
        embed.add_field(name="Громкость", value=f"🔊 {player.volume}%",          inline=True)
        embed.add_field(name="В очереди", value=str(len(player.queue)),            inline=True)

        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        await ctx.send(embed=embed)

    # ── queue ────────────────────────────────

    @commands.command(name='queue', aliases=['q'])
    async def queue_cmd(self, ctx, page: int = 1):
        """Показать очередь (10 треков на страницу)."""
        player: wavelink.Player = ctx.voice_client
        if not player or (player.queue.is_empty and player.current is None):
            return await ctx.send("📭 Очередь пуста.")

        per_page = 10
        queue_list = list(player.queue)
        total_pages = max(1, (len(queue_list) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        embed = discord.Embed(
            title=f"🎶 Очередь (страница {page}/{total_pages})",
            color=discord.Color.green()
        )

        loop = _get_loop(player)
        status = f" | {LOOP_LABELS[loop]}" if loop != LOOP_OFF else ""

        if player.current is not None:
            embed.add_field(
                name=f"▶️ Сейчас{status}",
                value=f"**{player.current.title}** — *{player.current.author}*",
                inline=False
            )

        if queue_list:
            start = (page - 1) * per_page
            chunk = queue_list[start:start + per_page]
            lines = "\n".join(
                f"`{start + i + 1}.` {t.title} — *{t.author}* `[{fmt_time(t.length)}]`"
                for i, t in enumerate(chunk)
            )
            embed.add_field(name="Далее", value=lines, inline=False)

        total_dur = sum(t.length for t in queue_list)
        embed.set_footer(text=f"Всего в очереди: {len(queue_list)} треков | {fmt_time(total_dur)}")
        await ctx.send(embed=embed)

    # ── shuffle ──────────────────────────────

    @commands.command(name='shuffle', aliases=['sh'])
    async def shuffle(self, ctx):
        """Перемешать очередь случайным образом."""
        player: wavelink.Player = ctx.voice_client
        if not player or player.queue.is_empty:
            return await ctx.send("❌ Очередь пуста.")
        player.queue.shuffle()
        await ctx.send(f"🔀 Очередь перемешана! ({len(player.queue)} треков)")

    # ── remove ───────────────────────────────

    @commands.command(name='remove', aliases=['rm'])
    async def remove(self, ctx, index: int):
        """Удалить трек из очереди по номеру (`a!remove 3`)."""
        player: wavelink.Player = ctx.voice_client
        if not player or player.queue.is_empty:
            return await ctx.send("❌ Очередь пуста.")
        if not 1 <= index <= len(player.queue):
            return await ctx.send(f"❌ Нет трека с номером {index}.")
        track = player.queue[index - 1]
        del player.queue[index - 1]
        await ctx.send(f"🗑️ Удалён: **{track.title}**")

    # ── clear ────────────────────────────────

    @commands.command(name='clear', aliases=['cls'])
    async def clear(self, ctx):
        """Очистить очередь (текущий трек продолжит играть)."""
        player: wavelink.Player = ctx.voice_client
        if not player or player.queue.is_empty:
            return await ctx.send("❌ Очередь уже пуста.")
        count = len(player.queue)
        player.queue.clear()
        await ctx.send(f"🧹 Очередь очищена ({count} треков удалено).")

    # ── move ─────────────────────────────────

    @commands.command(name='move', aliases=['mv'])
    async def move(self, ctx, from_idx: int, to_idx: int):
        """Переместить трек в очереди: `a!move 5 2`"""
        player: wavelink.Player = ctx.voice_client
        if not player or player.queue.is_empty:
            return await ctx.send("❌ Очередь пуста.")
        n = len(player.queue)
        if not (1 <= from_idx <= n and 1 <= to_idx <= n):
            return await ctx.send(f"❌ Номера должны быть от 1 до {n}.")
        track = player.queue[from_idx - 1]
        del player.queue[from_idx - 1]
        player.queue.put_at(to_idx - 1, track)
        await ctx.send(f"↕️ **{track.title}** перемещён на позицию **{to_idx}**.")

    # ── seek ─────────────────────────────────

    @commands.command(name='seek')
    async def seek(self, ctx, position: str):
        """
        Перемотать трек. Формат: `1:30` (мин:сек) или `90` (секунды).
        """
        player: wavelink.Player = ctx.voice_client
        if not player or player.current is None:
            return await ctx.send("❌ Ничего не играет.")

        try:
            if ":" in position:
                parts = position.split(":")
                ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
            else:
                ms = int(position) * 1000
        except ValueError:
            return await ctx.send("❌ Формат: `a!seek 1:30` или `a!seek 90`")

        if ms > player.current.length:
            return await ctx.send("❌ Позиция превышает длину трека.")

        await player.seek(ms)
        await ctx.send(f"⏩ Перемотал на **{fmt_time(ms)}**.")

    # ── bassboost ────────────────────────────

    @commands.command(name='bassboost', aliases=['bb'])
    async def bassboost(self, ctx, level: str = "medium"):
        """
        Бас-буст: `off` / `low` / `medium` / `high` / `extreme`
        """
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале.")

        presets = {
            "off":     [0.0] * 15,
            "low":     [0.15, 0.10, 0.05] + [0.0] * 12,
            "medium":  [0.30, 0.20, 0.10] + [0.0] * 12,
            "high":    [0.50, 0.35, 0.20, 0.05] + [0.0] * 11,
            "extreme": [0.75, 0.60, 0.45, 0.25, 0.10] + [0.0] * 10,
        }
        level = level.lower()
        if level not in presets:
            return await ctx.send("❓ Уровни: `off`, `low`, `medium`, `high`, `extreme`")

        gains = presets[level]
        bands = [wavelink.filters.EQBand(band=i, gain=g) for i, g in enumerate(gains)]
        eq = wavelink.filters.Equalizer(bands=bands)
        filters = wavelink.Filters()
        filters.equalizer.set(bands=bands)
        await player.set_filters(filters)

        emojis = {"off": "🔈", "low": "🔉", "medium": "🔊", "high": "📢", "extreme": "💥"}
        await ctx.send(f"{emojis[level]} Бас-буст: **{level.upper()}**")

    # ── nightcore ────────────────────────────

    @commands.command(name='nightcore', aliases=['nc'])
    async def nightcore(self, ctx):
        """Включить/выключить эффект Nightcore (ускорение + повышение тона)."""
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале.")

        is_nc = getattr(player, "nightcore_on", False)
        filters = wavelink.Filters()

        if not is_nc:
            filters.timescale.set(pitch=1.2, speed=1.15, rate=1.0)
            player.nightcore_on = True
            await player.set_filters(filters)
            await ctx.send("🌙 **Nightcore** включён! anime speed 🎌")
        else:
            player.nightcore_on = False
            await player.set_filters(filters)   # сброс фильтров
            await ctx.send("🌙 **Nightcore** выключен.")

    # ── 8d ───────────────────────────────────

    @commands.command(name='8d')
    async def eightd(self, ctx):
        """Включить/выключить эффект 8D-аудио (вращение)."""
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале.")

        is_8d = getattr(player, "eightd_on", False)
        filters = wavelink.Filters()

        if not is_8d:
            filters.rotation.set(rotation_hz=0.2)
            player.eightd_on = True
            await player.set_filters(filters)
            await ctx.send("🎧 **8D аудио** включено! (надень наушники)")
        else:
            player.eightd_on = False
            await player.set_filters(filters)
            await ctx.send("🎧 **8D аудио** выключено.")

    # ── resetfilters ─────────────────────────

    @commands.command(name='resetfilters', aliases=['rf', 'clearfx'])
    async def resetfilters(self, ctx):
        """Сбросить все аудио-фильтры."""
        player: wavelink.Player = ctx.voice_client
        if not player:
            return await ctx.send("❌ Бот не в канале.")
        player.nightcore_on = False
        player.eightd_on = False
        await player.set_filters(wavelink.Filters())
        await ctx.send("✨ Все фильтры сброшены.")

    # ── help ─────────────────────────────────

    @commands.command(name='help', aliases=['h', 'команды'])
    async def help_cmd(self, ctx):
        """Список всех команд бота."""
        embed = discord.Embed(
            title="🎵 Команды музыкального бота",
            color=discord.Color.blurple()
        )
        sections = {
            "▶️ Воспроизведение": [
                ("`a!play <запрос>`",      "Найти и поставить трек / плейлист"),
                ("`a!playskip <запрос>`",  "Найти трек и сразу проиграть его"),
                ("`a!join`",               "Подключиться к каналу"),
                ("`a!leave`",              "Отключиться"),
                ("`a!stop`",               "Стоп + очистить очередь"),
                ("`a!pause` / `a!resume`", "Пауза / продолжить"),
                ("`a!skip [N]`",           "Пропустить N треков"),
                ("`a!seek <1:30>`",        "Перемотать на время"),
            ],
            "🔁 Повтор": [
                ("`a!loop`",               "Переключить режим: off → track → queue"),
                ("`a!loop track`",         "Повторять текущий трек"),
                ("`a!loop queue`",         "🔁 Повторять всю очередь"),
                ("`a!loop off`",           "Без повтора"),
            ],
            "📃 Очередь": [
                ("`a!queue [стр]`",        "Показать очередь"),
                ("`a!shuffle`",            "Перемешать"),
                ("`a!remove <N>`",         "Удалить трек по номеру"),
                ("`a!move <от> <куда>`",   "Переставить трек"),
                ("`a!clear`",              "Очистить очередь"),
            ],
            "🎛️ Звук": [
                ("`a!volume [0-200]`",     "Громкость"),
                ("`a!bassboost [уровень]`","Бас-буст: off/low/medium/high/extreme"),
                ("`a!nightcore`",          "Эффект Nightcore"),
                ("`a!8d`",                 "8D аудио"),
                ("`a!resetfilters`",       "Сбросить все фильтры"),
            ],
            "ℹ️ Инфо": [
                ("`a!np`",                 "Текущий трек + прогресс-бар"),
            ],
        }
        for section, commands_list in sections.items():
            value = "\n".join(f"{cmd} — {desc}" for cmd, desc in commands_list)
            embed.add_field(name=section, value=value, inline=False)

        embed.set_footer(text="Префикс: a!  •  Приятного прослушивания! 🎶")
        await ctx.send(embed=embed)


# ─────────────────────────────────────────────
#  Глобальный обработчик ошибок команд
# ─────────────────────────────────────────────
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Игнорируем неизвестные команды
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ Не хватает аргумента: `{error.param.name}`")
    if isinstance(error, commands.CommandInvokeError):
        cause = error.original
        if "LavalinkException" in type(cause).__name__ or "wavelink" in type(cause).__module__:
            return await ctx.send(
                "❌ **Ошибка Lavalink:** нода потеряла сессию или недоступна.\n"
                "Попробуй `a!leave`, затем `a!play` снова."
            )
        await ctx.send(f"❌ Ошибка выполнения команды: `{cause}`")
        raise error  # Логируем в консоль


# ─────────────────────────────────────────────
#  Запуск
# ─────────────────────────────────────────────

# setup_hook вызывается ДО on_ready — команды регистрируются правильно
@bot.event
async def setup_hook():
    music_cog = MusicCog(bot)
    await bot.add_cog(music_cog)
    # Запускаем подключение к нодам в фоне (они требуют wait_until_ready внутри)
    bot.loop.create_task(music_cog.setup_nodes())
    print("✅ Cog загружен, ноды подключаются...")


@bot.event
async def on_ready():
    print(f'Бот запущен: {bot.user}')
    print('------')
    await bot.change_presence(activity=discord.Game(name="a!help | a!play"))
    print("✅ Все системы готовы.")


if TOKEN:
    bot.run(TOKEN)
else:
    print("ОШИБКА: Токен не найден в .env")
