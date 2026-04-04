import path from "path";
import { fileURLToPath } from "url";

import dotenv from "dotenv";
import express from "express";
import fs from "fs-extra";
import multer from "multer";
import { createClient } from "@supabase/supabase-js";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const app = express();

const PORT = Number(process.env.PORT || 3000);
const MAX_PORT_ATTEMPTS = 10;
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const ASSEMBLYAI_API_KEY = process.env.ASSEMBLYAI_API_KEY;

const OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions";
const OPENAI_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe";
const ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com/v2";
const ASSEMBLYAI_UPLOAD_URL = `${ASSEMBLYAI_BASE_URL}/upload`;
const ASSEMBLYAI_TRANSCRIPT_URL = `${ASSEMBLYAI_BASE_URL}/transcript`;
const ASSEMBLYAI_SPEECH_MODELS = ["universal-2"];

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_KEY;

let supabase = null;
if (SUPABASE_URL && SUPABASE_KEY) {
  supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
}

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const SUPPORTED_EXTENSIONS = new Set([".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"]);
const UPLOADS_DIR = path.join(__dirname, "uploads");

await fs.ensureDir(UPLOADS_DIR);

const storage = multer.diskStorage({
  destination: (_req, _file, callback) => callback(null, UPLOADS_DIR),
  filename: (_req, file, callback) => {
    const safeName = `${Date.now()}-${file.originalname.replace(/[^\w.\-]/g, "_")}`;
    callback(null, safeName);
  }
});

const upload = multer({
  storage,
  limits: {
    fileSize: MAX_UPLOAD_BYTES
  },
  fileFilter: (_req, file, callback) => {
    const extension = path.extname(file.originalname).toLowerCase();

    if (!SUPPORTED_EXTENSIONS.has(extension)) {
      callback(new Error("Supported formats: mp3, mp4, mpeg, mpga, m4a, wav, webm."));
      return;
    }

    callback(null, true);
  }
});

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

app.get("/api/health", (_req, res) => {
  res.json({
    ok: true,
    openaiConfigured: Boolean(OPENAI_API_KEY),
    assemblyConfigured: Boolean(ASSEMBLYAI_API_KEY),
    supabaseConfigured: Boolean(SUPABASE_URL && SUPABASE_KEY),
    openaiModel: OPENAI_TRANSCRIBE_MODEL,
    maxUploadMb: MAX_UPLOAD_BYTES / (1024 * 1024)
  });
});

app.get("/api/config", (_req, res) => {
  res.json({
    supabaseUrl: SUPABASE_URL || null,
    supabaseAnonKey: SUPABASE_KEY || null
  });
});

// Auth Middleware
async function requireAuth(req, res, next) {
  if (!supabase) {
    console.warn("Supabase is not configured, skipping auth check.");
    return next();
  }

  const authHeader = req.headers.authorization;
  if (!authHeader) {
    return res.status(401).json({ error: "로그인이 필요합니다." });
  }

  const token = authHeader.replace("Bearer ", "");
  const { data: { user }, error } = await supabase.auth.getUser(token);
  
  if (error || !user) {
    return res.status(401).json({ error: "유효하지 않은 토큰입니다. 다시 로그인해주세요." });
  }

  // Check profile status
  const { data: profile, error: dbError } = await supabase
    .from("profiles")
    .select("status")
    .eq("id", user.id)
    .single();

  if (dbError || !profile || profile.status !== "approved") {
    return res.status(403).json({ error: "관리자의 승인이 필요한 계정입니다. 가입 승인을 기다려주세요." });
  }

  req.user = user;
  next();
}

app.post("/api/transcribe", requireAuth, upload.single("mediaFile"), async (req, res) => {
  const uploadedFilePath = req.file?.path;

  try {
    if (!req.file) {
      return res.status(400).json({
        error: "Upload an audio or video file first."
      });
    }

    const mode = req.body?.mode === "diarize" ? "diarize" : "plain";
    const prompt = req.body?.prompt?.trim();
    const expectedSpeakers = parseExpectedSpeakers(req.body?.expectedSpeakers);
    const consultationType = req.body?.consultationType || "general";

    const payload = mode === "diarize"
      ? await transcribeWithAssemblyAI({
        filePath: req.file.path,
        mimeType: req.file.mimetype,
        expectedSpeakers
      })
      : await transcribeWithOpenAI({
        filePath: req.file.path,
        originalName: req.file.originalname,
        mimeType: req.file.mimetype,
        prompt
      });

    const summary = await summarizeTranscript(payload.transcriptText, consultationType);

    res.json({
      fileName: req.file.originalname,
      fileSizeBytes: req.file.size,
      mode,
      summary,
      ...payload
    });
  } catch (error) {
    const statusCode = error instanceof multer.MulterError ? 400 : error.statusCode || 500;
    res.status(statusCode).json({
      error: extractErrorMessage(error)
    });
  } finally {
    if (uploadedFilePath) {
      await fs.remove(uploadedFilePath).catch(() => { });
    }
  }
});

async function transcribeWithOpenAI({ filePath, originalName, mimeType, prompt }) {
  if (!OPENAI_API_KEY) {
    const error = new Error("OPENAI_API_KEY is missing. Add it to your .env file for plain transcription.");
    error.statusCode = 500;
    throw error;
  }

  const buffer = await fs.readFile(filePath);
  const formData = new FormData();
  const file = new File([buffer], originalName, {
    type: mimeType || "application/octet-stream"
  });

  formData.append("file", file);
  formData.append("model", OPENAI_TRANSCRIBE_MODEL);
  formData.append("response_format", "json");

  if (prompt) {
    formData.append("prompt", prompt);
  }

  const response = await fetch(OPENAI_TRANSCRIPTIONS_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`
    },
    body: formData
  });

  const payload = await parseResponseBody(response);

  if (!response.ok) {
    const error = new Error(extractOpenAIError(payload));
    error.statusCode = response.status;
    throw error;
  }

  const transcript = typeof payload === "string" ? { text: payload } : payload;

  return {
    provider: "openai",
    model: OPENAI_TRANSCRIBE_MODEL,
    prompt: prompt || null,
    transcriptText: (transcript.text || "").trim(),
    speakerSegments: []
  };
}

async function transcribeWithAssemblyAI({ filePath, mimeType, expectedSpeakers }) {
  if (!ASSEMBLYAI_API_KEY) {
    const error = new Error("ASSEMBLYAI_API_KEY is missing. Add it to your .env file for speaker diarization.");
    error.statusCode = 500;
    throw error;
  }

  const audioUrl = await uploadToAssemblyAI(filePath, mimeType);
  const requestBody = {
    audio_url: audioUrl,
    speech_models: ASSEMBLYAI_SPEECH_MODELS,
    language_detection: true,
    speaker_labels: true
  };

  if (expectedSpeakers) {
    requestBody.speakers_expected = expectedSpeakers;
  }

  const createResponse = await fetch(ASSEMBLYAI_TRANSCRIPT_URL, {
    method: "POST",
    headers: {
      Authorization: ASSEMBLYAI_API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(requestBody)
  });

  const createPayload = await parseResponseBody(createResponse);

  if (!createResponse.ok) {
    const error = new Error(extractAssemblyError(createPayload));
    error.statusCode = createResponse.status;
    throw error;
  }

  const transcript = await pollAssemblyTranscript(createPayload.id);

  const rawSegments = transcript.utterances || [];
  const speakerSegments = formatSpeakerSegments(rawSegments);

  // 화자 라벨링된 전체 텍스트 생성
  let labeledText = (transcript.text || "").trim();
  if (rawSegments.length > 0) {
    labeledText = speakerSegments
      .map(seg => `[화자 ${seg.speaker}]: ${seg.text}`)
      .join("\n\n");
  }

  return {
    provider: "assemblyai",
    model: ASSEMBLYAI_SPEECH_MODELS[0],
    prompt: null,
    transcriptText: labeledText,
    speakerSegments,
    expectedSpeakers: expectedSpeakers || null,
    detectedLanguage: transcript.language_code || null
  };
}

async function summarizeTranscript(transcriptText, consultationType = "general") {
  if (!OPENAI_API_KEY) {
    return "OpenAI API 키가 설정되지 않아 요약을 생성할 수 없습니다.";
  }

  let systemPrompt = "당신은 전문 상담가입니다. 제공된 음성 기록 텍스트를 분석하여, [상담 일자/시간], [내담자 주요 호소 문제], [상담 주요 내용], [상담자 의견 및 향후 계획] 등 체계적인 상담 일지 형태로 요약해 주세요. 전문적이고 간결한 어조를 사용하세요.";

  switch (consultationType) {
    case "psychological":
      systemPrompt = "당신은 경험이 풍부한 전문 심리 상담가입니다. 제공된 대화에서 내담자의 발화 내용을 깊이 있게 분석하여 다음 형태로 심리학적 상담 일지를 작성하세요: [내담자 주요 호소 문제], [감정선 및 심리적 상태 변화], [관찰된 행동/언어적 특이점], [상담자 개입 및 내담자 반응], [향후 상담 방향 및 제언]. 전문가적인 공감과 분석의 어조를 유지하세요.";
      break;
    case "family":
      systemPrompt = "당신은 전문 가족 치료사입니다. 다중 화자 간의 대화 기록을 분석하여 개인의 심리보다는 '관계의 역동(Dynamics)'에 초점을 맞춰 일지를 작성하세요: [면담 요지 및 갈등 상황], [구성원 간 상호작용 및 의사소통 패턴], [갈등 유발 요인], [개입 및 조율 내용], [관계 개선을 위한 과제]. 중립적이고 객관적인 태도를 유지하세요.";
      break;
    case "career":
      systemPrompt = "당신은 전문 코치(Coach)입니다. 제공된 내용을 GROW 모델(Goal, Reality, Options, Will)에 기반하여 분석하고 요약하세요: [내담자의 현재 목표], [현재 상황 및 장애물 진단], [논의된 가능성과 대안 발굴], [구체적인 실행 계획 및 결심]. 내담자가 실행할 수 있도록 행동 지향적인 언어로 요약하세요.";
      break;
    case "general":
    default:
      systemPrompt = "당신은 숙련된 고객 지원 및 상담 담당자입니다. 제공된 대화 기록을 기반으로 다음 항목으로 깔끔하게 요약하세요: [주요 문의 및 요구사항], [제공된 안내 및 해결책], [미해결 된 이슈], [향후 팔로업(Follow-up) 액션 아이템]. 지나치게 감정적인 분석을 배제하고 사실과 조치 내용 위주로 작성하세요.";
      break;
  }

  const requestBody = {
    model: "gpt-4o-mini", // updating to standard valid model
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: transcriptText }
    ],
    temperature: 0.3
  };

  try {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${OPENAI_API_KEY}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(requestBody)
    });

    const body = await parseResponseBody(response);
    if (!response.ok) {
      return "요약 중 오류가 발생했습니다: " + (body.error?.message || "Unknown error");
    }

    return body.choices[0].message.content;
  } catch (error) {
    return "요약 요청 실패: " + error.message;
  }
}

async function uploadToAssemblyAI(filePath, mimeType) {
  const buffer = await fs.readFile(filePath);
  const response = await fetch(ASSEMBLYAI_UPLOAD_URL, {
    method: "POST",
    headers: {
      Authorization: ASSEMBLYAI_API_KEY,
      "Content-Type": mimeType || "application/octet-stream"
    },
    body: buffer
  });

  const payload = await parseResponseBody(response);

  if (!response.ok) {
    const error = new Error(extractAssemblyError(payload));
    error.statusCode = response.status;
    throw error;
  }

  return payload.upload_url;
}

async function pollAssemblyTranscript(transcriptId) {
  while (true) {
    const response = await fetch(`${ASSEMBLYAI_TRANSCRIPT_URL}/${transcriptId}`, {
      headers: {
        Authorization: ASSEMBLYAI_API_KEY
      }
    });

    const payload = await parseResponseBody(response);

    if (!response.ok) {
      const error = new Error(extractAssemblyError(payload));
      error.statusCode = response.status;
      throw error;
    }

    if (payload.status === "completed") {
      return payload;
    }

    if (payload.status === "error") {
      const error = new Error(payload.error || "AssemblyAI diarization failed.");
      error.statusCode = 500;
      throw error;
    }

    await wait(3000);
  }
}

function formatSpeakerSegments(utterances) {
  return utterances.map((utterance) => ({
    speaker: utterance.speaker ?? "unknown",
    text: utterance.text || "",
    startMs: utterance.start ?? null,
    endMs: utterance.end ?? null
  }));
}

function parseExpectedSpeakers(input) {
  if (!input) {
    return null;
  }

  const parsed = Number.parseInt(input, 10);

  if (!Number.isFinite(parsed) || parsed < 1) {
    return null;
  }

  return parsed;
}

async function parseResponseBody(response) {
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

function extractOpenAIError(payload) {
  if (typeof payload === "string") {
    return payload;
  }

  return payload?.error?.message || payload?.message || "OpenAI transcription request failed.";
}

function extractAssemblyError(payload) {
  if (typeof payload === "string") {
    return payload;
  }

  return payload?.error || payload?.message || "AssemblyAI request failed.";
}

function extractErrorMessage(error) {
  if (error instanceof multer.MulterError && error.code === "LIMIT_FILE_SIZE") {
    return "File size must be 25MB or smaller. Split or compress the file and try again.";
  }

  return error.message || "An unknown error occurred.";
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const server = await startServer(PORT);

export { app, server };

async function startServer(preferredPort) {
  for (let attempt = 0; attempt < MAX_PORT_ATTEMPTS; attempt += 1) {
    const port = preferredPort + attempt;

    try {
      const nextServer = await listenOnPort(port);

      if (attempt > 0) {
        console.warn(`Port ${preferredPort} is busy. Listening on http://localhost:${port} instead.`);
      } else {
        console.log(`Transcription app is running on http://localhost:${port}`);
      }

      return nextServer;
    } catch (error) {
      if (error?.code !== "EADDRINUSE" || attempt === MAX_PORT_ATTEMPTS - 1) {
        throw error;
      }
    }
  }
}

function listenOnPort(port) {
  return new Promise((resolve, reject) => {
    const nextServer = app.listen(port);

    nextServer.once("listening", () => resolve(nextServer));
    nextServer.once("error", (error) => {
      nextServer.close(() => reject(error));
    });
  });
}
