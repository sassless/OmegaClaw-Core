---
name: extensions-hub
description: Agent Extensions Hub on Omega Cloud. Answer questions about the
  Hub and run a Hub extension on the image or audio file the user attached.
---
# Agent Extensions Hub (Omega Cloud)

Use these instructions to answer questions about the Agent Extensions Hub and
to do image or audio work through a Hub extension. Once the question is
answered or the result is delivered, call `(workflow-unload-instructions)`.

## What the Hub is

The Agent Extensions Hub is the catalogue of agents published on Omega Cloud.
They are called extensions because each one does something you cannot do on
your own, such as upscaling an image, removing its background, reading text
off a scan, transcribing a recording or speaking a text aloud.

When the user asks about the Hub, answer from these facts:
- It opens from Agent Extensions Hub in the sidebar or at
  https://omega-cloud.io/#/extensions-hub. The user has to be signed in.
- Only published agents appear there. Every agent the user builds stays in
  their default space, and the platform does not publish agents from it, so
  their own agents never reach the Hub.
- The Search Agents field and the Filter button, with tags grouped into
  categories, narrow the list. Results come 24 to a page.
- A card shows the agent's avatar, name and description. The agent's page adds
  its tags and readme and has no control that runs it.
- The only way to run an extension is to ask you. You find it, open a chat with
  it and send the request, with the file when the extension takes one. A call
  gets about 30 seconds.

## Files the user attaches

The chat takes up to 3 files per message in these formats: TXT, MD, MARKDOWN,
JSON, CSV, PDF, PNG, JPG, JPEG, PJP, PJPEG, PJPG, JFIF, WAV.

An attached file reaches you inside the message, for example:

    User attached photo.png (image/png, 48213 bytes; id=5d0c1f7e-...).
    Attachment downloaded successfully.
    Original file: /tmp/omegaclaw/uploads/12/5d0c1f7e-...-photo.png
    Native image processing is unavailable for image/png.
    Use an Extension Hub image tool with the original file path.

- The file is on disk at the `Original file:` path. That path is what you pass
  to an extension.
- For a WAV file the message says `Attachment processing error: unsupported
  attachment content type: audio/wav`. Ignore it: only the text extractor
  cannot read audio, and the file is on disk as usual.
- For TXT, MD, JSON, CSV and PDF the message may also give `Extracted text:`,
  a file with the text. A PDF comes as the words on its pages, without the
  layout.
- Never tell the user that images or audio are unsupported, that the upload
  failed, or that you cannot process attachments. Do not ask them to upload
  the file again or to convert it.
- The `id=` in `User attached` belongs to the user's own file and cannot be
  sent back. To return that file to the user, upload it with `upload_file` and
  send the new id.

## When to use an extension

| The user asks for | Extension |
|---|---|
| upscale, enhance, sharpen, make bigger, low resolution, pixelated or blurry, with an image | SNET Enhanced Upscaling x2 (default) |
| upscale x4, 4x enhance, maximum quality upscale, enhance 4 times, with an image | SNET Enhanced Upscaling x4 |
| strong upscale, heavy enhance, super resolution, drastically improve quality, with an image | SNET Image Upscaler |
| generate an image, create a picture, draw, make an image of | SNET Image Generator |
| OCR, extract text, read this document, what does this say, with an image or PDF | SNET Document OCR |
| remove background, cut out, transparent background, isolate, with an image | SNET Background Remover |
| segment, semantic segmentation, mask, regions, with an image | SNET Image Segmenter |
| extract foreground, subject only, main object, with an image | SNET Foreground Extractor |
| transcribe, what are they saying, write down this audio, with audio | SNET Speech-to-Text |
| what language is this, detect language, with audio | SNET Language Identifier |
| enhance audio, clean audio, remove noise, fix sound, with audio | SNET Audio Enhancer |
| read aloud, say this, voice message, text to speech, with text | SNET Text-to-Speech |
| clone voice, speak with this voice, imitate voice, with audio and text | SNET Voice Cloning |

If the task is in this table, run the pipeline below. Never install local
tools such as pip packages, Pillow, ImageMagick or ffmpeg to do an extension's
job.

## Pipeline

Do the steps in order and do not ask the user for permission between them. The
MCP tool list in your context shows the arguments of each tool.

1. Find the extension. Call `call-mcp get_published_agents {}` without a
   search term. The reply is a page with `total_items`, `total_pages`, `page`
   and `items`. While `page` is less than `total_pages`, request the next page:
   `call-mcp get_published_agents {"page":2}`, then 3, and so on. Take the `id`
   of the item whose name matches the Hub Agent Name below as `agent_uuid`.
   Do not tell the user an extension is missing until you have read every page,
   and do not suggest that they check whether it exists or try another name.
2. Open a chat. Call `call-mcp get_agent_chats {"agent_uuid":"<agent_uuid>"}`
   and reuse the `uuid` of an existing chat as `chat_uuid`. If there is none,
   call `call-mcp create_agent_chat {"agent_uuid":"<agent_uuid>","chat_name":"<short name>"}`.
3. Run it. Call `call-mcp run_lf_agent` with `chat_uuid`, `text` set to the
   Body from the reference below, `filename`, and `b64_string_file` set to
   `@file:` followed by the Original file path, for example:
   `call-mcp run_lf_agent {"chat_uuid":"<chat_uuid>","text":"{\"input\": {\"return_mask\": true}}","filename":"photo.png","b64_string_file":"@file:/tmp/omegaclaw/uploads/12/5d0c1f7e-...-photo.png"}`
   The file is read and encoded for you. Never put base64 or file content into
   the JSON yourself and never run base64 in the shell. For the text-only
   extensions, Image Generator and Text-to-Speech, leave out `filename` and
   `b64_string_file`.
4. Reply. If the result has files with an `attachment_id`, send each file with
   `send-attachment <attachment_id> <short message>`, one file per message, and
   do not call `upload_file` for them. Tell the user which extension you used
   and what it did. Do not show tool calls, UUIDs or internal commands.

If your tool list has `send_agent_message` instead of `get_agent_chats`,
`create_agent_chat` and `run_lf_agent`, steps 2 and 3 become one call:
`call-mcp send_agent_message {"agent_uuid":"<agent_uuid>","text":"<Body>","filename":"photo.png","b64_string_file":"@file:<Original file path>"}`.
It returns PENDING with an `operation_id`. Call
`call-mcp get_agent_message_result {"operation_id":"<operation_id>"}` until it
reports COMPLETED, then reply as in step 4.

## Cold start

An idle extension shuts down, and the first call starts it, which takes about
five minutes. The call is cut off after 30 seconds, so the first attempt
usually fails with `Network Error: Unable to connect to the internal service`.
The extension is starting, it is not broken.

1. Tell the user once: "The extension is starting, this takes a few minutes."
2. Repeat the same call with the same arguments once at least 60 seconds have
   passed since the failure. Check the time in TIME and keep the attempt number
   with pin. `shell sleep` cannot wait that long, because shell commands are
   stopped after 5 seconds.
3. Make 3 to 4 attempts over about five minutes without asking the user. Only
   then say that the extension did not come up.

## Limits

- An image or audio file can be 1 MB at most. Ask for a smaller file if it is
  larger.
- Images: png, jpg, jpeg, pjp, pjpeg, pjpg, jfif. Audio: wav.
- One file per call.
- Do not promise the output format in advance. Describe the file that comes
  back.

## Extension reference

| Hub Agent Name | Input | Body |
|---|---|---|
| SNET Enhanced Upscaling x2 | image | `""` |
| SNET Enhanced Upscaling x4 | image | `""` |
| SNET Image Upscaler | image | `""` |
| SNET Image Generator | text | `{"input": {"prompt": "...", "steps": 4, "width": 640, "height": 640, "seed": 1234}}` |
| SNET Document OCR | image or PDF | `{"input": {"prompt": "Please OCR this image. Return clean plain text; use line breaks and spaces correctly."}}` |
| SNET Background Remover | image | `{"input": {"return_mask": true}}` |
| SNET Image Segmenter | image | `{"input": {}}` |
| SNET Foreground Extractor | image | `{"input": {"return_mask": true}}` |
| SNET Speech-to-Text | audio | `{"input": {"source_lang": "en", "target_lang": "en"}}` |
| SNET Language Identifier | audio | `{"input": {}}` |
| SNET Audio Enhancer | audio | `{"input": {}}` |
| SNET Text-to-Speech | text | `{"input": {"text": "...", "lang": "EN", "speed": 1.0}}` |
| SNET Voice Cloning | audio and text | `{"input": {"text": "...", "text_language": "EN", "speech_speed": 1.0}}` |

- The upscalers ignore the body, so send an empty string. Use x2 when the user
  gives no scale or strength, x4 only when they ask for four times, and Image
  Upscaler when they stress strength over speed.
- Image Generator: `prompt` is required. `steps` defaults to 4, `width` and
  `height` to 640, and `seed` is optional and makes the result reproducible.
- Document OCR: `prompt` is optional, and the text above is the default.
- Background Remover and Foreground Extractor: with `return_mask` set to true
  the alpha mask comes back as well.
- Image Segmenter returns a segmentation mask or a colour overlay.
- Speech-to-Text: `source_lang` and `target_lang` are required lowercase codes.
  The same code gives a transcript and different codes give a translation. Ask
  the user for the source language if you cannot tell, because a wrong code
  gives a wrong transcript.
- Language Identifier returns the detected language with its probability.
- Text-to-Speech: `text` is the exact words to speak, never your summary or
  translation of them. `lang` is uppercase: EN, EN_US, EN_AU, FR, ES, JP, ZH,
  KR. Leave `speed` at 1.0.
- Voice Cloning: the attached audio is the voice to copy. `text` is what to
  say and `text_language` is uppercase: EN, EN_NEWEST, ES, FR, ZH, JP, KR.
  `speech_speed` defaults to 1.0.
- Never put the file into the body, whether as `image_b64`, `base64_image`,
  `audio` or `base64_audio`. The platform adds the file itself.
