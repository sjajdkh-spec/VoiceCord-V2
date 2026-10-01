let tokensCache = {};
let vcStatesCache = {};
let editingTokenId = null;
let avatarBase64Data = null;

// Auth check on load
const token = localStorage.getItem("token") || localStorage.getItem("vc_token");
if (!token) {
    window.location.href = "/login_page";
}

async function apiRequest(url, method = "GET", body = null) {
    const authHeader = token.startsWith("Bearer ") ? token : `Bearer ${token}`;
    const headers = {
        "Authorization": authHeader,
        "x-access-token": token,
        "Content-Type": "application/json"
    };

    const options = { method, headers };
    if (body) {
        options.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(url, options);
        if (response.status === 401) {
            localStorage.removeItem("token");
            localStorage.removeItem("vc_token");
            window.location.href = "/login_page";
            return null;
        }
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP Error ${response.status}`);
        }
        return await response.json();
    } catch (err) {
        showToast(err.message, "danger");
        throw err;
    }
}

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.style.cssText = `
        background: ${type === 'danger' ? 'linear-gradient(135deg,#f43f5e,#dc2626)' : type === 'success' ? 'linear-gradient(135deg,#10b981,#059669)' : type === 'warning' ? 'linear-gradient(135deg,#f59e0b,#d97706)' : 'linear-gradient(135deg,#0ea5e9,#0284c7)'};
        color: white; padding: 12px 20px; border-radius: 10px; margin-top: 6px;
        font-weight: 600; font-size: 13px; box-shadow: 0 6px 20px rgba(0,0,0,0.4);
        transition: opacity 0.3s; display: flex; align-items: center; gap: 8px;
        min-width: 220px; max-width: 360px; border: 1px solid rgba(255,255,255,0.15);
    `;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Navigation
function showSection(sectionName) {
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    document.querySelectorAll('.section-view').forEach(view => view.classList.remove('active'));

    const navItem = document.getElementById(`nav-${sectionName}`);
    if (navItem) navItem.classList.add('active');

    const view = document.getElementById(`section-${sectionName}`);
    if (view) view.classList.add('active');

    if (sectionName === 'dashboard') {
        loadDashboard();
    } else if (sectionName === 'reactions') {
        loadReactionsView();
    } else if (sectionName === 'vc') {
        loadVCView();
    } else if (sectionName === 'music') {
        loadMusicView();
    } else if (sectionName === 'settings') {
        loadSettingsView();
    }
}

function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("vc_token");
    window.location.href = "/login_page";
}

// ── Dashboard Loading ──────────────────────────────────────────────────────────
async function loadDashboard() {
    tokensCache = await apiRequest("/api/tokens") || {};
    vcStatesCache = await apiRequest("/api/vc-states") || {};
    renderDashboard();
}

function renderDashboard() {
    const grid = document.getElementById("token-grid");
    grid.innerHTML = "";

    const tokenKeys = Object.keys(tokensCache);
    let totalOnline = 0;
    let totalRpc = 0;
    let totalVc = 0;

    document.getElementById("stat-total").innerText = tokenKeys.length;

    if (tokenKeys.length === 0) {
        grid.innerHTML = `<div class="empty-state"><i class="ri-key-2-line" style="font-size:36px;opacity:0.4;display:block;margin-bottom:10px"></i>No tokens added yet. Click "+ New Token" to get started.</div>`;
        document.getElementById("stat-online").innerText = 0;
        document.getElementById("stat-rpc").innerText = 0;
        document.getElementById("stat-vc").innerText = 0;
        return;
    }

    tokenKeys.forEach(tStr => {
        const cfg = tokensCache[tStr];
        const stateData = vcStatesCache[tStr] || {};
        const profile = cfg.profile || {};
        const isInvalid = profile.valid === false;

        const status = cfg.status || "online";
        if (status === "online") totalOnline++;

        const rpc = cfg.rpc || {};
        const ytStream = cfg.youtube_stream || {};
        if (rpc.name || (ytStream.enabled && ytStream.url)) totalRpc++;

        const vcState = stateData.vc_state || {};
        if (vcState.connected) totalVc++;

        const platform = (cfg.platform || "pc").toLowerCase();
        const platformBadge = {
            "pc":          '<i class="ri-computer-line"></i> PC',
            "mobile":      '<i class="ri-smartphone-line"></i> Mobile',
            "vr":          '<i class="ri-glasses-line"></i> VR',
            "xbox":        '<i class="ri-gamepad-line"></i> Xbox',
            "playstation": '<i class="ri-gamepad-fill"></i> PlayStation'
        }[platform] || '<i class="ri-computer-line"></i> PC';

        const card = document.createElement("div");
        card.className = `token-card ${isInvalid ? 'invalid-token' : ''}`;

        const avatarUrl = profile.id && profile.avatar
            ? `https://cdn.discordapp.com/avatars/${profile.id}/${profile.avatar}.png`
            : 'https://cdn.discordapp.com/embed/avatars/0.png';

        const usernameText = profile.username
            ? `${profile.global_name || profile.username} (${profile.username})`
            : `Token: ${tStr.slice(0, 12)}...`;

        card.innerHTML = `
            <div class="token-card-header">
                <img src="${avatarUrl}" class="token-avatar" alt="User Avatar">
                <div class="token-user-details">
                    <h4>${usernameText}</h4>
                    <div class="flex-row gap-2 mt-1">
                        ${isInvalid
                            ? `<span class="badge badge-invalid"><i class="ri-close-circle-line"></i> INVALID TOKEN</span>`
                            : `<span class="badge badge-success"><i class="ri-checkbox-blank-circle-fill"></i> ${status.toUpperCase()}</span>`}
                        <span class="badge badge-info">${platformBadge}</span>
                    </div>
                </div>
            </div>

            <div class="token-string-box">
                <span class="blur-token-text" title="Hover to view full token">${tStr}</span>
            </div>

            ${ytStream.enabled && ytStream.url ? `
                <div class="badge badge-warning"><i class="ri-youtube-line"></i> Live YouTube Stream Active</div>
            ` : ''}

            ${cfg.voice && cfg.voice.self_video ? `
                <div class="badge badge-info"><i class="ri-vidicon-line"></i> Self-Cam Active</div>
            ` : ''}

            <div class="token-actions">
                <button class="btn btn-secondary btn-sm" onclick="openProfileModal('${tStr}')"><i class="ri-user-settings-line"></i> Edit Profile</button>
                <button class="btn btn-secondary btn-sm" onclick="editTokenConfig('${tStr}')"><i class="ri-settings-3-line"></i> Config</button>
                <button class="btn btn-warning btn-sm" onclick="restartToken('${tStr}')"><i class="ri-refresh-line"></i> Restart</button>
                <button class="btn btn-danger btn-sm" onclick="deleteToken('${tStr}')"><i class="ri-delete-bin-line"></i></button>
            </div>
        `;

        grid.appendChild(card);
    });

    document.getElementById("stat-online").innerText = totalOnline;
    document.getElementById("stat-rpc").innerText = totalRpc;
    document.getElementById("stat-vc").innerText = totalVc;
}

// ── Reactions View ─────────────────────────────────────────────────────────────
async function loadReactionsView() {
    tokensCache = await apiRequest("/api/tokens") || {};
    const container = document.getElementById("react-tokens-list");
    container.innerHTML = "";

    const keys = Object.keys(tokensCache);
    if (keys.length === 0) {
        container.innerHTML = '<div style="color:var(--text-dim);font-size:13px;">No tokens added yet.</div>';
        return;
    }

    keys.forEach(tStr => {
        const p = tokensCache[tStr].profile || {};
        const labelText = p.username ? `${p.username} (${tStr.slice(0, 10)}...)` : tStr;

        const row = document.createElement("label");
        row.className = "checkbox-row";
        row.innerHTML = `
            <input type="checkbox" value="${tStr}" class="react-token-cb" checked>
            <span>${labelText}</span>
        `;
        container.appendChild(row);
    });
}

function selectAllReactionTokens(select) {
    document.querySelectorAll(".react-token-cb").forEach(cb => cb.checked = select);
}

async function sendBulkReactions() {
    const channel_id = document.getElementById("react-channel-id").value.trim();
    const message_id = document.getElementById("react-message-id").value.trim();
    const emoji = document.getElementById("react-emoji").value.trim();
    const delay = parseInt(document.getElementById("react-delay").value) || 300;

    const selectedTokens = [];
    document.querySelectorAll(".react-token-cb:checked").forEach(cb => selectedTokens.push(cb.value));

    if (!channel_id || !message_id || !emoji) {
        showToast("Please enter Channel ID, Message ID, and Emoji!", "warning");
        return;
    }

    const terminal = document.getElementById("reaction-logs-terminal");
    terminal.innerHTML = `<div class="log-line info">Sending reactions to message ${message_id}...</div>`;

    const res = await apiRequest("/api/reactions/send", "POST", {
        channel_id,
        message_id,
        emoji,
        delay,
        tokens: selectedTokens
    });

    if (res && res.results) {
        res.results.forEach(r => {
            const line = document.createElement("div");
            line.className = `log-line ${r.success ? 'green' : 'red'}`;
            line.innerText = `[${r.success ? 'SUCCESS' : 'FAILED'}] Token ${r.token.slice(0, 10)}... : ${r.message}`;
            terminal.appendChild(line);
        });
        terminal.scrollTop = terminal.scrollHeight;
    }
}

// ── Profile Edit Modal ────────────────────────────────────────────────────────
function openProfileModal(tokenId) {
    editingTokenId = tokenId;
    avatarBase64Data = null;
    document.getElementById("p-token-id").value = tokenId;

    const profile = (tokensCache[tokenId] && tokensCache[tokenId].profile) || {};
    document.getElementById("p-global-name").value = profile.global_name || profile.username || "";
    document.getElementById("p-bio").value = profile.bio || "";
    document.getElementById("p-avatar-file").value = "";
    document.getElementById("p-avatar-base64").value = "";

    document.getElementById("profile-modal").classList.add("active");
}

function closeProfileModal() {
    document.getElementById("profile-modal").classList.remove("active");
    editingTokenId = null;
    avatarBase64Data = null;
}

function convertAvatarToBase64(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        const reader = new FileReader();
        reader.onload = function (e) {
            avatarBase64Data = e.target.result;
            document.getElementById("p-avatar-base64").value = avatarBase64Data;
        };
        reader.readAsDataURL(file);
    }
}

async function saveDiscordProfile() {
    if (!editingTokenId) return;

    const global_name = document.getElementById("p-global-name").value.trim();
    const bio = document.getElementById("p-bio").value.trim();

    const payload = {
        global_name: global_name,
        bio: bio
    };

    if (avatarBase64Data) {
        payload.avatar = avatarBase64Data;
    }

    const res = await apiRequest(`/api/tokens/${encodeURIComponent(editingTokenId)}/profile`, "PATCH", payload);
    if (res) {
        showToast("Profile updated on Discord!", "success");
        closeProfileModal();
        loadDashboard();
    }
}

// ── Add/Edit Token Modal Controls ─────────────────────────────────────────────
function openAddModal() {
    editingTokenId = null;
    document.getElementById("modal-title").innerText = "Add New Token";
    document.getElementById("token-form").reset();
    document.getElementById("t-token").disabled = false;
    document.getElementById("token-modal").classList.add("active");
}

function closeModal() {
    document.getElementById("token-modal").classList.remove("active");
}

function toggleStreamingUrl() {
    const type = document.getElementById("t-rpc-type").value;
    document.getElementById("streaming-url-group").style.display = (type === "streaming") ? "block" : "none";
}

function toggleYtInput() {
    const enabled = document.getElementById("t-yt-enable").checked;
    document.getElementById("yt-link-group").style.display = enabled ? "block" : "none";
}

function editTokenConfig(tokenId) {
    editingTokenId = tokenId;
    const cfg = tokensCache[tokenId];
    if (!cfg) return;

    document.getElementById("modal-title").innerText = "Edit Token Configuration";
    document.getElementById("t-token").value = tokenId;
    document.getElementById("t-token").disabled = true;

    document.getElementById("t-status").value = cfg.status || "online";
    document.getElementById("t-platform").value = cfg.platform || "pc";
    document.getElementById("t-status-text").value = cfg.status_text || "";

    const vc = cfg.voice || {};
    document.getElementById("t-vc-guild").value = vc.guild_id || "";
    document.getElementById("t-vc-channel").value = vc.channel_id || "";
    document.getElementById("t-vc-mute").checked = vc.self_mute === true;
    document.getElementById("t-vc-deaf").checked = !!vc.self_deaf;
    document.getElementById("t-self-cam").checked = !!vc.self_video;

    const yt = cfg.youtube_stream || {};
    document.getElementById("t-yt-enable").checked = !!yt.enabled;
    document.getElementById("t-yt-url").value = yt.url || "";
    toggleYtInput();

    const rpc = cfg.rpc || {};
    document.getElementById("t-app-id").value = rpc.application_id || "";
    document.getElementById("t-rpc-type").value = rpc.activity_type || "playing";
    document.getElementById("t-rpc-url").value = rpc.url || "";
    document.getElementById("t-rpc-name").value = rpc.name || "";
    document.getElementById("t-rpc-details").value = rpc.details || "";
    document.getElementById("t-rpc-state").value = rpc.state || "";
    document.getElementById("t-rpc-large-img").value = rpc.large_image || "";
    document.getElementById("t-rpc-large-text").value = rpc.large_text || "";
    document.getElementById("t-rpc-small-img").value = rpc.small_image || "";
    document.getElementById("t-rpc-small-text").value = rpc.small_text || "";
    document.getElementById("t-rpc-btn1-label").value = rpc.btn1_label || "";
    document.getElementById("t-rpc-btn1-url").value = rpc.btn1_url || "";
    document.getElementById("t-rpc-btn2-label").value = rpc.btn2_label || "";
    document.getElementById("t-rpc-btn2-url").value = rpc.btn2_url || "";

    toggleStreamingUrl();
    document.getElementById("token-modal").classList.add("active");
}

async function saveToken() {
    const tokenStr = document.getElementById("t-token").value.trim();
    if (!tokenStr) {
        showToast("Token string is required!", "warning");
        return;
    }

    const vcGuild = document.getElementById("t-vc-guild").value.trim();
    const vcChannel = document.getElementById("t-vc-channel").value.trim();

    const config = {
        status: document.getElementById("t-status").value,
        platform: document.getElementById("t-platform").value,
        status_text: document.getElementById("t-status-text").value.trim(),
        voice: {
            guild_id: vcGuild,
            channel_id: vcChannel,
            self_mute: document.getElementById("t-vc-mute").checked,
            self_deaf: document.getElementById("t-vc-deaf").checked,
            self_video: document.getElementById("t-self-cam").checked
        },
        youtube_stream: {
            enabled: document.getElementById("t-yt-enable").checked,
            url: document.getElementById("t-yt-url").value.trim()
        },
        rpc: {
            application_id: document.getElementById("t-app-id").value.trim(),
            activity_type: document.getElementById("t-rpc-type").value,
            url: document.getElementById("t-rpc-url").value.trim(),
            name: document.getElementById("t-rpc-name").value.trim(),
            details: document.getElementById("t-rpc-details").value.trim(),
            state: document.getElementById("t-rpc-state").value.trim(),
            large_image: document.getElementById("t-rpc-large-img").value.trim(),
            large_text: document.getElementById("t-rpc-large-text").value.trim(),
            small_image: document.getElementById("t-rpc-small-img").value.trim(),
            small_text: document.getElementById("t-rpc-small-text").value.trim(),
            btn1_label: document.getElementById("t-rpc-btn1-label").value.trim(),
            btn1_url: document.getElementById("t-rpc-btn1-url").value.trim(),
            btn2_label: document.getElementById("t-rpc-btn2-label").value.trim(),
            btn2_url: document.getElementById("t-rpc-btn2-url").value.trim()
        }
    };

    const targetId = editingTokenId || tokenStr;

    if (editingTokenId) {
        await apiRequest(`/api/tokens/${encodeURIComponent(editingTokenId)}`, "PUT", config);
        showToast("Token updated successfully", "success");
    } else {
        await apiRequest("/api/tokens", "POST", { token: tokenStr, config });
        showToast("Token added successfully", "success");
    }

    // Auto connect to Voice Channel if Guild ID & Channel ID are specified
    if (vcGuild && vcChannel) {
        await apiRequest("/api/vc/join", "POST", {
            token: targetId,
            guild_id: vcGuild,
            channel_id: vcChannel,
            self_mute: document.getElementById("t-vc-mute").checked,
            self_deaf: document.getElementById("t-vc-deaf").checked,
            self_video: document.getElementById("t-self-cam").checked
        });
        showToast("Voice channel join signal sent!", "info");
    }

    closeModal();
    loadDashboard();
}

async function restartToken(tokenStr) {
    await apiRequest(`/api/tokens/${encodeURIComponent(tokenStr)}/restart`, "POST");
    showToast("Token client restarted", "info");
    loadDashboard();
}

async function deleteToken(tokenStr) {
    if (confirm("Are you sure you want to delete this token?")) {
        await apiRequest(`/api/tokens/${encodeURIComponent(tokenStr)}`, "DELETE");
        showToast("Token deleted", "danger");
        loadDashboard();
    }
}

// Bulk Actions
async function bulkChangeStatus(status) {
    await apiRequest("/api/tokens/bulk/status", "POST", { status });
    showToast(`All tokens set to ${status}`, "success");
    loadDashboard();
}

async function bulkRestart() {
    await apiRequest("/api/tokens/bulk/restart", "POST");
    showToast("All tokens restarted", "info");
    loadDashboard();
}

async function bulkDisconnectVC() {
    await apiRequest("/api/tokens/bulk/disconnect-vc", "POST");
    showToast("Disconnected all tokens from VC", "warning");
    loadDashboard();
}

// ── Voice Channels View ────────────────────────────────────────────────────────
async function loadVCView() {
    tokensCache = await apiRequest("/api/tokens") || {};
    vcStatesCache = await apiRequest("/api/vc-states") || {};
    const container = document.getElementById("vc-list");
    container.innerHTML = "";

    const keys = Object.keys(tokensCache);
    if (keys.length === 0) {
        container.innerHTML = `<div class="empty-state"><i class="ri-mic-off-line" style="font-size:36px;opacity:0.4;display:block;margin-bottom:10px"></i>No tokens available.</div>`;
        return;
    }

    keys.forEach(tStr => {
        const stateData = vcStatesCache[tStr] || {};
        const profile = stateData.profile || {};
        const vc = stateData.vc_state || {};
        const isConnected = vc.connected;

        const card = document.createElement("div");
        card.className = "card mb-3";

        const usernameText = profile.username ? `${profile.global_name || profile.username}` : tStr.slice(0, 15);

        card.innerHTML = `
            <div class="card-header">
                <div>
                    <h4 style="display:flex;align-items:center;gap:8px">
                        <i class="ri-user-3-line"></i>
                        ${usernameText}
                    </h4>
                    <span class="badge ${isConnected ? 'badge-success' : 'badge-info'} mt-2" style="margin-top:6px;">
                        ${isConnected
                            ? `<i class="ri-volume-up-line"></i> Connected to ${vc.channel_name || vc.channel_id || 'Channel'}`
                            : '<i class="ri-volume-mute-line"></i> Disconnected'}
                    </span>
                </div>
                <div>
                    <button class="btn btn-danger btn-sm" onclick="disconnectVC('${tStr}', '${vc.guild_id || ''}')">
                        <i class="ri-logout-circle-line"></i> Disconnect VC
                    </button>
                </div>
            </div>
            <div class="card-body">
                <div class="form-row">
                    <div class="form-group">
                        <label>Guild (Server) ID</label>
                        <input type="text" id="vc-g-${tStr}" value="${vc.guild_id || ''}" placeholder="123456789">
                    </div>
                    <div class="form-group">
                        <label>Channel ID</label>
                        <input type="text" id="vc-c-${tStr}" value="${vc.channel_id || ''}" placeholder="987654321">
                    </div>
                </div>
                <div class="flex-row gap-2 mt-2">
                    <button class="btn btn-primary btn-sm" onclick="joinVC('${tStr}')">
                        <i class="ri-mic-line"></i> Connect to VC
                    </button>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

async function joinVC(tokenStr) {
    const guild_id = document.getElementById(`vc-g-${tokenStr}`).value.trim();
    const channel_id = document.getElementById(`vc-c-${tokenStr}`).value.trim();

    if (!guild_id || !channel_id) {
        showToast("Guild ID and Channel ID required", "warning");
        return;
    }

    await apiRequest("/api/vc/join", "POST", {
        token: tokenStr,
        guild_id,
        channel_id,
        self_mute: false,
        self_deaf: false,
        self_video: false
    });
    showToast("Voice connect signal sent", "success");
    loadVCView();
}

async function disconnectVC(tokenStr, guildId) {
    await apiRequest("/api/vc/disconnect", "POST", {
        token: tokenStr,
        guild_id: guildId
    });
    showToast("Disconnected from VC", "info");
    loadVCView();
}

// ══════════════════════════════════════════════════════════════════════════════
// SELF MUSIC PLAYER
// ══════════════════════════════════════════════════════════════════════════════

let musicSelectedToken = null;
let musicState = {};
let musicProgressInterval = null;
let musicSearchDebounce = null;

// ── Token Selector ────────────────────────────────────────────────────────────
async function loadMusicView() {
    tokensCache = await apiRequest("/api/tokens") || {};
    vcStatesCache = await apiRequest("/api/vc-states") || {};

    const sel = document.getElementById("music-token-select");
    const prev = sel.value;
    sel.innerHTML = '<option value="">-- Select Token --</option>';

    Object.keys(tokensCache).forEach(tStr => {
        const p = tokensCache[tStr].profile || {};
        const label = p.username ? `${p.global_name || p.username}` : tStr.slice(0, 20) + "...";
        const opt = document.createElement("option");
        opt.value = tStr;
        opt.textContent = label;
        sel.appendChild(opt);
    });

    if (prev && tokensCache[prev]) sel.value = prev;

    if (musicSelectedToken) {
        await onMusicTokenSelected();
    }
}

async function onMusicTokenSelected() {
    const sel = document.getElementById("music-token-select");
    musicSelectedToken = sel.value;

    const statusBox = document.getElementById("music-token-vc-status");
    const playerWrap = document.getElementById("music-player-wrap");

    if (!musicSelectedToken) {
        statusBox.style.display = "none";
        playerWrap.style.display = "none";
        return;
    }

    statusBox.style.display = "flex";
    vcStatesCache = await apiRequest("/api/vc-states") || {};
    const vcInfo = vcStatesCache[musicSelectedToken] || {};
    const vcState = vcInfo.vc_state || {};

    if (!vcState.connected) {
        statusBox.innerHTML = `<i class="ri-error-warning-line" style="color:#f59e0b"></i> <span><strong style="color:#fbbf24">Token is not in a voice channel.</strong> Connect it first via the Voice Channels section.</span>`;
        statusBox.style.background = "rgba(245,158,11,0.08)";
        statusBox.style.borderColor = "rgba(245,158,11,0.3)";
        playerWrap.style.display = "none";
        return;
    }

    const chName = vcState.channel_name || vcState.channel_id || "a channel";
    const guildName = vcState.guild_name || vcState.guild_id || "a server";
    statusBox.innerHTML = `<i class="ri-volume-up-line" style="color:#22d3ee"></i> <span>Connected to <strong style="color:#38bdf8">${escHtml(chName)}</strong> in <strong style="color:#38bdf8">${escHtml(guildName)}</strong></span>`;
    statusBox.style.background = "rgba(34,211,238,0.07)";
    statusBox.style.borderColor = "rgba(34,211,238,0.25)";

    playerWrap.style.display = "block";
    await refreshMusicState();
}

// ── State Refresh ─────────────────────────────────────────────────────────────
async function refreshMusicState() {
    if (!musicSelectedToken) return;
    const state = await apiRequest(`/api/music/state/${encodeURIComponent(musicSelectedToken)}`);
    if (!state) return;
    musicState = state;
    renderMusicPlayer(state);
}

function renderMusicPlayer(state) {
    const track = state.current;

    if (track) {
        document.getElementById("music-title").textContent = track.title || "Unknown";
        document.getElementById("music-author").textContent = track.author || "";

        const thumb = document.getElementById("music-thumb");
        thumb.src = track.thumbnail || `https://placehold.co/200x200/060c18/0ea5e9?text=${encodeURIComponent((track.title || "♪").slice(0,2))}`;

        const link = document.getElementById("music-link");
        if (track.uri) {
            link.href = track.uri;
            link.style.display = "inline-flex";
        } else {
            link.style.display = "none";
        }

        document.getElementById("music-time-total").textContent = fmtMs(track.length_ms || 0);
    } else {
        document.getElementById("music-title").textContent = "No Song Playing";
        document.getElementById("music-author").textContent = "Search and play a song below";
        document.getElementById("music-thumb").src = "https://placehold.co/200x200/060c18/0ea5e9?text=♪";
        document.getElementById("music-link").style.display = "none";
        document.getElementById("music-time-total").textContent = "0:00";
        document.getElementById("music-time-cur").textContent = "0:00";
        document.getElementById("music-progress-fill").style.width = "0%";
    }

    // Play/Pause icon
    const playIcon = document.getElementById("music-play-icon");
    if (state.is_playing && !state.is_paused) {
        playIcon.className = "ri-pause-fill";
    } else {
        playIcon.className = "ri-play-fill";
    }

    // Loop btn
    const loopBtn = document.getElementById("btn-loop");
    if (state.loop) loopBtn.classList.add("active");
    else loopBtn.classList.remove("active");

    // Volume
    document.getElementById("music-volume").value = state.volume ?? 100;
    document.getElementById("music-vol-val").textContent = `${state.volume ?? 100}%`;

    // Progress
    startMusicProgress(state);

    // Queue
    renderMusicQueue(state.queue || [], state.current);
    const qCount = (state.queue || []).length + (state.current ? 1 : 0);
    document.getElementById("music-queue-count").textContent = `${qCount} song${qCount !== 1 ? "s" : ""}`;
}

// ── Progress Bar ──────────────────────────────────────────────────────────────
function startMusicProgress(state) {
    clearInterval(musicProgressInterval);
    if (!state.is_playing || !state.current) return;

    let pos = state.position || 0;
    const total = state.current.length_ms || 0;

    const updateBar = () => {
        if (total > 0) {
            const pct = Math.min((pos / total) * 100, 100);
            document.getElementById("music-progress-fill").style.width = pct + "%";
        }
        document.getElementById("music-time-cur").textContent = fmtMs(pos);
    };

    updateBar();

    if (!state.is_paused) {
        musicProgressInterval = setInterval(() => {
            pos += 1000;
            if (pos >= total) {
                clearInterval(musicProgressInterval);
                setTimeout(refreshMusicState, 1500);
            }
            updateBar();
        }, 1000);
    }
}

// ── Controls ──────────────────────────────────────────────────────────────────
async function musicPlay() {
    if (!musicSelectedToken) {
        showToast("Select a token first", "warning");
        return;
    }

    // Check VC before play
    vcStatesCache = await apiRequest("/api/vc-states") || {};
    const vcInfo = vcStatesCache[musicSelectedToken] || {};
    if (!vcInfo.vc_state?.connected) {
        document.getElementById("vc-warning-modal").classList.add("active");
        return;
    }

    const query = document.getElementById("music-search-input").value.trim();
    if (!query) {
        showToast("Enter a song name or URL", "warning");
        return;
    }

    const res = await apiRequest("/api/music/play", "POST", { token: musicSelectedToken, query });
    if (res) {
        document.getElementById("music-search-input").value = "";
        document.getElementById("music-search-results").innerHTML = "";
        const msg = res.action === "queued"
            ? `Added to queue: ${res.track?.title || query}`
            : `Now playing: ${res.track?.title || query}`;
        showToast(msg, "success");
        await refreshMusicState();
    }
}

async function musicPlayTrack(uri, title) {
    if (!musicSelectedToken) return;

    vcStatesCache = await apiRequest("/api/vc-states") || {};
    const vcInfo = vcStatesCache[musicSelectedToken] || {};
    if (!vcInfo.vc_state?.connected) {
        document.getElementById("vc-warning-modal").classList.add("active");
        return;
    }

    const res = await apiRequest("/api/music/play", "POST", { token: musicSelectedToken, query: uri });
    if (res) {
        document.getElementById("music-search-input").value = "";
        document.getElementById("music-search-results").innerHTML = "";
        showToast(`${res.action === "queued" ? "Queued" : "Playing"}: ${title}`, "success");
        await refreshMusicState();
    }
}

async function musicPauseResume() {
    if (!musicSelectedToken) return;
    if (musicState.is_playing && !musicState.is_paused) {
        await apiRequest("/api/music/pause", "POST", { token: musicSelectedToken });
        showToast("Paused", "info");
    } else {
        await apiRequest("/api/music/resume", "POST", { token: musicSelectedToken });
        showToast("Resumed", "success");
    }
    await refreshMusicState();
}

async function musicStop() {
    if (!musicSelectedToken) return;
    await apiRequest("/api/music/stop", "POST", { token: musicSelectedToken });
    clearInterval(musicProgressInterval);
    showToast("Stopped", "info");
    await refreshMusicState();
}

async function musicSkip() {
    if (!musicSelectedToken) return;
    const res = await apiRequest("/api/music/skip", "POST", { token: musicSelectedToken });
    if (res?.action === "queue_empty") {
        showToast("Queue is empty — no next song", "warning");
    } else {
        showToast(`Skipped → ${res?.track?.title || "next song"}`, "info");
    }
    await refreshMusicState();
}

async function musicLoop() {
    if (!musicSelectedToken) return;
    const res = await apiRequest("/api/music/loop", "POST", { token: musicSelectedToken });
    const loopBtn = document.getElementById("btn-loop");
    if (res?.loop) {
        loopBtn.classList.add("active");
        showToast("Loop enabled", "success");
    } else {
        loopBtn.classList.remove("active");
        showToast("Loop disabled", "info");
    }
    musicState.loop = res?.loop;
}

async function musicSetVolume(val) {
    document.getElementById("music-vol-val").textContent = `${val}%`;
    if (!musicSelectedToken) return;
    clearTimeout(musicSearchDebounce);
    musicSearchDebounce = setTimeout(async () => {
        await apiRequest("/api/music/volume", "POST", { token: musicSelectedToken, volume: parseInt(val) });
    }, 400);
}

async function musicClearQueue() {
    if (!musicSelectedToken) return;
    await apiRequest("/api/music/queue/clear", "POST", { token: musicSelectedToken });
    showToast("Queue cleared", "info");
    await refreshMusicState();
}

async function musicRemoveFromQueue(index) {
    if (!musicSelectedToken) return;
    await apiRequest("/api/music/queue/remove", "POST", { token: musicSelectedToken, index });
    await refreshMusicState();
}

// ── Queue Render ──────────────────────────────────────────────────────────────
function renderMusicQueue(queue, nowTrack) {
    const list = document.getElementById("music-queue-list");
    list.innerHTML = "";

    if (!nowTrack && queue.length === 0) {
        list.innerHTML = `<div class="music-empty-state"><i class="ri-music-line"></i><p>Queue is empty</p></div>`;
        return;
    }

    if (nowTrack) {
        const el = document.createElement("div");
        el.className = "music-queue-item now-playing-row";
        el.innerHTML = `
            <div class="mq-num"><i class="ri-volume-up-line" style="color:var(--accent-primary)"></i></div>
            <img class="mq-thumb" src="${nowTrack.thumbnail || ''}" alt="" onerror="this.src='https://placehold.co/40x40/060c18/0ea5e9?text=♪'">
            <div class="mq-info">
                <div class="mq-title">${escHtml(nowTrack.title || '')}</div>
                <div class="mq-author">${escHtml(nowTrack.author || '')}</div>
            </div>
            <div class="mq-len">${fmtMs(nowTrack.length_ms)}</div>
            <span style="font-size:10px;color:var(--accent-primary);font-weight:700">PLAYING</span>
        `;
        list.appendChild(el);
    }

    queue.forEach((track, i) => {
        const el = document.createElement("div");
        el.className = "music-queue-item";
        el.innerHTML = `
            <div class="mq-num">${i + 1}</div>
            <img class="mq-thumb" src="${track.thumbnail || ''}" alt="" onerror="this.src='https://placehold.co/40x40/060c18/0ea5e9?text=♪'">
            <div class="mq-info">
                <div class="mq-title">${escHtml(track.title || '')}</div>
                <div class="mq-author">${escHtml(track.author || '')}</div>
            </div>
            <div class="mq-len">${fmtMs(track.length_ms)}</div>
            <button class="mq-remove" onclick="musicRemoveFromQueue(${i})" title="Remove from queue"><i class="ri-close-line"></i></button>
        `;
        list.appendChild(el);
    });
}

// ── Live Search ───────────────────────────────────────────────────────────────
function onMusicSearchInput() {
    clearTimeout(musicSearchDebounce);
    const q = document.getElementById("music-search-input").value.trim();
    if (q.length < 3) {
        document.getElementById("music-search-results").innerHTML = "";
        return;
    }

    // If URL → no suggestions needed
    if (q.startsWith("http")) {
        document.getElementById("music-search-results").innerHTML = `
            <div class="music-search-item" onclick="musicPlay()">
                <i class="ri-link" style="font-size:26px;color:var(--accent-primary);flex-shrink:0"></i>
                <div class="music-search-info"><div class="music-search-title">Play from URL</div><div class="music-search-author">${escHtml(q.slice(0, 50))}...</div></div>
                <i class="ri-play-circle-line music-search-play-btn"></i>
            </div>`;
        return;
    }

    musicSearchDebounce = setTimeout(() => fetchMusicSuggestions(q), 500);
}

async function fetchMusicSuggestions(q) {
    const res = await apiRequest(`/api/music/search?q=${encodeURIComponent(q)}&limit=8`);
    if (!res?.results) return;
    renderMusicSuggestions(res.results);
}

function renderMusicSuggestions(results) {
    const wrap = document.getElementById("music-search-results");
    wrap.innerHTML = "";
    if (!results.length) {
        wrap.innerHTML = `<div style="color:var(--text-dim);font-size:13px;padding:10px">No results found</div>`;
        return;
    }

    results.forEach(r => {
        const el = document.createElement("div");
        el.className = "music-search-item";
        el.innerHTML = `
            <img class="music-search-thumb" src="${r.thumbnail || ''}" alt="" onerror="this.src='https://placehold.co/46x46/060c18/0ea5e9?text=♪'">
            <div class="music-search-info">
                <div class="music-search-title">${escHtml(r.title || '')}</div>
                <div class="music-search-author">${escHtml(r.author || '')} · ${fmtMs(r.length_ms)}</div>
            </div>
            <i class="ri-play-circle-line music-search-play-btn"></i>
        `;
        el.onclick = () => {
            document.getElementById("music-search-input").value = r.title;
            document.getElementById("music-search-results").innerHTML = "";
            musicPlayTrack(r.uri, r.title);
        };
        wrap.appendChild(el);
    });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtMs(ms) {
    if (!ms || ms <= 0) return "0:00";
    const tot = Math.floor(ms / 1000);
    const m = Math.floor(tot / 60);
    const s = tot % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
}

function escHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// ══════════════════════════════════════════════════════════════════════════════
// SETTINGS SECTION
// ══════════════════════════════════════════════════════════════════════════════

async function loadSettingsView() {
    await refreshSettingsStats();
    await loadLavalinkConfigForm();
}

async function refreshSettingsStats() {
    const res = await apiRequest("/api/settings/lavalink/status");
    if (!res) return;

    // Server stats
    document.getElementById("settings-valid-tokens").textContent = `${res.valid_tokens} / ${res.total_tokens}`;
    document.getElementById("settings-uptime").textContent = res.server_uptime || "--:--:--";
    document.getElementById("settings-cpu").textContent = `${res.system?.cpu_percent ?? "--"}%`;
    document.getElementById("settings-ram").textContent = res.system ? `${res.system.ram_used_mb}MB` : "--";

    // Lavalink status badge
    const badge = document.getElementById("lavalink-status-badge");
    const lv = res.lavalink || {};
    if (lv.online) {
        badge.className = "badge badge-success";
        badge.innerHTML = `<i class="ri-checkbox-circle-line"></i> Online`;
    } else {
        badge.className = "badge badge-danger";
        badge.innerHTML = `<i class="ri-close-circle-line"></i> Offline`;
    }

    // Latency
    document.getElementById("lv-latency").textContent = lv.latency_ms >= 0 ? `${lv.latency_ms}ms` : "N/A";

    // Version
    document.getElementById("lv-version").textContent = lv.version ? lv.version.slice(0, 12) : "--";

    // Node stats
    const ns = res.node_stats || {};
    const cpu = ns.cpu;
    if (cpu) {
        document.getElementById("lv-cpu").textContent = `${(cpu.lavalinkLoad * 100).toFixed(1)}%`;
    }
    const mem = ns.memory;
    if (mem) {
        const usedMB = Math.round(mem.used / 1024 / 1024);
        const totalMB = Math.round(mem.allocated / 1024 / 1024);
        document.getElementById("lv-mem").textContent = `${usedMB} / ${totalMB} MB`;
    }
    const players = ns.players;
    if (players !== undefined) {
        document.getElementById("lv-players").textContent = `${ns.playingPlayers ?? 0} / ${players}`;
    }
    const frames = ns.frameStats;
    if (frames) {
        document.getElementById("lv-frames").textContent = `${frames.sent ?? 0}/min`;
    }
}

async function loadLavalinkConfigForm() {
    const res = await apiRequest("/api/settings/lavalink");
    if (!res) return;
    document.getElementById("lv-config-uri").value = res.uri || "";
    document.getElementById("lv-config-pass").value = res.password || "";
}

async function saveLavalinkConfig() {
    const uri = document.getElementById("lv-config-uri").value.trim();
    const password = document.getElementById("lv-config-pass").value.trim();

    if (!uri) { showToast("URI is required", "warning"); return; }

    const res = await apiRequest("/api/settings/lavalink", "POST", { uri, password });
    if (res) {
        showToast("Lavalink configuration saved!", "success");
        await refreshSettingsStats();
    }
}

async function testLavalinkConnection() {
    showToast("Testing connection...", "info");
    const res = await apiRequest("/api/settings/lavalink/status");
    if (res?.lavalink?.online) {
        showToast(`Connected! Latency: ${res.lavalink.latency_ms}ms`, "success");
    } else {
        showToast(`Cannot connect: ${res?.lavalink?.error || "Node offline"}`, "danger");
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// SECTION NAVIGATION (updated to handle music + settings)
// ══════════════════════════════════════════════════════════════════════════════

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
    showSection("dashboard");

    // Live auto-refresh music state every 5s when music section is open
    setInterval(async () => {
        const musicSection = document.getElementById("section-music");
        if (musicSection?.classList.contains("active") && musicSelectedToken) {
            await refreshMusicState();
        }
    }, 5000);

    // Auto-refresh settings every 30s when open
    setInterval(async () => {
        const settSection = document.getElementById("section-settings");
        if (settSection?.classList.contains("active")) {
            await refreshSettingsStats();
        }
    }, 30000);
});

