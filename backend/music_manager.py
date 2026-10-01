"""
music_manager.py
Self-Music backend for Voicecord.
Uses wavelink (Lavalink) per-token voice channel playback via aiohttp.
Each token gets its own wavelink player hooked up through the token's VC connection.
"""
import asyncio
import logging
import time
import aiohttp

logger = logging.getLogger("music_manager")

# ── Lavalink Config helpers ────────────────────────────────────────────────────
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent
LAVALINK_CONFIG_FILE = BASE_DIR / "lavalink_config.json"

def load_lavalink_config() -> dict:
    defaults = {
        "uri": "http://lavalinkv4.serenetia.com:80",
        "password": "https://seretia.link/discord",
    }
    if LAVALINK_CONFIG_FILE.exists():
        try:
            with open(LAVALINK_CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except Exception:
            pass
    return defaults

def save_lavalink_config(cfg: dict):
    try:
        with open(LAVALINK_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving lavalink config: {e}")


# ── Per-Token Music State ──────────────────────────────────────────────────────

class TokenMusicState:
    """Holds music playback state for a single token (self-bot)."""

    def __init__(self, token_str: str):
        self.token_str = token_str
        self.queue: list = []          # list of track dicts
        self.current: dict | None = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.loop: bool = False
        self.volume: int = 100
        self.position_ms: int = 0
        self.started_at: float = 0.0  # epoch when track started
        # Lavalink REST session
        self.session_id: str | None = None
        self.player_guild_id: str | None = None
        self.node_session: str | None = None
        self.user_id: str = ""
        self.lavalink_session_id: str | None = None
        self.ws_task: asyncio.Task | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None

    def get_position(self) -> int:
        if self.is_playing and not self.is_paused and self.started_at > 0:
            elapsed = int((time.time() - self.started_at) * 1000)
            return self.position_ms + elapsed
        return self.position_ms

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "queue": self.queue,
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "loop": self.loop,
            "volume": self.volume,
            "position": self.get_position(),
        }


# ── Lavalink REST Client ───────────────────────────────────────────────────────

class LavalinkClient:
    """
    Lightweight async Lavalink v4 REST client.
    Handles track search, player control (volume, pause, stop, seek).
    The actual voice connection is handled by the DiscordClient (bot.py).
    """

    def __init__(self):
        self._cfg = load_lavalink_config()
        self._base_url = self._cfg["uri"].rstrip("/")
        self._password = self._cfg["password"]
        self._session: aiohttp.ClientSession | None = None
        self._lavalink_session_id: str | None = None

    def _headers(self) -> dict:
        return {
            "Authorization": self._password,
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def check_status(self) -> dict:
        """Returns node health stats."""
        cfg = load_lavalink_config()
        self._base_url = cfg["uri"].rstrip("/")
        self._password = cfg["password"]
        try:
            s = await self._get_session()
            start = time.monotonic()
            async with s.get(
                f"{self._base_url}/version",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=4),
            ) as r:
                latency_ms = round((time.monotonic() - start) * 1000)
                if r.status == 200:
                    return {"online": True, "latency_ms": latency_ms, "version": await r.text()}
                return {"online": False, "latency_ms": latency_ms, "error": f"HTTP {r.status}"}
        except Exception as e:
            return {"online": False, "latency_ms": -1, "error": str(e)}

    async def get_stats(self) -> dict:
        """Returns Lavalink node stats (cpu, ram, uptime, players)."""
        cfg = load_lavalink_config()
        self._base_url = cfg["uri"].rstrip("/")
        self._password = cfg["password"]
        try:
            s = await self._get_session()
            async with s.get(
                f"{self._base_url}/v4/stats",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            logger.error(f"Lavalink stats error: {e}")
        return {}

    async def search(self, query: str, limit: int = 8) -> list:
        """Search for tracks. Returns list of track dicts."""
        cfg = load_lavalink_config()
        self._base_url = cfg["uri"].rstrip("/")
        self._password = cfg["password"]
        # Detect URL vs keyword search
        if query.startswith("http"):
            identifier = query
        else:
            identifier = f"ytsearch:{query}"

        try:
            s = await self._get_session()
            async with s.get(
                f"{self._base_url}/v4/loadtracks",
                params={"identifier": identifier},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        except Exception as e:
            logger.error(f"Lavalink search error: {e}")
            return []

        load_type = data.get("loadType", "")
        tracks = []

        if load_type == "track":
            t = data.get("data", {})
            info = t.get("info", {})
            tracks = [self._format_track(t, info)]
        elif load_type == "playlist":
            for t in (data.get("data", {}).get("tracks", []))[:limit]:
                info = t.get("info", {})
                tracks.append(self._format_track(t, info))
        elif load_type in ("search", "results"):
            for t in (data.get("data", []))[:limit]:
                info = t.get("info", {})
                tracks.append(self._format_track(t, info))

        return tracks[:limit]

    def _format_track(self, raw: dict, info: dict) -> dict:
        title = info.get("title", "Unknown Track")
        author = info.get("author", "Unknown")
        length = info.get("length", 0)
        uri = info.get("uri", "")
        yt_id = info.get("identifier", "")
        thumbnail = ""
        if yt_id and "youtube" in uri.lower():
            thumbnail = f"https://img.youtube.com/vi/{yt_id}/mqdefault.jpg"
        return {
            "encoded": raw.get("encoded", ""),
            "title": title,
            "author": author,
            "length_ms": length,
            "uri": uri,
            "thumbnail": thumbnail,
            "identifier": yt_id,
        }

    async def update_player(
        self,
        guild_id: str,
        encoded_track: str | None = None,
        voice_data: dict | None = None,
        volume: int | None = None,
        paused: bool | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Sends player update to Lavalink v4 REST API to stream audio in VC."""
        cfg = load_lavalink_config()
        self._base_url = cfg["uri"].rstrip("/")
        self._password = cfg["password"]

        sess_id = session_id or "voicecord_session"
        url = f"{self._base_url}/v4/sessions/{sess_id}/players/{guild_id}?noReplace=false"
        payload = {}

        if encoded_track is not None:
            payload["track"] = {"encoded": encoded_track} if encoded_track else {"encoded": None}

        if voice_data and voice_data.get("token") and voice_data.get("endpoint"):
            endpoint = voice_data.get("endpoint", "")
            if ":" in endpoint:
                endpoint = endpoint.split(":")[0]
            if endpoint.startswith("wss://"):
                endpoint = endpoint[6:]
            elif endpoint.startswith("ws://"):
                endpoint = endpoint[5:]

            payload["voice"] = {
                "token": voice_data.get("token"),
                "endpoint": endpoint,
                "sessionId": voice_data.get("session_id", "")
            }

        if volume is not None:
            payload["volume"] = volume

        if paused is not None:
            payload["paused"] = paused

        logger.info(f"Sending Lavalink update_player to {url}: {json.dumps(payload)}")
        try:
            s = await self._get_session()
            async with s.patch(
                url,
                json=payload,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                txt = await r.text()
                logger.info(f"Lavalink update_player status {r.status}: {txt[:200]}")
                if r.status in (200, 204):
                    return {"success": True, "data": json.loads(txt) if txt else {}}
                return {"success": False, "error": f"HTTP {r.status}: {txt}"}
        except Exception as e:
            logger.error(f"Lavalink update_player error: {e}")
            return {"success": False, "error": str(e)}

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


# ── Music Manager (Singleton) ──────────────────────────────────────────────────

class MusicManager:
    """
    Central music manager for all tokens.
    Provides high-level play/pause/stop/skip/loop/volume/queue APIs.
    Does NOT handle the actual WebSocket voice connection — that stays with bot.py.
    Relies on Lavalink REST for audio decoding/streaming state tracking.
    """

    def __init__(self):
        self._states: dict[str, TokenMusicState] = {}
        self.lavalink = LavalinkClient()

    def _get_state(self, token_str: str) -> TokenMusicState:
        if token_str not in self._states:
            self._states[token_str] = TokenMusicState(token_str)
        return self._states[token_str]

    # ── Search ─────────────────────────────────────────────────────────────────
    async def search(self, query: str, limit: int = 8) -> list:
        return await self.lavalink.search(query, limit)

    def get_lavalink_ws_url(self, base_url: str) -> str:
        url = base_url.rstrip("/")
        if url.startswith("http://"):
            return "ws://" + url[7:] + "/v4/websocket"
        elif url.startswith("https://"):
            return "wss://" + url[8:] + "/v4/websocket"
        elif url.startswith("ws://") or url.startswith("wss://"):
            return url + "/v4/websocket"
        return "ws://" + url + "/v4/websocket"

    async def ensure_lavalink_connected(self, token_str: str, user_id: str) -> str | None:
        state = self._get_state(token_str)
        if user_id:
            state.user_id = user_id

        if state.ws_task and not state.ws_task.done() and state.lavalink_session_id:
            return state.lavalink_session_id

        if state.ws_task and not state.ws_task.done():
            state.ws_task.cancel()

        state.ws_task = asyncio.create_task(self._connect_lavalink_ws(state))
        for _ in range(30):
            if state.lavalink_session_id:
                break
            await asyncio.sleep(0.1)

        return state.lavalink_session_id

    async def _connect_lavalink_ws(self, state: TokenMusicState):
        cfg = load_lavalink_config()
        ws_url = self.get_lavalink_ws_url(cfg["uri"])
        headers = {
            "Authorization": cfg["password"],
            "User-Id": state.user_id or "100000000000000000",
            "Client-Name": "Voicecord/1.0"
        }
        try:
            session = await self.lavalink._get_session()
            async with session.ws_connect(ws_url, headers=headers) as ws:
                state.ws = ws
                logger.info(f"Connected to Lavalink WS for user_id={state.user_id}")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        op = data.get("op")
                        if op == "ready":
                            state.lavalink_session_id = data.get("sessionId")
                            logger.info(f"Lavalink session ID received: {state.lavalink_session_id}")
                        elif op == "event":
                            evt_type = data.get("type")
                            if evt_type == "TrackEndEvent":
                                reason = data.get("reason", "")
                                if reason in ("finished", "loadFailed"):
                                    await self.skip(state.token_str)
                            elif evt_type in ("TrackExceptionEvent", "TrackStuckEvent"):
                                logger.error(f"Lavalink track event error: {data}")
                                await self.skip(state.token_str)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
        except Exception as e:
            logger.error(f"Lavalink WS connection error: {e}")
        finally:
            state.ws = None
            state.lavalink_session_id = None

    # ── Play ───────────────────────────────────────────────────────────────────
    async def play(self, token_str: str, query: str, vc_state: dict, voice_data: dict | None = None, user_id: str = "") -> dict:
        """
        If currently playing → add to queue.
        If not → play immediately via Lavalink.
        vc_state: dict with keys 'connected', 'guild_id', 'channel_id'
        """
        if not vc_state.get("connected"):
            return {"success": False, "error": "Token is not in a voice channel. Please connect it to a VC first."}

        state = self._get_state(token_str)
        tracks = await self.lavalink.search(query, limit=1)
        if not tracks:
            return {"success": False, "error": "No results found for that query."}

        track = tracks[0]
        guild_id = vc_state.get("guild_id")

        if state.is_playing:
            state.queue.append(track)
            return {"success": True, "action": "queued", "track": track, "position": len(state.queue)}
        else:
            state.current = track
            state.is_playing = True
            state.is_paused = False
            state.started_at = time.time()
            state.position_ms = 0

            if guild_id:
                sess_id = await self.ensure_lavalink_connected(token_str, user_id)
                await self.lavalink.update_player(
                    guild_id=guild_id,
                    encoded_track=track.get("encoded"),
                    voice_data=voice_data,
                    volume=state.volume,
                    paused=False,
                    session_id=sess_id or f"voicecord_{guild_id}"
                )

            return {"success": True, "action": "playing", "track": track}

    # ── Pause / Resume ────────────────────────────────────────────────────────
    async def pause(self, token_str: str, guild_id: str | None = None) -> dict:
        state = self._get_state(token_str)
        if not state.is_playing:
            return {"success": False, "error": "Nothing is playing."}
        state.position_ms = state.get_position()
        state.started_at = 0.0
        state.is_paused = True
        if guild_id:
            await self.lavalink.update_player(
                guild_id=guild_id,
                paused=True,
                session_id=f"voicecord_{guild_id}"
            )
        return {"success": True, "action": "paused"}

    async def resume(self, token_str: str, guild_id: str | None = None) -> dict:
        state = self._get_state(token_str)
        if not state.is_playing:
            return {"success": False, "error": "Nothing is playing."}
        state.is_paused = False
        state.started_at = time.time()
        if guild_id:
            await self.lavalink.update_player(
                guild_id=guild_id,
                paused=False,
                session_id=f"voicecord_{guild_id}"
            )
        return {"success": True, "action": "resumed"}

    # ── Stop ──────────────────────────────────────────────────────────────────
    async def stop(self, token_str: str, guild_id: str | None = None) -> dict:
        state = self._get_state(token_str)
        state.is_playing = False
        state.is_paused = False
        state.current = None
        state.queue = []
        state.position_ms = 0
        state.started_at = 0.0
        if guild_id:
            await self.lavalink.update_player(
                guild_id=guild_id,
                encoded_track="",
                session_id=f"voicecord_{guild_id}"
            )
        return {"success": True, "action": "stopped"}

    # ── Skip ──────────────────────────────────────────────────────────────────
    async def skip(self, token_str: str, guild_id: str | None = None, voice_data: dict | None = None) -> dict:
        state = self._get_state(token_str)
        if not state.queue:
            if state.loop and state.current:
                # loop current
                state.started_at = time.time()
                state.position_ms = 0
                state.is_paused = False
                if guild_id and state.current.get("encoded"):
                    await self.lavalink.update_player(
                        guild_id=guild_id,
                        encoded_track=state.current.get("encoded"),
                        voice_data=voice_data,
                        session_id=f"voicecord_{guild_id}"
                    )
                return {"success": True, "action": "loop_restart", "track": state.current}
            state.is_playing = False
            state.current = None
            if guild_id:
                await self.lavalink.update_player(
                    guild_id=guild_id,
                    encoded_track="",
                    session_id=f"voicecord_{guild_id}"
                )
            return {"success": True, "action": "queue_empty"}

        next_track = state.queue.pop(0)
        if state.loop and state.current:
            state.queue.append(state.current)
        state.current = next_track
        state.is_playing = True
        state.is_paused = False
        state.started_at = time.time()
        state.position_ms = 0
        if guild_id and next_track.get("encoded"):
            await self.lavalink.update_player(
                guild_id=guild_id,
                encoded_track=next_track.get("encoded"),
                voice_data=voice_data,
                volume=state.volume,
                paused=False,
                session_id=f"voicecord_{guild_id}"
            )
        return {"success": True, "action": "skipped", "track": next_track}

    # ── Loop ──────────────────────────────────────────────────────────────────
    async def toggle_loop(self, token_str: str) -> dict:
        state = self._get_state(token_str)
        state.loop = not state.loop
        return {"success": True, "loop": state.loop}

    # ── Volume ────────────────────────────────────────────────────────────────
    async def set_volume(self, token_str: str, volume: int, guild_id: str | None = None) -> dict:
        volume = max(0, min(200, volume))
        state = self._get_state(token_str)
        state.volume = volume
        if guild_id:
            await self.lavalink.update_player(
                guild_id=guild_id,
                volume=volume,
                session_id=f"voicecord_{guild_id}"
            )
        return {"success": True, "volume": volume}

    # ── Queue ─────────────────────────────────────────────────────────────────
    async def remove_from_queue(self, token_str: str, index: int) -> dict:
        state = self._get_state(token_str)
        if index < 0 or index >= len(state.queue):
            return {"success": False, "error": "Invalid queue index."}
        removed = state.queue.pop(index)
        return {"success": True, "removed": removed}

    async def clear_queue(self, token_str: str) -> dict:
        state = self._get_state(token_str)
        state.queue = []
        return {"success": True}

    # ── Get state ─────────────────────────────────────────────────────────────
    def get_state(self, token_str: str) -> dict:
        return self._get_state(token_str).to_dict()

    async def close(self):
        await self.lavalink.close()


# Singleton instance
music_manager = MusicManager()
