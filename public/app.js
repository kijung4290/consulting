const form = document.querySelector("#transcribeForm");
const mediaFileInput = document.querySelector("#mediaFile");
const submitButton = document.querySelector("#submitButton");
const btnText = document.querySelector(".btn-text");
const btnLoader = document.querySelector(".btn-loader");
const statusBox = document.querySelector("#status");
const resultSection = document.querySelector("#resultSection");
const speakerCountField = document.querySelector("#speakerCountField");
const expectedSpeakersInput = document.querySelector("#expectedSpeakers");
const modeRadios = form.querySelectorAll('input[name="mode"]');
const summaryText = document.querySelector("#summaryText");
const transcriptText = document.querySelector("#transcriptText");
const copySummaryButton = document.querySelector("#copySummaryButton");
const copyTranscriptButton = document.querySelector("#copyTranscriptButton");

// Recording related elements
const recordButton = document.querySelector("#recordButton");
const stopRecordButton = document.querySelector("#stopRecordButton");
const recordingIndicator = document.querySelector("#recordingIndicator");
const recordTime = document.querySelector("#recordTime");
const audioPlayback = document.querySelector("#audioPlayback");
const clearRecordButton = document.querySelector("#clearRecordButton");

let latestSummary = "";
let latestTranscript = "";
let mediaRecorder;
let audioChunks = [];
let recordedBlob = null;
let recordingTimer;
let secondsRecorded = 0;
let supabase;

document.addEventListener("DOMContentLoaded", async () => {
  const configRes = await fetch("/api/config");
  const config = await configRes.json();
  
  if (config.supabaseUrl && config.supabaseAnonKey) {
    supabase = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
    const { data: { session }, error } = await supabase.auth.getSession();
    
    if (error || !session) {
      window.location.href = "/login.html";
      return;
    }
  } else if (!config.supabaseUrl) {
    // No Supabase URL configured, proceed normally
  }
});

const logoutBtn = document.getElementById("logoutBtn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    if (supabase) {
      await supabase.auth.signOut();
    }
    window.location.href = "/login.html";
  });
}

function syncMode() {
  const isDiarize = form.querySelector('input[name="mode"]:checked')?.value === "diarize";
  if (isDiarize) {
    speakerCountField.classList.remove("hidden");
  } else {
    speakerCountField.classList.add("hidden");
  }
}

modeRadios.forEach(radio => {
  radio.addEventListener("change", syncMode);
});
syncMode();

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = mediaFileInput.files[0];
  if (!file && !recordedBlob) {
    renderStatus("파일을 업로드하거나 녹음을 진행해주세요.", "error");
    return;
  }

  submitButton.disabled = true;
  btnText.textContent = "분석 및 일지 생성 중...";
  btnLoader.classList.remove("hidden");
  resultSection.classList.add("hidden");
  statusBox.classList.remove("hidden");

  renderStatus("음성 분석 및 AI 상담 일지 생성을 진행 중입니다. 잠시만 기다려주세요 (최대 몇 분 소요 가능)...", "loading");

  const formData = new FormData();
  
  if (recordedBlob) {
    // Append the recorded webm file
    formData.append("mediaFile", recordedBlob, "recording.webm");
  } else {
    // Append the uploaded file
    formData.append("mediaFile", file);
  }
  
  const mode = form.querySelector('input[name="mode"]:checked')?.value || "plain";
  formData.append("mode", mode);

  const consultationType = form.querySelector('input[name="consultationType"]:checked')?.value || "general";
  formData.append("consultationType", consultationType);

  if (mode === "diarize" && expectedSpeakersInput.value.trim()) {
    formData.append("expectedSpeakers", expectedSpeakersInput.value.trim());
  }

  const headers = {};
  if (supabase) {
    const { data: { session } } = await supabase.auth.getSession();
    if (session) {
      headers["Authorization"] = `Bearer ${session.access_token}`;
    } else {
      window.location.href = "/login.html";
      return;
    }
  }

  try {
    const response = await fetch("/api/transcribe", {
      method: "POST",
      headers,
      body: formData
    });

    const payload = await response.json();

    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        throw new Error(payload.error || "분석 요청 권한이 없습니다. 관리자 승인을 확인하세요.");
      }
      throw new Error(payload.error || "분석 요청에 실패했습니다.");
    }

    latestSummary = payload.summary || "요약 내용을 불러오지 못했습니다.";
    latestTranscript = payload.transcriptText || "";

    summaryText.value = latestSummary;
    transcriptText.value = latestTranscript;

    resultSection.classList.remove("hidden");
    
    // Auto-resize text areas
    summaryText.style.height = 'auto';
    summaryText.style.height = (summaryText.scrollHeight) + 'px';
    transcriptText.style.height = 'auto';
    transcriptText.style.height = (transcriptText.scrollHeight) + 'px';

    renderStatus("상담 일지 생성이 완료되었습니다.", "success");
  } catch (error) {
    renderStatus(error.message, "error");
  } finally {
    submitButton.disabled = false;
    btnText.textContent = "음성 분석 및 일지 생성 시작";
    btnLoader.classList.add("hidden");
    setTimeout(() => {
        if(statusBox.classList.contains("success")) {
            statusBox.classList.add("hidden");
        }
    }, 5000);
  }
});

copySummaryButton.addEventListener("click", async () => {
  if (!latestSummary) return;
  try {
    await navigator.clipboard.writeText(latestSummary);
    copySummaryButton.textContent = "복사 완료!";
    setTimeout(() => copySummaryButton.textContent = "일지 복사", 2000);
  } catch (_error) {
    alert("복사 실패. 텍스트를 직접 선택해서 복사해주세요.");
  }
});

copyTranscriptButton.addEventListener("click", async () => {
  if (!latestTranscript) return;
  try {
    await navigator.clipboard.writeText(latestTranscript);
    copyTranscriptButton.textContent = "복사 완료!";
    setTimeout(() => copyTranscriptButton.textContent = "기록 복사", 2000);
  } catch (_error) {
    alert("복사 실패. 텍스트를 직접 선택해서 복사해주세요.");
  }
});

function renderStatus(message, state) {
  statusBox.textContent = message;
  statusBox.className = `status ${state}`;
}

// --- RECORDING LOGIC ---
recordButton.addEventListener("click", async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    // WebM format works well for web recorders and is supported by our backend
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    audioChunks = [];

    mediaRecorder.addEventListener("dataavailable", event => {
      audioChunks.push(event.data);
    });

    mediaRecorder.addEventListener("stop", () => {
      recordedBlob = new Blob(audioChunks, { type: "audio/webm" });
      const audioUrl = URL.createObjectURL(recordedBlob);
      audioPlayback.src = audioUrl;
      audioPlayback.classList.remove("hidden");
      clearRecordButton.classList.remove("hidden");
      
      // Stop microphone stream when finished
      stream.getTracks().forEach(track => track.stop());
    });

    mediaRecorder.start();
    recordButton.classList.add("hidden");
    stopRecordButton.classList.remove("hidden");
    recordingIndicator.classList.remove("hidden");
    mediaFileInput.disabled = true;

    secondsRecorded = 0;
    recordTime.textContent = formatTimer(0);
    recordingTimer = setInterval(() => {
      secondsRecorded++;
      recordTime.textContent = formatTimer(secondsRecorded);
    }, 1000);

  } catch (err) {
    alert("마이크 접근 권한이 거부되었거나 오류가 발생했습니다.");
    console.error(err);
  }
});

stopRecordButton.addEventListener("click", () => {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  clearInterval(recordingTimer);
  stopRecordButton.classList.add("hidden");
  recordingIndicator.classList.add("hidden");
});

clearRecordButton.addEventListener("click", () => {
  recordedBlob = null;
  audioPlayback.src = "";
  audioPlayback.classList.add("hidden");
  clearRecordButton.classList.add("hidden");
  recordButton.classList.remove("hidden");
  mediaFileInput.disabled = false;
});

function formatTimer(sec) {
  const m = String(Math.floor(sec / 60)).padStart(2, '0');
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}
