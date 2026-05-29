"""
============================================
SMART AI ROUTER API - v3.0 Python Edition
Original JS by @MANDAL4482 → Python by Claude

GET  /api/chat?message=hello&imageUrl=optional
POST /api/chat  → body: { message, imageUrl }

Dono methods support karta hai!
No rate limits. No action caps.
============================================
"""

import json
import asyncio
import httpx
from urllib.parse import urlparse, parse_qs, urlencode, quote
from http.server import BaseHTTPRequestHandler

# ── CONSTANTS ────────────────────────────────────────────────────────────
AI_BASE     = "https://vie-ai-psi.vercel.app"
SEARCH_BASE = "https://pplx-api.vercel.app/api/ask"
LOGO_BASE   = "https://3d-logo-eight.vercel.app"

TIMEOUT_DEFAULT = 30.0
TIMEOUT_IMAGE   = 45.0
TIMEOUT_VIDEO   = 90.0
TIMEOUT_SEARCH  = 20.0

# ── SYSTEM PROMPTS ────────────────────────────────────────────────────────
AI_CAPABILITIES = """
You are "VIE AI" — a powerful multi-modal AI assistant made by @MANDAL4482.

Here is EXACTLY what you can do:

🖼️ IMAGE GENERATION
- "ek sunset ki image banao" → realistic AI images from any description
- "make a logo for my bakery" → professional logos and 3D logos
- "generate 3 images of cats" → multiple images in one request

🎬 VIDEO GENERATION
- "ek video banao mountains ka" → short AI-generated videos from text

✨ IMAGE ENHANCEMENT
- "is photo ko enhance karo" → sharpen, upscale, and beautify any image

🔍 IMAGE UNDERSTANDING
- "is image mein kya hai?" → read and describe any image

🌐 REAL-TIME SEARCH
- "aaj ka weather kya hai?" → live web search for current news, prices, events

💬 SMART CONVERSATION
- Answer in Hindi, English, or Hinglish
- Help with coding, writing, math, advice

⚡ MULTI-TASK
- "ek image aur ek video banao sunset ka" → both done simultaneously

If asked "can you make images?" → YES! Tell them to describe what they want.
If asked "kya tum AI ho?" → Yes, main VIE AI hun, @MANDAL4482 ka banaya hua.
NEVER say "I am just an LLM" or "I cannot generate images" — you CAN do everything above.
"""

ROUTER_SYSTEM = """You are an intelligent multi-action router for VIE AI.
Analyze the user message and respond ONLY in this EXACT JSON format — no markdown, no extra text:

{
  "actions": [
    {
      "action": "<action_type>",
      "prompt": "<extracted clean prompt in English>",
      "reply": "<short friendly reply in same language as user>"
    }
  ]
}

Available action types:
- "chat"           → normal conversation, greetings, general questions, capability questions
- "image_generate" → user wants to create/make/draw/generate an image or picture
- "video_generate" → user wants to create a video or animation
- "logo_3d"        → user wants a 3D logo or icon
- "enhance"        → user sent an image and wants it improved/enhanced/upscaled
- "img2prompt"     → user wants to know what is in an image
- "search"         → user asks about current events, news, live data, today's info, prices

CRITICAL RULES:
1. Multiple tasks → multiple action objects. "3 images banao" = 3 image_generate objects.
2. "prompt" must be clean English version of what user wants (translate if needed).
3. "reply" = ONE short friendly reply for ALL actions combined, in user's language.
4. For "chat": prompt = the user's full message.
5. For "enhance" and "img2prompt": prompt = "" (image URL passed separately).
6. No limit on action objects — handle everything the user asks.
7. If capability question → use "chat" action.
8. ONLY output valid JSON. Nothing else."""

IMAGE_ENHANCER_SYSTEM = """You are an expert AI image prompt engineer.
Expand the user's simple request into a rich, detailed prompt.
Add: lighting (golden hour, studio, cinematic), quality tags (8k, photorealistic, detailed),
composition (rule of thirds, close-up, wide angle), mood, art style if relevant.
Keep under 80 words. Output ONLY the enhanced prompt — no explanation, no quotes."""

SEARCH_SUMMARIZER_SYSTEM = """You are a helpful assistant summarizing search results.
Give a SHORT, clear, direct answer (3-5 lines max) in the SAME language the user asked.
Be conversational and friendly. No bullet points for simple answers."""

CHAT_SYSTEM = f"""{AI_CAPABILITIES}

You are VIE AI — friendly, helpful, smart. Rules:
- Reply in the SAME language the user wrote in (Hindi/English/Hinglish).
- Keep replies SHORT and conversational (2-4 lines for simple questions).
- For capability questions: confidently explain what you can do with examples.
- NEVER say you cannot generate images or videos — you CAN via connected tools.
- For code/explanation: be thorough but clear."""

# ── ERROR MAP ─────────────────────────────────────────────────────────────
ERROR_MAP = {
    "AI_AUTH_FAILED":      "⚠️ AI connection issue. Admin se contact karo.",
    "AI_RATE_LIMIT":       "⏳ AI server busy hai. Thodi der baad try karo.",
    "AI_UNAVAILABLE":      "🔧 AI service thodi der band hai. 1-2 min mein try karo.",
    "AI_SERVER_ERROR":     "❌ AI mein error aaya. Dobara try karo.",
    "IMAGE_NO_PROMPT":     "💬 Image ke liye description do. Example: 'ek sunset ki image banao'",
    "IMAGE_BAD_PROMPT":    "🚫 Yeh content allowed nahi. Koi aur cheez try karo.",
    "IMAGE_EMPTY":         "🔄 Image generate nahi hui. Dobara try karo.",
    "VIDEO_NO_PROMPT":     "💬 Video ke liye description do. Example: 'mountains ki video banao'",
    "VIDEO_EMPTY":         "🔄 Video generate nahi hui. Dobara try karo.",
    "LOGO_NO_PROMPT":      "💬 Logo ke liye naam ya description do.",
    "LOGO_EMPTY":          "🔄 Logo nahi bana. Dobara try karo.",
    "ENHANCE_NO_IMAGE":    "🖼️ Enhance ke liye image URL bhi bhejo.",
    "IMG2PROMPT_NO_IMAGE": "🖼️ Image describe karne ke liye URL bhi do.",
    "SEARCH_NO_QUERY":     "🔍 Kya dhundhna hai? Puri query likho.",
    "SEARCH_NO_RESULTS":   "🔍 Koi result nahi mila. Alag words mein try karo.",
    "SEARCH_UNAVAILABLE":  "🔧 Search engine abhi band hai.",
}

# ── HELPERS ───────────────────────────────────────────────────────────────
def format_user_error(error_msg: str) -> str:
    for code, friendly in ERROR_MAP.items():
        if code in error_msg:
            return friendly
    return f"❌ Kuch gadbad ho gayi: {error_msg.split(':')[0]}. Dobara try karo."


async def call_ai(system: str, user_msg: str, max_tokens: int = 500) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as client:
        res = await client.post(
            f"{AI_BASE}/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user_msg}],
            },
        )

    if not res.is_success:
        status = res.status_code
        err_text = res.text[:200]
        if status == 401:
            raise ValueError("AI_AUTH_FAILED: API key invalid ya expire ho gayi hai.")
        if status == 429:
            raise ValueError("AI_RATE_LIMIT: AI server busy hai.")
        if status == 503:
            raise ValueError("AI_UNAVAILABLE: AI server abhi available nahi hai.")
        if status == 500:
            raise ValueError("AI_SERVER_ERROR: AI server mein internal error aaya.")
        raise ValueError(f"AI_ERROR_{status}: {err_text}")

    data = res.json()
    return (data.get("content") or [{}])[0].get("text", "").strip()


async def enhance_image_prompt(raw_prompt: str) -> str:
    try:
        return await call_ai(IMAGE_ENHANCER_SYSTEM, raw_prompt, 150)
    except Exception:
        return raw_prompt  # fallback


async def search_and_summarize(query: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT_SEARCH) as client:
        res = await client.get(
            SEARCH_BASE,
            params={"prompt": query},
        )

    if not res.is_success:
        status = res.status_code
        if status == 503:
            raise ValueError("SEARCH_UNAVAILABLE: Search engine band hai abhi.")
        raise ValueError(f"SEARCH_ERROR_{status}: Search fail ho gayi.")

    data = res.json()
    if data.get("status") != "success" or not data.get("answer"):
        raise ValueError("SEARCH_NO_RESULTS: Is topic pe koi result nahi mila.")

    summary = await call_ai(
        SEARCH_SUMMARIZER_SYSTEM,
        f'User asked: "{query}"\n\nSearch results: {data["answer"]}',
        300,
    )

    sources = [
        {"name": s.get("name", "Source"), "url": s.get("url")}
        for s in (data.get("sources") or [])[:3]
    ]
    return {"answer": summary, "sources": sources}


# ── ACTION EXECUTOR ───────────────────────────────────────────────────────
async def execute_action(action: str, prompt: str, image_url: str) -> dict:

    if action == "chat":
        reply = await call_ai(CHAT_SYSTEM, prompt or "Hello", 600)
        return {"type": "chat", "reply": reply}

    elif action == "image_generate":
        if not prompt or not prompt.strip():
            raise ValueError("IMAGE_NO_PROMPT: Image ke liye description do.")
        enhanced = await enhance_image_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as client:
            res = await client.get(
                f"{AI_BASE}/generate",
                params={"prompt": enhanced},
            )
        if not res.is_success:
            if res.status_code == 400:
                raise ValueError("IMAGE_BAD_PROMPT: Yeh content allowed nahi.")
            raise ValueError(f"IMAGE_ERROR_{res.status_code}: Image nahi ban payi.")
        data = res.json()
        image_result = data.get("image_url") or data.get("url") or data.get("result")
        if not image_result:
            raise ValueError("IMAGE_EMPTY: Image URL nahi mili.")
        return {"type": "image", "prompt_used": enhanced, "image_url": image_result}

    elif action == "video_generate":
        if not prompt or not prompt.strip():
            raise ValueError("VIDEO_NO_PROMPT: Video ke liye description do.")
        enhanced = await enhance_image_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_VIDEO) as client:
            res = await client.get(
                f"{AI_BASE}/video",
                params={"prompt": enhanced},
            )
        if not res.is_success:
            if res.status_code == 400:
                raise ValueError("VIDEO_BAD_PROMPT: Yeh content allowed nahi.")
            raise ValueError(f"VIDEO_ERROR_{res.status_code}: Video nahi ban payi.")
        data = res.json()
        video_result = data.get("video_url") or data.get("url") or data.get("result")
        if not video_result:
            raise ValueError("VIDEO_EMPTY: Video URL nahi mili.")
        return {"type": "video", "prompt_used": enhanced, "video_url": video_result}

    elif action == "logo_3d":
        if not prompt or not prompt.strip():
            raise ValueError("LOGO_NO_PROMPT: Logo ke liye naam ya description do.")
        enhanced = await enhance_image_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as client:
            res = await client.get(
                f"{LOGO_BASE}/logo",
                params={"prompt": enhanced},
            )
        if not res.is_success:
            raise ValueError(f"LOGO_ERROR_{res.status_code}: Logo nahi bana.")
        data = res.json()
        logo_result = data.get("image_url") or data.get("url") or data.get("logo_url")
        if not logo_result:
            raise ValueError("LOGO_EMPTY: Logo URL nahi mila.")
        return {"type": "logo_3d", "prompt_used": enhanced, "image_url": logo_result}

    elif action == "enhance":
        if not image_url:
            raise ValueError("ENHANCE_NO_IMAGE: Enhance karne ke liye image URL do.")
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as client:
            res = await client.get(
                f"{AI_BASE}/enhance",
                params={"url": image_url},
            )
        if not res.is_success:
            raise ValueError(f"ENHANCE_ERROR_{res.status_code}: Image enhance nahi hui.")
        data = res.json()
        enh_result = data.get("enhanced_url") or data.get("url") or data.get("result")
        if not enh_result:
            raise ValueError("ENHANCE_EMPTY: Enhanced image URL nahi mila.")
        return {"type": "enhanced_image", "original_url": image_url, "image_url": enh_result}

    elif action == "img2prompt":
        if not image_url:
            raise ValueError("IMG2PROMPT_NO_IMAGE: Image describe karne ke liye URL do.")
        async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as client:
            res = await client.get(
                f"{AI_BASE}/img2txt",
                params={"url": image_url},
            )
        if not res.is_success:
            raise ValueError(f"IMG2PROMPT_ERROR_{res.status_code}: Image read nahi ho payi.")
        data = res.json()
        description = data.get("text") or data.get("prompt") or data.get("result") or ""
        if not description:
            raise ValueError("IMG2PROMPT_EMPTY: Description nahi aayi.")
        return {"type": "image_description", "description": description}

    elif action == "search":
        if not prompt or not prompt.strip():
            raise ValueError("SEARCH_NO_QUERY: Kya search karna hai? Query batao.")
        result = await search_and_summarize(prompt)
        return {"type": "search", "reply": result["answer"], "sources": result["sources"]}

    else:
        raise ValueError(
            f'UNKNOWN_ACTION: "{action}" action nahi pehchana. '
            "Valid: chat, image_generate, video_generate, logo_3d, enhance, img2prompt, search"
        )


# ── INPUT PARSER ──────────────────────────────────────────────────────────
def parse_input(method: str, query_params: dict, body: dict) -> tuple[str, str]:
    if method == "GET":
        message = (
            query_params.get("message", [""])[0]
            or query_params.get("msg", [""])[0]
            or query_params.get("q", [""])[0]
        )
        image_url = (
            query_params.get("imageUrl", [""])[0]
            or query_params.get("image", [""])[0]
            or query_params.get("img", [""])[0]
        )
    else:
        message   = body.get("message", "")
        image_url = body.get("imageUrl", "")
    return message, image_url


# ── MAIN HANDLER ─────────────────────────────────────────────────────────
async def main_handler(method: str, query_params: dict, body: dict) -> tuple[int, dict]:
    """
    Core async handler.
    Returns (status_code, response_dict).
    """
    if method not in ("GET", "POST"):
        return 405, {
            "error": "Sirf GET aur POST allowed hai",
            "examples": {
                "GET":  "/api/chat?message=hello",
                "POST": "POST /api/chat  body: { message: 'hello' }",
            },
        }

    message, image_url = parse_input(method, query_params, body)

    if not message or not message.strip():
        return 400, {
            "error": "message parameter zaroori hai",
            "examples": {
                "browser_url": "/api/chat?message=ek+cat+ki+image+banao",
                "post_body":   '{ "message": "ek cat ki image banao" }',
                "with_image":  "/api/chat?message=enhance+karo&imageUrl=https://example.com/photo.jpg",
            },
        }

    try:
        # ── STEP 1: Route Detection ──────────────────────────────────────
        router_input = (
            f'User message: "{message}"\nUser also shared an image: {image_url}'
            if image_url
            else f'User message: "{message}"'
        )

        try:
            router_raw = await call_ai(ROUTER_SYSTEM, router_input, 1000)
            clean = router_raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            routes = parsed.get("actions", [])
            if not isinstance(routes, list) or len(routes) == 0:
                raise ValueError("Empty actions")
        except Exception as router_err:
            print(f"Router failed, falling back to chat: {router_err}")
            routes = [{"action": "chat", "prompt": message, "reply": ""}]

        combined_reply = routes[0].get("reply", "") if routes else ""

        # ── STEP 2: Execute All Actions in Parallel ──────────────────────
        tasks = [
            execute_action(r.get("action", "chat"), r.get("prompt", ""), image_url)
            for r in routes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # ── STEP 3: Build Response ───────────────────────────────────────
        outputs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                raw_error = str(result)
                outputs.append({
                    "type": "error",
                    "action": routes[i].get("action", "unknown"),
                    "error": format_user_error(raw_error),
                    "raw_error": raw_error,
                })
            else:
                outputs.append(result)

        # Single action → flat response
        if len(outputs) == 1:
            return 200, {**outputs[0], "reply": combined_reply}

        # Multiple actions → grouped response
        return 200, {
            "reply":   combined_reply,
            "total":   len(outputs),
            "success": sum(1 for o in outputs if o.get("type") != "error"),
            "failed":  sum(1 for o in outputs if o.get("type") == "error"),
            "results": outputs,
        }

    except Exception as err:
        print(f"Smart AI Router Error: {err}")
        return 500, {
            "error": format_user_error(str(err)),
            "type":  "server_error",
            "hint":  "Agar baar baar ho raha hai to admin ko batao",
            "dev":   "@MANDAL4482",
        }


# ── VERCEL SERVERLESS ENTRY POINT ─────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    """Vercel Python Serverless Function handler."""

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def _handle(self, method: str):
        # Parse URL + query string
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)

        # Read body for POST
        body = {}
        if method == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_body = self.rfile.read(content_length)
                try:
                    body = json.loads(raw_body)
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "Invalid JSON body"})
                    return

        # Run async handler in event loop
        status, response = asyncio.run(main_handler(method, query_params, body))
        self._send_json(status, response)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def log_message(self, fmt, *args):
        pass  # Suppress default logs; Vercel handles logging
