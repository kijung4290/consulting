import path from "path";
import { fileURLToPath } from "url";

import dotenv from "dotenv";
import express from "express";
import fs from "fs-extra";
import multer from "multer";

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
    openaiModel: OPENAI_TRANSCRIBE_MODEL,
    maxUploadMb: MAX_UPLOAD_BYTES / (1024 * 1024)
  });
});

app.post("/api/transcribe", upload.single("mediaFile"), async (req, res) => {
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

    const summary = await summarizeTranscript(payload.transcriptText);

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
      await fs.remove(uploadedFilePath).catch(() => {});
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

async function summarizeTranscript(transcriptText) {
  if (!OPENAI_API_KEY) {
    return "OpenAI API 키가 설정되지 않아 요약을 생성할 수 없습니다.";
  }

  const requestBody = {
    model: "gpt-4o-mini", // user wrote gpt-5.4-mini, gracefully handling as gpt-4o-mini (the cheapest valid one)
    messages: [
      { role: "system", content: "당신은 전문 상담가입니다. 제공된 음성 기록 텍스트를 분석하여, [상담 일자/시간], [내담자 주요 호소 문제], [상담 주요 내용], [상담자 의견 및 향후 계획] 등 체계적인 상담 일지 형태로 요약해 주세요. 전문적이고 간결한 어조를 사용하세요." },
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
