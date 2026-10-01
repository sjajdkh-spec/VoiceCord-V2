import asyncio
import logging
import aiohttp
from typing import Dict, List, Optional
from urllib.parse import quote, parse_qs, urlparse

logger = logging.getLogger("bot_joiner")

class BotJoiner:
    def __init__(self):
        self.bot_token: str = ""
        self.bot_id: str = ""
        self.bot_secret: str = ""
        self.active: bool = False
        self.session: Optional[aiohttp.ClientSession] = None
        self._guilds_cache: List[dict] = []
        self.bot_profile: dict = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def start_bot(self, token: str, bot_id: str, secret: str) -> dict:
        clean_token = token.strip()
        clean_bot_id = bot_id.strip()
        clean_secret = secret.strip()

        if not clean_token:
            self.active = False
            return {"success": False, "message": "Bot Token is required!"}

        session = await self.get_session()
        headers = {"Authorization": f"Bot {clean_token}"}
        
        # Test bot token & fetch bot user profile
        try:
            async with session.get("https://discord.com/api/v10/users/@me", headers=headers) as resp:
                if resp.status != 200:
                    self.active = False
                    return {"success": False, "message": "Invalid Bot Token or Unauthorized!"}
                bot_data = await resp.json()
        except Exception as e:
            self.active = False
            return {"success": False, "message": f"Connection error: {e}"}

        self.bot_token = clean_token
        self.bot_id = clean_bot_id if clean_bot_id else bot_data.get("id", "")
        self.bot_secret = clean_secret
        self.active = True
        self.bot_profile = bot_data

        guilds = await self.fetch_bot_guilds()
        
        return {
            "success": True,
            "message": f"Bot Active as {bot_data.get('username')} ({bot_data.get('id')})",
            "bot_user": bot_data,
            "guilds": guilds
        }

    async def stop_bot(self):
        self.active = False
        self.bot_profile = {}
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def fetch_bot_guilds(self) -> List[dict]:
        if not self.active or not self.bot_token:
            return []
        
        session = await self.get_session()
        headers = {"Authorization": f"Bot {self.bot_token}"}
        
        try:
            async with session.get("https://discord.com/api/v10/users/@me/guilds?with_counts=true", headers=headers) as resp:
                if resp.status == 200:
                    guilds = await resp.json()
                    self._guilds_cache = guilds
                    return guilds
        except Exception as e:
            logger.error(f"Error fetching bot guilds: {e}")
        return self._guilds_cache

    async def get_guild_details(self, guild_id: str) -> Optional[dict]:
        if not self.bot_token:
            return None
        session = await self.get_session()
        headers = {"Authorization": f"Bot {self.bot_token}"}
        try:
            async with session.get(f"https://discord.com/api/v10/guilds/{guild_id}?with_counts=true", headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching guild details for {guild_id}: {e}")
        return None

    def clean_user_token(self, token_input: str) -> str:
        s = token_input.strip()
        parts = s.split(":")
        if len(parts) >= 3:
            return parts[2].strip()
        elif len(parts) == 2:
            return parts[1].strip()
        return s

    async def pull_single_token(
        self,
        token_str: str,
        guild_id: str,
        redirect_host: str = "http://localhost:8000",
        invite_code: str = ""
    ) -> dict:
        session = await self.get_session()
        clean_token = self.clean_user_token(token_str)

        # Step 1: Verify token profile
        user_headers = {"Authorization": clean_token}
        try:
            async with session.get("https://discord.com/api/v10/users/@me", headers=user_headers) as u_resp:
                if u_resp.status != 200:
                    # Try raw token string fallback if clean_token failed
                    if clean_token != token_str.strip():
                        clean_token = token_str.strip()
                        user_headers = {"Authorization": clean_token}
                        async with session.get("https://discord.com/api/v10/users/@me", headers=user_headers) as u2_resp:
                            if u2_resp.status != 200:
                                return {
                                    "token": token_str,
                                    "status": "invalid",
                                    "color": "red",
                                    "message": "Invalid token or Unauthorized"
                                }
                            user_data = await u2_resp.json()
                    else:
                        return {
                            "token": token_str,
                            "status": "invalid",
                            "color": "red",
                            "message": "Invalid token or Unauthorized"
                        }
                else:
                    user_data = await u_resp.json()
        except Exception as e:
            return {
                "token": token_str,
                "status": "invalid",
                "color": "red",
                "message": f"Token verification error: {e}"
            }

        user_id = user_data.get("id")
        username = user_data.get("username", "Unknown")

        # Option A: OAuth2 Bot Joiner
        if self.bot_token and self.bot_id:
            try:
                redirect_uri = f"{redirect_host}/api/oauth2/callback"
                scope = "identify guilds.join"
                auth_url = f"https://discord.com/api/v10/oauth2/authorize?client_id={self.bot_id}&redirect_uri={quote(redirect_uri)}&response_type=code&scope={quote(scope)}"

                auth_headers = {
                    "Authorization": clean_token,
                    "Content-Type": "application/json"
                }
                payload = {"permissions": "0", "authorize": True}

                async with session.post(auth_url, headers=auth_headers, json=payload) as auth_resp:
                    auth_json = await auth_resp.json()

                    location = auth_json.get("location")
                    if location:
                        parsed = urlparse(location)
                        query_params = parse_qs(parsed.query)
                        code = query_params.get("code", [None])[0]

                        if code and self.bot_secret:
                            token_url = "https://discord.com/api/v10/oauth2/token"
                            data = {
                                "client_id": self.bot_id,
                                "client_secret": self.bot_secret,
                                "grant_type": "authorization_code",
                                "code": code,
                                "redirect_uri": redirect_uri
                            }
                            headers = {"Content-Type": "application/x-www-form-urlencoded"}
                            async with session.post(token_url, data=data, headers=headers) as t_resp:
                                token_data = await t_resp.json()
                                access_token = token_data.get("access_token")

                                if access_token:
                                    put_url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"
                                    bot_headers = {
                                        "Authorization": f"Bot {self.bot_token}",
                                        "Content-Type": "application/json"
                                    }
                                    put_body = {"access_token": access_token}

                                    async with session.put(put_url, headers=bot_headers, json=put_body) as put_resp:
                                        if put_resp.status == 201:
                                            return {
                                                "token": clean_token,
                                                "user": username,
                                                "status": "joined",
                                                "color": "green",
                                                "message": f"Successfully pulled {username} into server!"
                                            }
                                        elif put_resp.status == 204:
                                            return {
                                                "token": clean_token,
                                                "user": username,
                                                "status": "already_joined",
                                                "color": "orange",
                                                "message": f"{username} is already in the server."
                                            }
                                        else:
                                            err_res = await put_resp.json()
                                            msg = err_res.get("message", "Failed to add member")
                                            # If bot authorization fails, attempt invite fallback below
            except Exception as e:
                logger.error(f"OAuth2 pull failed for {clean_token[:10]}: {e}")

        # Option B: Direct Invite Code Fallback
        if invite_code:
            clean_invite = invite_code.split("/")[-1].strip()
            inv_url = f"https://discord.com/api/v10/invites/{clean_invite}"
            try:
                async with session.post(inv_url, headers={"Authorization": clean_token}, json={}) as inv_resp:
                    if inv_resp.status == 200:
                        return {
                            "token": clean_token,
                            "user": username,
                            "status": "joined",
                            "color": "green",
                            "message": f"Joined server via invite link ({clean_invite})!"
                        }
                    else:
                        err_json = await inv_resp.json()
                        msg = err_json.get("message", "Invite join failed")
                        return {
                            "token": clean_token,
                            "user": username,
                            "status": "failed",
                            "color": "red",
                            "message": f"Invite Join failed: {msg}"
                        }
            except Exception as e:
                return {
                    "token": clean_token,
                    "user": username,
                    "status": "failed",
                    "color": "red",
                    "message": f"Invite Join error: {e}"
                }

        return {
            "token": clean_token,
            "user": username,
            "status": "failed",
            "color": "orange",
            "message": "Bot Secret missing or OAuth authorization failed. Add Invite Code link for direct join fallback."
        }

bot_joiner = BotJoiner()
