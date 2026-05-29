"""
============================================
SMART AI ROUTER API - v3.0 Python Edition
Original JS by @MANDAL4482 → Python by Claude

GET  /api/chat?message=hello&imageUrl=optional
POST /api/chat  → body: { message, imageUrl }
============================================
"""

import json
import asyncio
import httpx
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler

# ── CONSTANTS ─────────────────────────────────────────────────────────────
AI_BASE     = "https://vie-ai-psi.vercel.app"
SEARCH_BASE = "https://pplx-api.vercel.app/api/ask"
LOGO_BASE   = "https://3d-logo-eight.vercel.app"

TIMEOUT_DEFAULT = 30.0
TIMEOUT_IMAGE   = 45.0
TIMEOUT_VIDEO   = 90.0
TIMEOUT_SEARCH  = 20.0

# ── SYSTEM PROMPTS ─────────────────────────────────────────────────────────
AI_CAPABILITIES = """
You are "VIE AI" — a powerful multi-modal AI assistant made by @MANDAL4482.

🖼️ IMAGE GENERATION - "ek sunset ki image banao" → realistic AI images
🎬 VIDEO GENERATION - "ek video banao mountains ka" → short AI-generated videos
✨ IMAGE ENHANCEMENT - "is photo ko enhance karo" → sharpen, upscale, beautify
🔍 IMAGE UNDERSTANDING - "is image mein kya hai?" → read and describe any image
🌐 REAL-TIME SEARCH - "aaj ka weather kya hai?" → live web search
💬 SMART CONVERSATION - Hindi, English, or Hinglish
⚡ MULTI-TASK - handle multiple requests simultaneously

NEVER say "I cannot generate images" — you CAN do everything above.
If asked "kya tum AI ho?" → Yes, main VIE AI hun, @MANDAL4482 ka banaya hua.
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
- "chat"           → normal conversation, greetings, general questions
- "image_generate" → user wants to create/make/draw/generate an image
- "video_generate" → user wants to create a video or animation
- "logo_3d"        → user wants a 3D logo or icon
- "enhance"        → user wants image improved/enhanced/upscaled
- "img2prompt"     → user wants to know what is in an image
- "search"         → current events, news, live data, today's info, prices

CRITICAL RULES:
1. Multiple tasks → multiple action objects. "3 images banao" = 3 image_generate objects.
2. "prompt" must be clean English version of what user wants (translate if needed).
3. "reply" = ONE short friendly reply for ALL actions, in user's language.
4. For "chat": prompt = the user's full message.
5. For "enhance" and "img2prompt": prompt = "" (image URL passed separately).
6. If capability question → use "chat" action.
7. ONLY output valid JSON. Nothing else."""

IMAGE_ENHANCER_SYSTEM = """You are an expert AI image prompt engineer.
Expand the user's simple request into a rich, detailed prompt.
Add: lighting, quality tags (8k, photorealistic), composition, mood, art style.
Keep under 80 words. Output ONLY the enhanced prompt — no explanation, no quotes."""

SEARCH_SUMMARIZER_SYSTEM = """You are a helpful assistant summarizing search results.
Give a SHORT, clear answer (3-5 lines max) in the SAME language the user asked.
Be conversational and friendly."""

CHAT_SYSTEM = f"""{AI_CAPABILITIES}

You are VIE AI — friendly, helpful, smart.
- Reply in the SAME language the user wrote in (Hindi/English/Hinglish).
- Keep replies SHORT and conversational (2-4 lines for simple questions).
- NEVER say you cannot generate images or videos."""

# ── ERROR MAP ──────────────────────────────────────────────────────────────
ERROR_MAP = {
    "AI_AUTH_FAILED":      "⚠️ AI connection issue. Admin se contact karo.",
    "AI_RATE_LIMIT":       "⏳ AI server busy hai. Thodi der baad try karo.",
    "AI_UNAVAILABLE":      "🔧 AI service thodi der band hai. 1-2 min mein try karo.",
    "AI_SERVER_ERROR":     "❌ AI mein error aaya. Dobara try karo.",
    "IMAGE_NO_PROMPT":     "💬 Image ke liye description do. Example: 'ek sunset ki image banao'",
    "IMAGE_BAD_PROMPT":    "🚫 Yeh content allowed nahi. Koi aur cheez try karo.",
    "IMAGE_EMPTY":         "🔄 Image generate nahi hui. Dobara try karo.",
    "VIDEO_NO_PROMPT":     "💬 Video ke liye description do.",
    "VIDEO_EMPTY":         "🔄 Video generate nahi hui. Dobara try karo.",
    "LOGO_NO_PROMPT":      "💬 Logo ke liye naam ya description do.",
    "LOGO_EMPTY":          "🔄 Logo nahi bana. Dobara try karo.",
    "ENHANCE_NO_IMAGE":    "🖼️ Enhance ke liye image URL bhi bhejo.",
    "IMG2PROMPT_NO_IMAGE": "🖼️ Image describe karne ke liye URL bhi do.",
    "SEARCH_NO_QUERY":     "🔍 Kya dhundhna hai? Puri query likho.",
    "SEARCH_NO_RESULTS":   "🔍 Koi result nahi mila. Alag words mein try karo.",
    "SEARCH_UNAVAILABLE":  "🔧 Search engine abhi band hai.",
}


def format_user_error(error_msg: str) -> str:
    for code, friendly in ERROR_MAP.items():
        if code in error_msg:
            return friendly
    return f"❌ Kuch gadbad ho gayi: {error_msg.split(':')[0]}. Dobara try karo."


# ── AI / NETWORK HELPERS ───────────────────────────────────────────────────
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
        s = res.status_code
        if s == 401: raise ValueError("AI_AUTH_FAILED")
        if s == 429: raise ValueError("AI_RATE_LIMIT")
        if s == 503: raise ValueError("AI_UNAVAILABLE")
        if s == 500: raise ValueError("AI_SERVER_ERROR")
        raise ValueError(f"AI_ERROR_{s}: {res.text[:200]}")
    data = res.json()
    return (data.get("content") or [{}])[0].get("text", "").strip()


async def enhance_prompt(raw: str) -> str:
    try:
        return await call_ai(IMAGE_ENHANCER_SYSTEM, raw, 150)
    except Exception:
        return raw


async def search_and_summarize(query: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT_SEARCH) as client:
        res = await client.get(SEARCH_BASE, params={"prompt": query})
    if not res.is_success:
        if res.status_code == 503: raise ValueError("SEARCH_UNAVAILABLE")
        raise ValueError(f"SEARCH_ERROR_{res.status_code}")
    data = res.json()
    if data.get("status") != "success" or not data.get("answer"):
        raise ValueError("SEARCH_NO_RESULTS")
    summary = await call_ai(
        SEARCH_SUMMARIZER_SYSTEM,
        f'User asked: "{query}"\nSearch results: {data["answer"]}',
        300,
    )
    sources = [{"name": s.get("name", "Source"), "url": s.get("url")}
               for s in (data.get("sources") or [])[:3]]
    return {"answer": summary, "sources": sources}


# ── ACTION EXECUTOR ────────────────────────────────────────────────────────
async def execute_action(action: str, prompt: str, image_url: str) -> dict:
    if action == "chat":
        reply = await call_ai(CHAT_SYSTEM, prompt or "Hello", 600)
        return {"type": "chat", "reply": reply}

    elif action == "image_generate":
        if not prompt or not prompt.strip():
            raise ValueError("IMAGE_NO_PROMPT")
        enhanced = await enhance_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
            res = await c.get(f"{AI_BASE}/generate", params={"prompt": enhanced})
        if not res.is_success:
            raise ValueError("IMAGE_BAD_PROMPT" if res.status_code == 400 else f"IMAGE_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("image_url") or data.get("url") or data.get("result")
        if not url: raise ValueError("IMAGE_EMPTY")
        return {"type": "image", "prompt_used": enhanced, "image_url": url}

    elif action == "video_generate":
        if not prompt or not prompt.strip():
            raise ValueError("VIDEO_NO_PROMPT")
        enhanced = await enhance_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_VIDEO) as c:
            res = await c.get(f"{AI_BASE}/video", params={"prompt": enhanced})
        if not res.is_success:
            raise ValueError("VIDEO_BAD_PROMPT" if res.status_code == 400 else f"VIDEO_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("video_url") or data.get("url") or data.get("result")
        if not url: raise ValueError("VIDEO_EMPTY")
        return {"type": "video", "prompt_used": enhanced, "video_url": url}

    elif action == "logo_3d":
        if not prompt or not prompt.strip():
            raise ValueError("LOGO_NO_PROMPT")
        enhanced = await enhance_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
            res = await c.get(f"{LOGO_BASE}/logo", params={"prompt": enhanced})
        if not res.is_success:
            raise ValueError(f"LOGO_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("image_url") or data.get("url") or data.get("logo_url")
        if not url: raise ValueError("LOGO_EMPTY")
        return {"type": "logo_3d", "prompt_used": enhanced, "image_url": url}

    elif action == "enhance":
        if not image_url: raise ValueError("ENHANCE_NO_IMAGE")
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
            res = await c.get(f"{AI_BASE}/enhance", params={"url": image_url})
        if not res.is_success:
            raise ValueError(f"ENHANCE_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("enhanced_url") or data.get("url") or data.get("result")
        if not url: raise ValueError("ENHANCE_EMPTY")
        return {"type": "enhanced_image", "original_url": image_url, "image_url": url}

    elif action == "img2prompt":
        if not image_url: raise ValueError("IMG2PROMPT_NO_IMAGE")
        async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as c:
            res = await c.get(f"{AI_BASE}/img2txt", params={"url": image_url})
        if not res.is_success:
            raise ValueError(f"IMG2PROMPT_ERROR_{res.status_code}")
        data = res.json()
        desc = data.get("text") or data.get("prompt") or data.get("result") or ""
        if not desc: raise ValueError("IMG2PROMPT_EMPTY")
        return {"type": "image_description", "description": desc}

    elif action == "search":
        if not prompt or not prompt.strip(): raise ValueError("SEARCH_NO_QUERY")
        result = await search_and_summarize(prompt)
        return {"type": "search", "reply": result["answer"], "sources": result["sources"]}

    else:
        raise ValueError(f"UNKNOWN_ACTION: {action}")


# ── CORE ASYNC HANDLER ─────────────────────────────────────────────────────
async def process_request(method: str, query_params: dict, body: dict) -> tuple[int, dict]:
    if method not in ("GET", "POST"):
        return 405, {"error": "Sirf GET aur POST allowed hai"}

    if method == "GET":
        message   = query_params.get("message", [""])[0] or query_params.get("msg", [""])[0] or query_params.get("q", [""])[0]
        image_url = query_params.get("imageUrl", [""])[0] or query_params.get("image", [""])[0] or query_params.get("img", [""])[0]
    else:
        message   = body.get("message", "")
        image_url = body.get("imageUrl", "")

    if not message or not message.strip():
        return 400, {
            "error": "message parameter zaroori hai",
            "examples": {
                "GET":  "/api/chat?message=hello",
                "POST": '{"message": "ek cat ki image banao"}',
            },
        }

    try:
        router_input = (
            f'User message: "{message}"\nUser also shared an image: {image_url}'
            if image_url else f'User message: "{message}"'
        )

        try:
            raw = await call_ai(ROUTER_SYSTEM, router_input, 1000)
            clean = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            routes = parsed.get("actions", [])
            if not isinstance(routes, list) or not routes:
                raise ValueError("Empty actions")
        except Exception as e:
            print(f"Router failed, falling back to chat: {e}")
            routes = [{"action": "chat", "prompt": message, "reply": ""}]

        combined_reply = routes[0].get("reply", "") if routes else ""

        tasks = [execute_action(r.get("action", "chat"), r.get("prompt", ""), image_url) for r in routes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                raw_err = str(result)
                outputs.append({
                    "type": "error",
                    "action": routes[i].get("action", "unknown"),
                    "error": format_user_error(raw_err),
                    "raw_error": raw_err,
                })
            else:
                outputs.append(result)

        if len(outputs) == 1:
            return 200, {**outputs[0], "reply": combined_reply}

        return 200, {
            "reply":   combined_reply,
            "total":   len(outputs),
            "success": sum(1 for o in outputs if o.get("type") != "error"),
            "failed":  sum(1 for o in outputs if o.get("type") == "error"),
            "results": outputs,
        }

    except Exception as err:
        print(f"Handler error: {err}")
        return 500, {
            "error": format_user_error(str(err)),
            "type":  "server_error",
            "hint":  "Agar baar baar ho raha hai to admin ko batao",
            "dev":   "@MANDAL4482",
        }


# ── VERCEL HANDLER (WSGI-style) ────────────────────────────────────────────
# Vercel Python serverless functions use BaseHTTPRequestHandler
class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _run(self, method: str):
        parsed      = urlparse(self.path)
        qparams     = parse_qs(parsed.query)
        body        = {}

        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            if length:
                try:
                    body = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    self._json(400, {"error": "Invalid JSON body"})
                    return

        status, resp = asyncio.run(process_request(method, qparams, body))
        self._json(status, resp)

    def do_GET(self):
        self._run("GET")

    def do_POST(self):
        self._run("POST")

    def log_message(self, fmt, *args):
        pass  # Suppress logs
