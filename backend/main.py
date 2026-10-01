from fastapi import FastAPI, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
import requests as req_lib
import contextlib
import uvicorn
import asyncio
import psutil
import time as _time
from .config import (
    load_tokens, save_tokens, load_config, load_bot_config, save_bot_config, BASE_DIR
)
from .bot import manager
from .bot_joiner import bot_joiner
from .music_manager import music_manager, load_lavalink_config, save_lavalink_config

_SERVER_START_TIME = _time.time()

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    tokens_data = load_tokens()
    await manager.start_all(tokens_data)
    
    # Auto restore Bot Joiner if config was active
    b_cfg = load_bot_config()
    if b_cfg.get("active") and b_cfg.get("bot_token"):
        await bot_joiner.start_bot(
            b_cfg["bot_token"],
            b_cfg.get("bot_id", ""),
            b_cfg.get("bot_secret", "")
        )
    yield
    await manager.stop_all()
    await bot_joiner.stop_bot()

app = FastAPI(lifespan=lifespan)

frontend_dir = BASE_DIR / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

def get_current_user(request: Request):
    config = load_config()
    expected_pass = config["admin_pass"]
    
    auth_header = request.headers.get("Authorization", "").strip()
    token_val = ""
    if auth_header.startswith("Bearer "):
        token_val = auth_header[7:].strip()
    else:
        token_val = auth_header
        
    if not token_val:
        token_val = request.headers.get("x-access-token", "").strip()
        
    if not token_val or token_val != expected_pass:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token_val

# ─── Pages ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    f = frontend_dir / "index.html"
    return f.read_text(encoding="utf-8") if f.exists() else "Not Found"

@app.get("/login_page", response_class=HTMLResponse)
async def get_login_page():
    f = frontend_dir / "login.html"
    return f.read_text(encoding="utf-8") if f.exists() else "Not Found"

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    config = load_config()
    if username == config["admin_user"] and password == config["admin_pass"]:
        return {"access_token": password, "token_type": "bearer"}
    raise HTTPException(status_code=400, detail="Incorrect username or password")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def discord_get(path: str, token: str):
    try:
        r = req_lib.get(f"https://discord.com/api/v10{path}", headers={"Authorization": token})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def fetch_discord_profile(token: str):
    return discord_get("/users/@me", token)

# ─── Token API ────────────────────────────────────────────────────────────────

@app.get("/api/tokens")
async def api_get_tokens(token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    # Validate each token profile asynchronously / return status
    return tokens_data

@app.post("/api/tokens")
async def api_add_token(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    if not token_str:
        raise HTTPException(status_code=400, detail="Token is required")

    config = data.get("config", {})

    profile = fetch_discord_profile(token_str)
    if profile:
        config["profile"] = {
            "id": profile.get("id"),
            "username": profile.get("username"),
            "global_name": profile.get("global_name"),
            "discriminator": profile.get("discriminator"),
            "avatar": profile.get("avatar"),
            "bio": profile.get("bio", ""),
            "valid": True
        }
    else:
        config["profile"] = {"valid": False}

    tokens_data = load_tokens()
    tokens_data[token_str] = config
    save_tokens(tokens_data)
    await manager.add_token(token_str, config)
    return {"message": "Token added successfully", "profile": config["profile"]}

@app.put("/api/tokens/{token_id:path}")
async def api_update_token(token_id: str, data: dict, token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    if token_id not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")
    if "profile" in tokens_data[token_id] and "profile" not in data:
        data["profile"] = tokens_data[token_id]["profile"]
    tokens_data[token_id] = data
    save_tokens(tokens_data)
    await manager.update_token(token_id, data)
    return {"message": "Token updated"}

@app.post("/api/tokens/{token_id:path}/restart")
async def api_restart_token(token_id: str, token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    if token_id not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")
    await manager.restart_token(token_id)
    return {"message": "Token restarted"}

@app.delete("/api/tokens/{token_id:path}")
async def api_delete_token(token_id: str, token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    if token_id not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")
    del tokens_data[token_id]
    save_tokens(tokens_data)
    await manager.remove_token(token_id)
    return {"message": "Token deleted"}

@app.post("/api/tokens/bulk/status")
async def api_bulk_status(data: dict, token: str = Depends(get_current_user)):
    status = data.get("status", "online")
    tokens_data = load_tokens()
    for t in tokens_data:
        tokens_data[t]["status"] = status
    save_tokens(tokens_data)
    for t in tokens_data:
        await manager.update_token(t, tokens_data[t])
    return {"message": f"All tokens set to {status}"}

@app.post("/api/tokens/bulk/restart")
async def api_bulk_restart(token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    for t in tokens_data:
        await manager.restart_token(t)
    return {"message": "All tokens restarted"}

@app.post("/api/tokens/bulk/disconnect-vc")
async def api_bulk_disconnect_vc(token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    for t in tokens_data:
        if "voice" in tokens_data[t]:
            tokens_data[t]["voice"]["channel_id"] = ""
    save_tokens(tokens_data)
    for t in tokens_data:
        await manager.update_token(t, tokens_data[t])
    return {"message": "All tokens disconnected from voice channels"}

# ─── Profile Edit API ─────────────────────────────────────────────────────────

@app.patch("/api/tokens/{token_id:path}/profile")
async def api_edit_discord_profile(token_id: str, data: dict, token: str = Depends(get_current_user)):
    client = manager.clients.get(token_id)
    if not client:
        raise HTTPException(status_code=404, detail="Token client not running")
    
    global_name = data.get("global_name")
    bio = data.get("bio")
    avatar = data.get("avatar") # base64 image data
    
    res = await client.edit_profile(global_name=global_name, bio=bio, avatar_base64=avatar)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Profile update failed"))
    
    # Refresh profile stored in tokens data
    tokens_data = load_tokens()
    if token_id in tokens_data:
        p = fetch_discord_profile(token_id)
        if p:
            tokens_data[token_id]["profile"] = {
                "id": p.get("id"),
                "username": p.get("username"),
                "global_name": p.get("global_name"),
                "discriminator": p.get("discriminator"),
                "avatar": p.get("avatar"),
                "bio": p.get("bio", ""),
                "valid": True
            }
            save_tokens(tokens_data)
            
    return {"message": "Profile updated successfully", "profile": res.get("profile")}

# ─── Self-Stream YouTube & Self-Cam API ───────────────────────────────────────

@app.post("/api/tokens/{token_id:path}/youtube-stream")
async def api_set_youtube_stream(token_id: str, data: dict, token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    if token_id not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")
    
    enabled = data.get("enabled", False)
    url = data.get("url", "").strip()
    title = data.get("title", "YouTube Stream")

    tokens_data[token_id]["youtube_stream"] = {
        "enabled": enabled,
        "url": url,
        "title": title
    }
    save_tokens(tokens_data)
    await manager.update_token(token_id, tokens_data[token_id])
    return {"message": "YouTube Stream settings updated"}

@app.post("/api/tokens/{token_id:path}/self-cam")
async def api_toggle_self_cam(token_id: str, data: dict, token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    if token_id not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")
    
    enabled = data.get("enabled", False)
    if "voice" not in tokens_data[token_id]:
        tokens_data[token_id]["voice"] = {"guild_id": "", "channel_id": "", "self_mute": False, "self_deaf": False}
    
    tokens_data[token_id]["voice"]["self_video"] = enabled
    save_tokens(tokens_data)
    await manager.update_token(token_id, tokens_data[token_id])
    return {"message": "Self camera toggled"}

# ─── Reactions API ────────────────────────────────────────────────────────────

@app.post("/api/reactions/send")
async def api_send_reactions(data: dict, token: str = Depends(get_current_user)):
    channel_id = data.get("channel_id", "").strip()
    message_id = data.get("message_id", "").strip()
    emoji = data.get("emoji", "").strip()
    selected_tokens = data.get("tokens", [])
    delay_ms = data.get("delay", 300)

    if not channel_id or not message_id or not emoji:
        raise HTTPException(status_code=400, detail="channel_id, message_id, and emoji are required")

    tokens_data = load_tokens()
    tokens_to_use = selected_tokens if selected_tokens else list(tokens_data.keys())

    results = []
    for t_str in tokens_to_use:
        client = manager.clients.get(t_str)
        if client:
            res = await client.add_reaction(channel_id, message_id, emoji)
            results.append({
                "token": t_str,
                "success": res.get("success"),
                "message": res.get("message") or res.get("error")
            })
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
        else:
            results.append({"token": t_str, "success": False, "message": "Client not active"})

    return {"results": results}

# ─── Bot Joiner & Pull Tokens API ─────────────────────────────────────────────

@app.get("/api/bot/config")
async def api_get_bot_config(token: str = Depends(get_current_user)):
    return load_bot_config()

@app.post("/api/bot/config")
async def api_save_bot_config(data: dict, token: str = Depends(get_current_user)):
    bot_token = data.get("bot_token", "").strip()
    bot_id = data.get("bot_id", "").strip()
    bot_secret = data.get("bot_secret", "").strip()
    active = data.get("active", True)

    cfg = {
        "bot_token": bot_token,
        "bot_id": bot_id,
        "bot_secret": bot_secret,
        "active": active
    }
    save_bot_config(cfg)

    if active and bot_token:
        bot_res = await bot_joiner.start_bot(bot_token, bot_id, bot_secret)
        return {"message": "Bot configured & activated", "bot_result": bot_res}
    else:
        await bot_joiner.stop_bot()
        return {"message": "Bot deactivated"}

@app.get("/api/bot/guilds")
async def api_get_bot_guilds(token: str = Depends(get_current_user)):
    if not bot_joiner.active:
        return {"active": False, "guilds": []}
    guilds = await bot_joiner.fetch_bot_guilds()
    return {"active": True, "guilds": guilds}

@app.get("/api/bot/guild/{guild_id}")
async def api_get_bot_guild_details(guild_id: str, token: str = Depends(get_current_user)):
    details = await bot_joiner.get_guild_details(guild_id)
    if not details:
        raise HTTPException(status_code=404, detail="Guild details not found")
    return details

@app.post("/api/bot/pull-tokens")
async def api_pull_tokens(data: dict, request: Request, token: str = Depends(get_current_user)):
    guild_id = data.get("guild_id", "").strip()
    target_tokens = data.get("tokens", []) # list of token strings
    amount = data.get("amount", 0) # optional max amount
    invite_code = data.get("invite_code", "").strip()

    if not guild_id:
        raise HTTPException(status_code=400, detail="guild_id is required")

    all_tokens_dict = load_tokens()
    all_tokens_keys = list(all_tokens_dict.keys())

    if target_tokens:
        tokens_to_pull = [t for t in target_tokens if t in all_tokens_dict]
    else:
        tokens_to_pull = all_tokens_keys

    if amount and amount > 0:
        tokens_to_pull = tokens_to_pull[:amount]

    base_url = str(request.base_url).rstrip("/")

    results = []
    for t_str in tokens_to_pull:
        res = await bot_joiner.pull_single_token(
            token_str=t_str,
            guild_id=guild_id,
            redirect_host=base_url,
            invite_code=invite_code
        )
        results.append(res)
        await asyncio.sleep(0.5)

    return {"guild_id": guild_id, "total": len(results), "results": results}

# ─── VC API ───────────────────────────────────────────────────────────────────

@app.get("/api/vc-states")
async def api_vc_states(token: str = Depends(get_current_user)):
    tokens_data = load_tokens()
    result = {}
    for t in tokens_data:
        state = manager.get_vc_state(t)
        state = dict(state) if state else {}
        profile = tokens_data[t].get("profile", {}) or {}
        token_config = tokens_data[t]

        # ── Fallback: if vc_state is empty/disconnected but config has a
        # saved voice channel, assume connected (bot may not have received
        # VOICE_STATE_UPDATE yet after a reconnect).
        if not state.get("connected"):
            voice_cfg = token_config.get("voice", {})
            cfg_guild = voice_cfg.get("guild_id", "").strip()
            cfg_channel = voice_cfg.get("channel_id", "").strip()
            if cfg_guild and cfg_channel:
                state = {
                    "guild_id": cfg_guild,
                    "channel_id": cfg_channel,
                    "guild_name": cfg_guild,    # will be resolved below
                    "channel_name": cfg_channel, # will be resolved below
                    "connected": True,
                    "self_mute": voice_cfg.get("self_mute", False),
                    "self_deaf": voice_cfg.get("self_deaf", False),
                    "self_video": voice_cfg.get("self_video", False),
                    "from_config": True,
                }

        if state.get("connected"):
            guild_id = state.get("guild_id")
            channel_id = state.get("channel_id")

            if guild_id and (not state.get("guild_name") or state.get("guild_name") == guild_id):
                g_info = discord_get(f"/guilds/{guild_id}?with_counts=false", t)
                if g_info:
                    state["guild_name"] = g_info.get("name", guild_id)
                    icon_hash = g_info.get("icon")
                    state["guild_icon"] = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png" if icon_hash else None

            if channel_id and (not state.get("channel_name") or state.get("channel_name") == channel_id):
                ch_info = discord_get(f"/channels/{channel_id}", t)
                if ch_info:
                    state["channel_name"] = ch_info.get("name", channel_id)

        result[t] = {
            "profile": profile,
            "vc_state": state
        }
    return result


@app.post("/api/vc/join")
async def api_vc_join(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token")
    guild_id = data.get("guild_id", "").strip()
    channel_id = data.get("channel_id", "").strip()
    self_mute = data.get("self_mute", False)
    self_deaf = data.get("self_deaf", False)
    self_video = data.get("self_video", False)

    if not token_str or not guild_id or not channel_id:
        raise HTTPException(status_code=400, detail="token, guild_id, channel_id required")

    tokens_data = load_tokens()
    if token_str not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")

    config = tokens_data[token_str]
    config["voice"] = {
        "guild_id": guild_id,
        "channel_id": channel_id,
        "self_mute": self_mute,
        "self_deaf": self_deaf,
        "self_video": self_video
    }
    tokens_data[token_str] = config
    save_tokens(tokens_data)
    await manager.update_token(token_str, config)
    return {"message": "Join command sent"}

@app.post("/api/vc/disconnect")
async def api_vc_disconnect(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token")
    guild_id = data.get("guild_id", "").strip()

    if not token_str:
        raise HTTPException(status_code=400, detail="token required")

    tokens_data = load_tokens()
    if token_str not in tokens_data:
        raise HTTPException(status_code=404, detail="Token not found")

    config = tokens_data[token_str]
    config["voice"] = {
        "guild_id": guild_id,
        "channel_id": "",
        "self_mute": False,
        "self_deaf": False,
        "self_video": False
    }
    tokens_data[token_str] = config
    save_tokens(tokens_data)
    await manager.update_token(token_str, config)
    return {"message": "Disconnect command sent"}


# ─── Music API ────────────────────────────────────────────────────────────────

@app.get("/api/music/search")
async def api_music_search(q: str = "", limit: int = 8, token: str = Depends(get_current_user)):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query required")
    results = await music_manager.search(q.strip(), limit=limit)
    return {"results": results}

@app.get("/api/music/state/{token_id:path}")
async def api_music_state(token_id: str, token: str = Depends(get_current_user)):
    state = music_manager.get_state(token_id)
    return state

@app.post("/api/music/play")
async def api_music_play(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    query = data.get("query", "").strip()
    if not token_str or not query:
        raise HTTPException(status_code=400, detail="token and query required")

    # Check if token is in VC
    vc_state = manager.get_vc_state(token_str) or {}
    if not vc_state.get("connected"):
        tokens_data = load_tokens()
        if token_str in tokens_data:
            voice_cfg = tokens_data[token_str].get("voice", {})
            if voice_cfg.get("guild_id") and voice_cfg.get("channel_id"):
                vc_state = {
                    "connected": True,
                    "guild_id": voice_cfg.get("guild_id"),
                    "channel_id": voice_cfg.get("channel_id"),
                }

    voice_data = await manager.get_voice_data(token_str)
    user_id = manager.get_user_id(token_str)
    result = await music_manager.play(token_str, query, vc_state, voice_data, user_id=user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Play failed"))
    return result

@app.post("/api/music/pause")
async def api_music_pause(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    vc_state = manager.get_vc_state(token_str) or {}
    guild_id = vc_state.get("guild_id")
    result = await music_manager.pause(token_str, guild_id=guild_id)
    return result

@app.post("/api/music/resume")
async def api_music_resume(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    vc_state = manager.get_vc_state(token_str) or {}
    guild_id = vc_state.get("guild_id")
    result = await music_manager.resume(token_str, guild_id=guild_id)
    return result

@app.post("/api/music/stop")
async def api_music_stop(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    vc_state = manager.get_vc_state(token_str) or {}
    guild_id = vc_state.get("guild_id")
    result = await music_manager.stop(token_str, guild_id=guild_id)
    return result

@app.post("/api/music/skip")
async def api_music_skip(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    vc_state = manager.get_vc_state(token_str) or {}
    guild_id = vc_state.get("guild_id")
    voice_data = await manager.get_voice_data(token_str)
    result = await music_manager.skip(token_str, guild_id=guild_id, voice_data=voice_data)
    return result

@app.post("/api/music/loop")
async def api_music_loop(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    result = await music_manager.toggle_loop(token_str)
    return result

@app.post("/api/music/volume")
async def api_music_volume(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    volume = int(data.get("volume", 100))
    vc_state = manager.get_vc_state(token_str) or {}
    guild_id = vc_state.get("guild_id")
    result = await music_manager.set_volume(token_str, volume, guild_id=guild_id)
    return result

@app.post("/api/music/queue/remove")
async def api_music_queue_remove(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    index = int(data.get("index", 0))
    result = await music_manager.remove_from_queue(token_str, index)
    return result

@app.post("/api/music/queue/clear")
async def api_music_queue_clear(data: dict, token: str = Depends(get_current_user)):
    token_str = data.get("token", "").strip()
    result = await music_manager.clear_queue(token_str)
    return result

# ─── Settings & Lavalink API ──────────────────────────────────────────────────

@app.get("/api/settings/lavalink")
async def api_get_lavalink(token: str = Depends(get_current_user)):
    return load_lavalink_config()

@app.post("/api/settings/lavalink")
async def api_save_lavalink(data: dict, token: str = Depends(get_current_user)):
    cfg = {
        "uri": data.get("uri", "").strip(),
        "password": data.get("password", "").strip(),
    }
    if not cfg["uri"]:
        raise HTTPException(status_code=400, detail="URI required")
    save_lavalink_config(cfg)
    return {"message": "Lavalink configuration saved"}

@app.get("/api/settings/lavalink/status")
async def api_lavalink_status(token: str = Depends(get_current_user)):
    status = await music_manager.lavalink.check_status()
    node_stats = await music_manager.lavalink.get_stats()
    
    uptime_sec = int(_time.time() - _SERVER_START_TIME)
    hours, remainder = divmod(uptime_sec, 3600)
    mins, secs = divmod(remainder, 60)
    uptime_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
    
    # Valid tokens count
    tokens_data = load_tokens()
    valid_count = sum(
        1 for cfg in tokens_data.values()
        if cfg.get("profile", {}).get("valid", False)
    )

    # System stats
    cpu_pct = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory()
    
    return {
        "lavalink": status,
        "node_stats": node_stats,
        "server_uptime": uptime_str,
        "valid_tokens": valid_count,
        "total_tokens": len(tokens_data),
        "system": {
            "cpu_percent": cpu_pct,
            "ram_used_mb": round(ram.used / 1024 / 1024, 1),
            "ram_total_mb": round(ram.total / 1024 / 1024, 1),
            "ram_percent": ram.percent,
        },
        "lavalink_config": load_lavalink_config(),
    }

if __name__ == "__main__":
    config = load_config()
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
