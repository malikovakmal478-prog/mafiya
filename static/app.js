const tgApp = window.Telegram.WebApp;
tgApp.ready();
tgApp.expand();

const initData = tgApp.initData || "";

const loadingEl = document.getElementById("loading");
const notJoinedEl = document.getElementById("notJoined");
const cardWrapEl = document.getElementById("cardWrap");
const roleCardEl = document.getElementById("roleCard");
const roleNameEl = document.getElementById("roleName");
const roleDescEl = document.getElementById("roleDesc");
const phaseLabelEl = document.getElementById("phaseLabel");
const voiceBtn = document.getElementById("voiceBtn");
const peersEl = document.getElementById("peers");

const PHASE_LABELS = {
  lobby: "Lobby — o'yin hali boshlanmagan",
  night: "🌙 Kecha — shahar uxlamoqda",
  day: "🌅 Tong",
  voting: "🗳 Ovoz berish vaqti",
  finished: "🏁 O'yin tugadi",
};

let chatId = null;

async function loadMe() {
  try {
    const res = await fetch(`/api/me?initData=${encodeURIComponent(initData)}`);
    const data = await res.json();
    loadingEl.classList.add("hidden");

    if (!data.joined) {
      notJoinedEl.classList.remove("hidden");
      return;
    }

    chatId = data.chat_id;
    roleNameEl.textContent = data.role_name;
    roleDescEl.textContent = data.role_desc;
    phaseLabelEl.textContent = PHASE_LABELS[data.phase] || "";
    cardWrapEl.classList.remove("hidden");
  } catch (e) {
    loadingEl.textContent = "Ulanishda xatolik. Qayta urinib ko'ring.";
  }
}

roleCardEl.addEventListener("click", () => {
  roleCardEl.classList.toggle("flipped");
});

loadMe();

// ---------------------------------------------------------------------
// Ovozli xona — WebRTC mesh, Telegram voice chat'iga bog'liq emas
// ---------------------------------------------------------------------
let socket = null;
let localStream = null;
let joinedVoice = false;
const peerConnections = {}; // sid -> RTCPeerConnection
const audioEls = {}; // sid -> <audio>

const ICE_SERVERS = [{ urls: "stun:stun.l.google.com:19302" }];

async function toggleVoice() {
  if (!chatId) return;

  if (joinedVoice) {
    leaveVoice();
    return;
  }

  try {
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch (e) {
    alert("Mikrofonga ruxsat berilmadi.");
    return;
  }

  socket = io({ transports: ["websocket"] });

  socket.on("connect", () => {
    socket.emit("join_voice", { room: chatId });
  });

  socket.on("existing_peers", ({ peers }) => {
    peers.forEach((sid) => createPeerConnection(sid, true));
  });

  socket.on("peer_joined", ({ sid }) => {
    createPeerConnection(sid, false);
  });

  socket.on("peer_left", ({ sid }) => {
    removePeer(sid);
  });

  socket.on("signal", async (data) => {
    const { from, type, sdp, candidate } = data;
    let pc = peerConnections[from];
    if (!pc) pc = createPeerConnection(from, false);

    if (type === "offer") {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      socket.emit("signal", { room: chatId, target: from, type: "answer", sdp: answer });
    } else if (type === "answer") {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    } else if (type === "candidate" && candidate) {
      try { await pc.addIceCandidate(candidate); } catch (e) {}
    }
  });

  joinedVoice = true;
  voiceBtn.textContent = "🔇 Xonadan chiqish";
  voiceBtn.classList.add("active");
}

function createPeerConnection(sid, isInitiator) {
  const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
  peerConnections[sid] = pc;

  localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));

  pc.onicecandidate = (e) => {
    if (e.candidate) {
      socket.emit("signal", { room: chatId, target: sid, type: "candidate", candidate: e.candidate });
    }
  };

  pc.ontrack = (e) => {
    let audio = audioEls[sid];
    if (!audio) {
      audio = document.createElement("audio");
      audio.autoplay = true;
      document.body.appendChild(audio);
      audioEls[sid] = audio;
    }
    audio.srcObject = e.streams[0];
  };

  if (isInitiator) {
    pc.onnegotiationneeded = async () => {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      socket.emit("signal", { room: chatId, target: sid, type: "offer", sdp: offer });
    };
  }

  renderPeers();
  return pc;
}

function removePeer(sid) {
  if (peerConnections[sid]) {
    peerConnections[sid].close();
    delete peerConnections[sid];
  }
  if (audioEls[sid]) {
    audioEls[sid].remove();
    delete audioEls[sid];
  }
  renderPeers();
}

function renderPeers() {
  const n = Object.keys(peerConnections).length;
  peersEl.innerHTML = n ? `${"● ".repeat(n).trim()} ${n} kishi xonada` : "";
}

function leaveVoice() {
  socket.emit("leave_voice", { room: chatId });
  Object.keys(peerConnections).forEach(removePeer);
  if (localStream) localStream.getTracks().forEach((t) => t.stop());
  socket.disconnect();
  joinedVoice = false;
  voiceBtn.textContent = "🎙 Ovozli xonaga qo'shilish";
  voiceBtn.classList.remove("active");
  peersEl.innerHTML = "";
}

voiceBtn.addEventListener("click", toggleVoice);
