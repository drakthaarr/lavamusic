import discord
from discord.ext import commands
import wavelink
import os
from dotenv import load_dotenv
import asyncio
import random
import logging

# ─────────────────────────────────────────────
#  Логгер
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] [%(levelname)-7s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("MusicBot")
# Приглушаем шум от discord.py и wavelink чтобы наши логи были заметны
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("wavelink").setLevel(logging.DEBUG)  # wavelink оставляем DEBUG — он полезен

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
            {"id": "Serenetia",    "uri": "http://lavalinkv4.serenetia.com:80",      "pwd": "https://seretia.link/discord"},
            {"id": "Hatry-Node",   "uri": "http://lavahatry4.techbyte.host:3000",   "pwd": "naig.is-a.dev"},
            {"id": "Jirayu-Node",  "uri": "http://lavalink.jirayu.net:13592",       "pwd": "youshallnotpass"},
            {"id": "FreeLava-1",   "uri": "http://lavalink1.oops.wtf:80",           "pwd": "www.freelavalink.ga"},
            {"id": "FreeLava-2",   "uri": "http://lavalink.lexnet.cc:2333",         "pwd": "lexn3tl@val!nk"},
        ]
        wavelink_nodes = [
            wavelink.Node(identifier=n["id"], uri=n["uri"], password=n["pwd"])
            for n in nodes_data
        ]
        log.info(f"🔄 Подключаемся к {len(wavelink_nodes)} серверам...")
        connected = 0
        for node in wavelink_nodes:
            try:
                log.debug(f"Пробуем ноду {node.identifier} → {node.uri}")
                await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100)
                connected += 1
                log.info(f"✅ Нода {node.identifier} подключена")
            except Exception as e:
                log.warning(f"⚠️ Нода {node.identifier} недоступна: {e}")
        if connected == 0:
            log.critical("❌ Ни одна нода не подключилась! Музыка работать не будет.")
        else:
            log.info(f"✅ Подключено нод: {connected}/{len(wavelink_nodes)}")

    # ── события ──────────────────────────────

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        log.info(f"✅ Нода '{payload.node.identifier}' готова! URI: {payload.node.uri}")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        t = payload.track
        log.info(f"▶️  TRACK START | '{t.title}' by {t.author} | длина={t.length}ms | uri={t.uri}")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        t = payload.track
        log.info(f"⏹️  TRACK END   | '{t.title}' | reason={payload.reason} | queue_size={len(player.queue) if player else '?'}")

        if not player:
            log.warning("track_end: player is None, пропускаем")
            return

        loop = _get_loop(player)
        log.debug(f"track_end: loop_mode={loop}")

        if loop == LOOP_TRACK:
            log.debug("track_end: повторяем трек")
            await player.play(payload.track)

        elif loop == LOOP_QUEUE:
            player.queue.put(payload.track)
            if not player.queue.is_empty:
                next_track = player.queue.get()
                log.debug(f"track_end: loop_queue → играем '{next_track.title}'")
                await player.play(next_track)

        else:
            if not player.queue.is_empty:
                next_track = player.queue.get()
                log.debug(f"track_end: играем следующий → '{next_track.title}'")
                await player.play(next_track)
            else:
                log.info("track_end: очередь пуста, воспроизведение остановлено")

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        t = payload.track
        log.error(f"💥 TRACK EXCEPTION | '{t.title}' | {payload.exception}")
        player: wavelink.Player = payload.player
        if not player:
            return
        channel = getattr(player, "_text_channel", None)

        # Пробуем найти тот же трек через YouTube Music
        retry_query = f"{t.author} {t.title}"
        log.info(f"EXCEPTION RETRY: ищем через YouTube Music → '{retry_query}'")

        retry_track = None
        for source, label in [
            (wavelink.TrackSource.YouTubeMusic, "YouTube Music"),
            (wavelink.TrackSource.YouTube,      "YouTube"),
        ]:
            try:
                results = await wavelink.Playable.search(retry_query, source=source)
                if results:
                    retry_track = results[0]
                    log.info(f"EXCEPTION RETRY: найдено через {label} → '{retry_track.title}'")
                    break
            except Exception as e:
                log.warning(f"EXCEPTION RETRY: {label} упал: {e}")

        if retry_track:
            if channel:
                await channel.send(
                    f"⚠️ Нода не смогла загрузить **{t.title}** (`{payload.exception}`).\n"
                    f"🔄 Нашёл через YouTube: **{retry_track.title}** — воспроизвожу..."
                )
            try:
                await player.play(retry_track)
            except Exception as e:
                log.error(f"EXCEPTION RETRY: play упал: {e}")
        else:
            if channel:
                await channel.send(f"💥 Не смог загрузить **{t.title}** и не нашёл замену. Пропускаю...")
            if not player.queue.is_empty:
                await player.play(player.queue.get())

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload):
        log.error(f"🔁 TRACK STUCK     | трек='{payload.track.title}' | threshold={payload.threshold}ms")

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
        log.info(f"▶  play | user={ctx.author} | query='{query}'")

        try:
            node = wavelink.Pool.get_node()
            log.debug(f"play: используем ноду '{node.identifier}' | status={node.status}")
        except wavelink.InvalidNodeException:
            log.error("play: нет доступных нод!")
            return await ctx.send("⚠️ Серверы ещё подключаются. Подождите немного.")

        if not ctx.voice_client:
            if ctx.author.voice:
                log.debug(f"play: подключаемся к каналу '{ctx.author.voice.channel}'")
                try:
                    await ctx.author.voice.channel.connect(cls=wavelink.Player)
                    log.info(f"play: подключились к '{ctx.author.voice.channel}'")
                except Exception as e:
                    log.error(f"play: ошибка подключения к каналу: {e}", exc_info=True)
                    return await ctx.send(f"❌ Ошибка подключения: {e}")
            else:
                return await ctx.send("❌ Зайдите в голосовой канал!")

        player: wavelink.Player = ctx.voice_client
        player.autoplay = wavelink.AutoPlayMode.disabled
        player._text_channel = ctx.channel  # сохраняем для уведомлений из событий

        log.debug(f"play: player.current={player.current} | player.playing={player.playing} | queue={len(player.queue)}")

        await ctx.send(f"🔍 Ищу: `{query}`...")

        # Цепочка источников: если один не даёт результат — пробуем следующий
        tracks = None
        source_used = None

        if query.startswith("http"):
            # Прямая ссылка — ищем как есть
            try:
                tracks = await wavelink.Playable.search(query)
                source_used = "URL"
                log.debug(f"play: URL-поиск вернул {len(tracks) if tracks else 0} результатов")
            except Exception as e:
                log.error(f"play: URL-поиск упал: {e}", exc_info=True)
        else:
            # Текстовый запрос — пробуем SoundCloud, потом YouTube
            for source, label in [
                (wavelink.TrackSource.SoundCloud, "SoundCloud"),
                (wavelink.TrackSource.YouTube,    "YouTube"),
            ]:
                try:
                    results = await wavelink.Playable.search(query, source=source)
                    if results:
                        tracks = results
                        source_used = label
                        log.info(f"play: найдено через {label}: {len(tracks)} результатов")
                        break
                    else:
                        log.warning(f"play: {label} вернул пустой список")
                except Exception as e:
                    log.warning(f"play: {label} упал с ошибкой: {e}")

        if not tracks:
            log.warning(f"play: ничего не найдено для '{query}' ни в одном источнике")
            return await ctx.send("😕 Ничего не найдено ни на SoundCloud, ни на YouTube.")

        is_playing = player.current is not None
        log.debug(f"play: is_playing={is_playing}")

        if isinstance(tracks, wavelink.Playlist):
            first_track = None
            for i, track in enumerate(tracks):
                if i == 0 and not is_playing:
                    first_track = track
                else:
                    player.queue.put(track)
            msg = f"📃 Добавлен плейлист **{tracks.name}** ({len(tracks)} треков)."
            if first_track:
                log.info(f"play: запускаем первый трек плейлиста '{first_track.title}'")
                try:
                    await player.play(first_track)
                    log.info(f"play: player.play() вызван успешно")
                    await ctx.send(msg)
                except Exception as e:
                    log.error(f"play: player.play() упал: {e}", exc_info=True)
                    await ctx.send(f"❌ Не могу воспроизвести: `{e}`")
            else:
                await ctx.send(msg)
        else:
            track = tracks[0]
            log.info(f"play: найден трек '{track.title}' by '{track.author}' | длина={track.length}ms | uri={track.uri}")
            if not is_playing:
                log.info(f"play: ничего не играет → вызываем player.play()")
                try:
                    await player.play(track)
                    log.info(f"play: player.play() вызван | player.current={player.current}")
                    await ctx.send(f"▶️ Играю: **{track.title}** — *{track.author}* [источник: {source_used}]")

                    original_title  = track.title
                    original_author = track.author

                    async def _check_and_retry():
                        # Ждём 4 сек и запоминаем позицию
                        await asyncio.sleep(4)
                        pos1 = player.position
                        log.debug(f"_check_and_retry: позиция через 4 сек = {pos1}ms")

                        # Ждём ещё 3 сек и смотрим — двинулась ли позиция
                        await asyncio.sleep(3)
                        pos2 = player.position
                        log.debug(f"_check_and_retry: позиция через 7 сек = {pos2}ms")

                        if pos2 > pos1 and pos2 > 0:
                            log.info(f"_check_and_retry: трек реально играет ✅ ({pos1}ms → {pos2}ms)")
                            return

                        log.error(
                            f"ТИХИЙ СБОЙ: позиция не двигается ({pos1}ms → {pos2}ms) | "
                            f"player.playing={player.playing} | player.current={player.current}"
                        )

                        await ctx.send("⚠️ Нода не воспроизводит. Пробую другие источники и ноды...")

                        retry_query = f"{original_author} {original_title}"
                        all_nodes = list(wavelink.Pool.nodes.values())
                        log.info(f"RETRY: доступно нод: {[n.identifier for n in all_nodes]}")

                        for node in all_nodes:
                            if node.status != wavelink.NodeStatus.CONNECTED:
                                log.warning(f"RETRY: нода {node.identifier} не подключена, пропускаем")
                                continue

                            for source, label in [
                                (wavelink.TrackSource.YouTubeMusic, "YouTube Music"),
                                (wavelink.TrackSource.YouTube,      "YouTube"),
                            ]:
                                try:
                                    log.info(f"RETRY: нода={node.identifier} | источник={label} | запрос='{retry_query}'")
                                    results = await wavelink.Playable.search(retry_query, source=source)
                                    if not results:
                                        log.warning(f"RETRY: {label} вернул пустой список")
                                        continue

                                    retry_track = results[0]
                                    log.info(f"RETRY: найден '{retry_track.title}' через {label} на ноде {node.identifier}")

                                    await player.move_to(node)
                                    await asyncio.sleep(1)
                                    await player.play(retry_track)

                                    # Проверяем позицию снова
                                    await asyncio.sleep(4)
                                    p1 = player.position
                                    await asyncio.sleep(3)
                                    p2 = player.position

                                    if p2 > p1 and p2 > 0:
                                        await ctx.send(f"✅ Заработало через **{label}** (нода: `{node.identifier}`): **{retry_track.title}**")
                                        log.info(f"RETRY: успех на {node.identifier} / {label} ✅")
                                        return
                                    else:
                                        log.warning(f"RETRY: {node.identifier} + {label} — позиция всё равно не двигается ({p1} → {p2})")

                                except Exception as e:
                                    log.warning(f"RETRY: нода={node.identifier} + {label} упал: {e}")

                        log.error("RETRY: все ноды и источники исчерпаны")
                        await ctx.send(
                            "❌ **Ни одна нода не смогла воспроизвести трек.**\n"
                            "Все публичные Lavalink-серверы могут блокировать этот источник.\n"
                            "Попробуй вставить прямую ссылку на YouTube."
                        )

                    asyncio.create_task(_check_and_retry())

                except Exception as e:
                    log.error(f"play: player.play() упал: {e}", exc_info=True)
                    await ctx.send(f"❌ Не могу воспроизвести: `{e}`")
            else:
                log.info(f"play: уже играет → добавляем в очередь")
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
