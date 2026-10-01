import asyncio
import contextlib
import json
import logging
import time
import aiohttp
from typing import Dict, Optional
from urllib.parse import quote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


class DiscordClient:
    def __init__(self, raw_token: str, config: dict):
        self.raw_token = raw_token.strip()
        # Handle formatted tokens (e.g. email:pass:token or id:pass:token)
        parts = self.raw_token.split(":")
        self.token = parts[-1] if len(parts) >= 3 or len(parts) == 2 else self.raw_token

        self.config = config
        self.ws = None
        self.heartbeat_task = None
        self._start_task: Optional[asyncio.Task] = None
        self.running = False
        self.session = None
        self._internal_start_time = int(time.time())
        self.vc_state: dict = {}
        self._guild_cache: Dict[str, dict] = {}
        self.user_profile: dict = {}
        self._user_id: str = ""  # filled on READY, used to filter VOICE_STATE_UPDATE
        self.session_id: str = ""
        self.voice_data: dict = {}

    async def get_app_assets(self, app_id: str) -> list:
        if not hasattr(self, "_app_assets_cache"):
            self._app_assets_cache = {}
        if app_id in self._app_assets_cache:
            return self._app_assets_cache[app_id]
        if not self.session or self.session.closed:
            return []
        headers = {"Authorization": self.token}
        url = f"https://discord.com/api/v10/oauth2/applications/{app_id}/assets"
        try:
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    assets = await resp.json()
                    self._app_assets_cache[app_id] = assets
                    return assets
        except Exception as e:
            logger.error(f"Error fetching app assets: {e}")
        return []

    def resolve_asset(self, value: str, assets_list: list) -> str:
        if not value:
            return value
        v = value.strip()
        if v.startswith("http://") or v.startswith("https://"):
            return f"mp:external/{v}"
        for asset in assets_list:
            if asset.get("name") == v:
                return asset.get("id")
        return v

    async def start(self):
        self.running = True
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        while self.running:
            try:
                await self.connect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self.running:
                    break
                logger.error(f"[{self.token[:10]}...] Connection error: {e}")
                if self.running:
                    await asyncio.sleep(5)

    async def stop(self):
        self.running = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            self.heartbeat_task = None
        if self.ws and not self.ws.closed:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self.session and not self.session.closed:
            try:
                await self.session.close()
            except Exception:
                pass
        self.ws = None
        self.session = None

    async def connect(self):
        uri = "wss://gateway.discord.gg/?v=10&encoding=json"
        async with self.session.ws_connect(uri) as ws:
            self.ws = ws
            hello = await ws.receive_json()
            heartbeat_interval = hello["d"]["heartbeat_interval"]

            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            self.heartbeat_task = asyncio.create_task(self.heartbeat(heartbeat_interval))

            await self.identify()

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    t = data.get("t")
                    if t == "READY":
                        logger.info(f"[{self.token[:10]}...] Ready!")
                        ready_d = data.get("d", {})
                        self.user_profile = ready_d.get("user", {})
                        self._user_id = self.user_profile.get("id", "")
                        self.session_id = ready_d.get("session_id", "")
                        await self.update_presence()
                        await self.update_voice()
                        # Optimistically pre-populate vc_state from saved config
                        # so the UI shows 'connected' immediately without waiting
                        # for a VOICE_STATE_UPDATE from Discord.
                        self._apply_config_vc_state()
                    elif t == "VOICE_STATE_UPDATE":
                        vsu_data = data.get("d", {})
                        vsu_user_id = vsu_data.get("user_id", "")
                        # Only process voice state updates for this specific token user
                        if (self._user_id and vsu_user_id == self._user_id) or (not self._user_id and self.user_profile.get("id") and vsu_user_id == self.user_profile.get("id")):
                            if vsu_data.get("session_id"):
                                self.session_id = vsu_data.get("session_id")
                            self.voice_data["session_id"] = self.session_id
                            self.voice_data["guild_id"] = vsu_data.get("guild_id")
                            self.voice_data["channel_id"] = vsu_data.get("channel_id")
                            await self._handle_voice_state(vsu_data)
                    elif t == "VOICE_SERVER_UPDATE":
                        vsu_data = data.get("d", {})
                        self.voice_data["token"] = vsu_data.get("token")
                        self.voice_data["endpoint"] = vsu_data.get("endpoint")
                        self.voice_data["guild_id"] = vsu_data.get("guild_id")
                        if not self.voice_data.get("session_id"):
                            self.voice_data["session_id"] = self.session_id
                        logger.info(f"[{self.token[:10]}...] VOICE_SERVER_UPDATE: endpoint={vsu_data.get('endpoint')}")
                    elif t == "GUILD_CREATE":
                        self._cache_guild(data.get("d", {}))
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    def _cache_guild(self, guild_data: dict):
        guild_id = guild_data.get("id")
        if not guild_id:
            return
        channels = {}
        for ch in guild_data.get("channels", []):
            channels[ch["id"]] = ch.get("name", ch["id"])
        icon_hash = guild_data.get("icon")
        icon_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png" if icon_hash else None
        self._guild_cache[guild_id] = {
            "name": guild_data.get("name", guild_id),
            "icon_url": icon_url,
            "channels": channels
        }

    def _apply_config_vc_state(self):
        """Pre-populate vc_state from saved config so UI shows connected
        immediately after READY, before Discord sends VOICE_STATE_UPDATE."""
        voice = self.config.get("voice", {})
        guild_id = voice.get("guild_id", "").strip()
        channel_id = voice.get("channel_id", "").strip()
        if guild_id and channel_id:
            guild_info = self._guild_cache.get(guild_id, {})
            self.vc_state = {
                "guild_id": guild_id,
                "channel_id": channel_id,
                "guild_name": guild_info.get("name", guild_id),
                "guild_icon": guild_info.get("icon_url"),
                "channel_name": guild_info.get("channels", {}).get(channel_id, channel_id),
                "connected": True,
                "self_video": voice.get("self_video", False),
                "self_mute": voice.get("self_mute", False),
                "self_deaf": voice.get("self_deaf", False),
                "from_config": True,  # flag: real Discord event will overwrite this
            }

    async def _handle_voice_state(self, d: dict):
        guild_id = d.get("guild_id")
        channel_id = d.get("channel_id")
        if channel_id:
            guild_info = self._guild_cache.get(guild_id, {})
            self.vc_state = {
                "guild_id": guild_id,
                "channel_id": channel_id,
                "guild_name": guild_info.get("name", guild_id),
                "guild_icon": guild_info.get("icon_url"),
                "channel_name": guild_info.get("channels", {}).get(channel_id, channel_id),
                "connected": True,
                "self_video": d.get("self_video", False),
                "self_mute": d.get("self_mute", False),
                "self_deaf": d.get("self_deaf", False)
            }
        else:
            self.vc_state = {"connected": False, "guild_id": guild_id}

    async def heartbeat(self, interval):
        while self.running:
            await asyncio.sleep(interval / 1000)
            if self.ws and not self.ws.closed:
                try:
                    await self.ws.send_json({"op": 1, "d": None})
                except Exception as e:
                    logger.error(f"Heartbeat failed: {e}")
                    break

    # ─── Identify & Platforms ────────────────────────────────────────────────
    async def identify(self):
        platform = self.config.get("platform", "pc").lower()
        
        platform_props = {
            "pc": {"$os": "windows", "$browser": "chrome", "$device": "pc"},
            "mobile": {"$os": "ios", "$browser": "Discord iOS", "$device": "iPhone"},
            "vr": {"$os": "windows", "$browser": "Discord VR", "$device": "Oculus Quest 3"},
            "xbox": {"$os": "xbox", "$browser": "Discord Xbox", "$device": "Xbox Series X"},
            "playstation": {"$os": "playstation", "$browser": "Discord PlayStation", "$device": "PS5"}
        }
        
        props = platform_props.get(platform, platform_props["pc"])

        payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "intents": 0,
                "properties": props
            }
        }
        await self.ws.send_json(payload)

    # ─── Presence & YouTube Stream ────────────────────────────────────────────
    async def update_presence(self):
        if not self.ws or self.ws.closed:
            return

        status = self.config.get("status", "online")
        status_text = self.config.get("status_text", "")
        rpc = self.config.get("rpc", {})
        youtube_stream = self.config.get("youtube_stream", {})

        activities = []

        if status_text:
            activities.append({
                "type": 4,
                "name": "Custom Status",
                "state": status_text
            })

        # YouTube Live Screen Stream Mode
        if youtube_stream and youtube_stream.get("enabled") and youtube_stream.get("url"):
            yt_url = youtube_stream.get("url").strip()
            activities.append({
                "type": 1, # Streaming activity
                "name": youtube_stream.get("title", "Voicecord YouTube Stream"),
                "details": "Streaming Screen Live on Voice Channel",
                "state": "Watching YouTube Live",
                "url": yt_url if yt_url.startswith("http") else f"https://{yt_url}",
                "timestamps": {"start": self._internal_start_time},
                "assets": {
                    "large_image": "mp:external/https/i.ytimg.com/vi/live/hqdefault.jpg",
                    "large_text": "YouTube Video Stream"
                }
            })

        elif rpc and rpc.get("name"):
            activity_type_map = {
                "playing": 0,
                "streaming": 1,
                "listening": 2,
                "watching": 3,
                "competing": 5
            }
            act_type_str = rpc.get("activity_type", "playing").lower()
            act_type = activity_type_map.get(act_type_str, 0)

            activity = {
                "type": act_type,
                "name": rpc.get("name", "Playing"),
            }

            if rpc.get("application_id"):
                activity["application_id"] = rpc.get("application_id")

            if rpc.get("details"):
                activity["details"] = rpc["details"]
            if rpc.get("state"):
                activity["state"] = rpc["state"]

            if act_type == 1 and rpc.get("url"):
                activity["url"] = rpc.get("url")

            timestamps = {}
            ts_start_raw = str(rpc.get("timestamp_start", "")).strip()
            ts_end_raw = str(rpc.get("timestamp_end", "")).strip()

            if ts_start_raw.lower() in ("auto", "true"):
                timestamps["start"] = self._internal_start_time
            elif ts_start_raw:
                with contextlib.suppress(ValueError, TypeError):
                    timestamps["start"] = int(float(ts_start_raw))

            if ts_end_raw:
                with contextlib.suppress(ValueError, TypeError):
                    timestamps["end"] = int(float(ts_end_raw))

            if timestamps:
                activity["timestamps"] = timestamps

            app_id = rpc.get("application_id", "").strip()
            assets_list = []
            if app_id:
                assets_list = await self.get_app_assets(app_id)

            assets = {}
            large_img = self.resolve_asset(rpc.get("large_image", ""), assets_list)
            if large_img:
                assets["large_image"] = large_img
            if rpc.get("large_text"):
                assets["large_text"] = rpc["large_text"]
            small_img = self.resolve_asset(rpc.get("small_image", ""), assets_list)
            if small_img:
                assets["small_image"] = small_img
            if rpc.get("small_text"):
                assets["small_text"] = rpc["small_text"]

            if assets:
                activity["assets"] = assets

            button_labels = []
            button_urls = []
            for i in [1, 2]:
                lbl = rpc.get(f"btn{i}_label", "").strip()
                url = rpc.get(f"btn{i}_url", "").strip()
                if lbl and url:
                    if not url.startswith(("http://", "https://")):
                        url = f"https://{url}"
                    button_labels.append(lbl[:32])
                    button_urls.append(url[:512])

            if button_labels and button_urls:
                activity["metadata"] = {
                    "button_urls": button_urls
                }
                activity["buttons"] = button_labels

            activities.append(activity)

        payload = {
            "op": 3,
            "d": {
                "since": 0,
                "activities": activities,
                "status": status,
                "afk": status == "idle"
            }
        }
        await self.ws.send_json(payload)

    # ─── Voice & Self Camera ──────────────────────────────────────────────────
    async def update_voice(self):
        if not self.ws or self.ws.closed:
            return

        voice = self.config.get("voice", {})
        guild_id = voice.get("guild_id", "").strip()
        channel_id = voice.get("channel_id", "").strip()
        self_video = voice.get("self_video", False)
        self_mute = voice.get("self_mute", False)
        self_deaf = voice.get("self_deaf", False)

        if guild_id:
            payload = {
                "op": 4,
                "d": {
                    "guild_id": guild_id,
                    "channel_id": channel_id if channel_id else None,
                    "self_mute": self_mute,
                    "self_deaf": self_deaf,
                    "self_video": self_video
                }
            }
            await self.ws.send_json(payload)

    # ─── Profile Editing ──────────────────────────────────────────────────────
    async def edit_profile(self, global_name: Optional[str] = None, bio: Optional[str] = None, avatar_base64: Optional[str] = None) -> dict:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()

        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }
        payload = {}
        if global_name is not None:
            payload["global_name"] = global_name
        if bio is not None:
            payload["bio"] = bio
        if avatar_base64 is not None:
            payload["avatar"] = avatar_base64

        try:
            async with self.session.patch("https://discord.com/api/v10/users/@me", headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.user_profile = data
                    return {"success": True, "profile": data}
                else:
                    err_txt = await resp.text()
                    return {"success": False, "error": f"HTTP {resp.status}: {err_txt}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─── Message Reactions ────────────────────────────────────────────────────
    async def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> dict:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        
        encoded_emoji = quote(emoji.strip())
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me"
        headers = {"Authorization": self.token}

        try:
            async with self.session.put(url, headers=headers) as resp:
                if resp.status in (204, 200):
                    return {"success": True, "message": "Reaction added successfully"}
                else:
                    err_text = await resp.text()
                    return {"success": False, "error": f"HTTP {resp.status}: {err_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── Token Manager ─────────────────────────────────────────────────────────────

class TokenManager:
    def __init__(self):
        self.clients: Dict[str, DiscordClient] = {}

    async def start_all(self, tokens_data: dict):
        for token, config in tokens_data.items():
            await self.add_token(token, config)

    def _launch_client(self, client: DiscordClient):
        client._start_task = asyncio.create_task(client.start())

    async def add_token(self, token: str, config: dict):
        if token in self.clients:
            await self.update_token(token, config)
            return
        client = DiscordClient(token, config)
        self.clients[token] = client
        self._launch_client(client)

    async def update_token(self, token: str, config: dict):
        if token not in self.clients:
            return
        client = self.clients[token]
        old_platform = client.config.get("platform", "pc")
        new_platform = config.get("platform", "pc")
        client.config = config
        if old_platform != new_platform:
            await client.stop()
            if client._start_task and not client._start_task.done():
                client._start_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client._start_task
            new_client = DiscordClient(token, config)
            self.clients[token] = new_client
            self._launch_client(new_client)
        else:
            await client.update_presence()
            await client.update_voice()

    async def restart_token(self, token: str):
        if token not in self.clients:
            return
        client = self.clients[token]
        config = client.config
        await client.stop()
        if client._start_task and not client._start_task.done():
            client._start_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client._start_task
        new_client = DiscordClient(token, config)
        new_client._internal_start_time = int(time.time())
        self.clients[token] = new_client
        self._launch_client(new_client)

    async def remove_token(self, token: str):
        if token in self.clients:
            client = self.clients.pop(token)
            await client.stop()
            if client._start_task and not client._start_task.done():
                client._start_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client._start_task

    def get_user_id(self, token: str) -> str:
        if token in self.clients:
            return self.clients[token]._user_id or self.clients[token].user_profile.get("id", "")
        return ""

    async def get_voice_data(self, token: str) -> dict:
        if token in self.clients:
            client = self.clients[token]
            vdata = client.voice_data
            if not vdata.get("token") or not vdata.get("endpoint"):
                logger.info(f"[{token[:10]}...] Voice credentials incomplete, requesting VOICE_SERVER_UPDATE from Discord...")
                await client.update_voice()
                for _ in range(25):
                    await asyncio.sleep(0.1)
                    vdata = client.voice_data
                    if vdata.get("token") and vdata.get("endpoint"):
                        break
            vdata_out = dict(vdata)
            if not vdata_out.get("session_id"):
                vdata_out["session_id"] = client.session_id
            return vdata_out
        return {}

    def get_vc_state(self, token: str) -> dict:
        if token in self.clients:
            client = self.clients[token]
            state = dict(client.vc_state) if client.vc_state else {}
            if state.get("connected"):
                return state
            
            # Fallback to saved voice config if runtime gateway state isn't connected yet
            voice = client.config.get("voice", {})
            g_id = voice.get("guild_id", "").strip()
            c_id = voice.get("channel_id", "").strip()
            if g_id and c_id:
                guild_info = client._guild_cache.get(g_id, {})
                return {
                    "guild_id": g_id,
                    "channel_id": c_id,
                    "guild_name": guild_info.get("name", g_id),
                    "guild_icon": guild_info.get("icon_url"),
                    "channel_name": guild_info.get("channels", {}).get(c_id, c_id),
                    "connected": True,
                    "self_video": voice.get("self_video", False),
                    "self_mute": voice.get("self_mute", False),
                    "self_deaf": voice.get("self_deaf", False),
                    "from_config": True
                }
        return {}

    async def stop_all(self):
        for client in list(self.clients.values()):
            await client.stop()
        self.clients.clear()


manager = TokenManager()
