# Hybrid Transcription App

This app routes requests by feature:

- Plain transcription -> OpenAI `gpt-4o-mini-transcribe`
- Speaker diarization -> AssemblyAI with `speaker_labels=true`

## Features

- Single upload flow for audio or video files
- Plain transcript mode for lower-cost text transcription
- Speaker diarization mode for speaker-separated segments
- Optional OpenAI prompt hint for plain transcripts
- Optional expected speaker count for AssemblyAI diarization
- Copy transcript in the browser
- Download transcript as `.txt`

## Supported formats

- `mp3`
- `mp4`
- `mpeg`
- `mpga`
- `m4a`
- `wav`
- `webm`

## Environment variables

```env
OPENAI_API_KEY=your_openai_api_key_here
ASSEMBLYAI_API_KEY=your_assemblyai_api_key_here
PORT=3000
```

## Run locally

1. Install dependencies

```bash
npm install
```

2. Create `.env` from `.env.example`

3. Start the dev server

```bash
npm run dev
```

4. Open the app at `http://localhost:3000`

## Routing behavior

- `Plain transcription` calls OpenAI `v1/audio/transcriptions`
- `Speaker diarization` uploads to AssemblyAI, requests `speaker_labels`, and polls until completion

## Notes

- The app keeps a `25MB` upload limit so the OpenAI plain-transcription path stays within the current OpenAI upload constraint.
- For larger files, split or compress the media first.
- Plain mode in this app does not do speaker separation.
