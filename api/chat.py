from flask import Flask, request, jsonify
import json
import asyncio
import httpx
import base64

app = Flask(__name__)

# ── CONSTANTS ─────────────────────────────────────────────────────────────
AI_BASE     = "https://vie-ai-psi.vercel.app"
SEARCH_BASE = "https://pplx-api.vercel.app/api/ask"
LOGO_BASE   = "https://3d-logo-eight.vercel.app"

TIMEOUT_DEFAULT = 30.0
TIMEOUT_IMAGE   = 60.0
TIMEOUT_VIDEO   = 120.0
TIMEOUT_SEARCH  = 20.0

# ── SYSTEM PROMPTS ─────────────────────────────────────────────────────────
ROUTER_SYSTEM = (
    'You are a router. Given a user message, return ONLY valid JSON like this:\n'
    '{"actions":[{"action":"<type>","prompt":"<english prompt>","reply":"<short reply in user language>"}]}\n'
    'Action types: chat, image_generate, video_generate, logo_3d, enhance, img2prompt, search\n'
    'Rules: translate prompt to English, reply in user language, '
    'for enhance/img2prompt set prompt to empty string, '
    'multiple requests = multiple action objects. '
    'Output ONLY the JSON object. No markdown. No explanation.'
)

IMAGE_ENHANCER_SYSTEM = (
    'You are an image prompt engineer. '
    'Expand the idea into a detailed image prompt under 80 words. '
    'Include lighting, style, 8k photorealistic quality tags. '
    'Output ONLY the prompt text, nothing else.'
)

SEARCH_SUMMARIZER_SYSTEM = (
    'Summarize the search results in 3-5 short lines. '
    'Reply in the same language the user asked. Be friendly.'
)

CHAT_SYSTEM = (
    'You are VIE AI made by @MANDAL4482. '
    'Reply in the same language as the user (Hindi/English/Hinglish). '
    'Keep answers short and friendly. '
    'You can generate images, videos, search the web. Never say you cannot.'
)

# ── ERROR MAP ──────────────────────────────────────────────────────────────
ERROR_MAP = {
    "AI_AUTH_FAILED":      "AI connection issue. Admin se contact karo.",
    "AI_RATE_LIMIT":       "AI server busy hai. Thodi der baad try karo.",
    "AI_UNAVAILABLE":      "AI service band hai. 1-2 min mein try karo.",
    "AI_SERVER_ERROR":     "AI mein error aaya. Dobara try karo.",
    "IMAGE_NO_PROMPT":     "Image ke liye description do.",
    "IMAGE_BAD_PROMPT":    "Yeh content allowed nahi.",
    "IMAGE_EMPTY":         "Image generate nahi hui. Dobara try karo.",
    "VIDEO_NO_PROMPT":     "Video ke liye description do.",
    "VIDEO_EMPTY":         "Video generate nahi hui. Dobara try karo.",
    "LOGO_NO_PROMPT":      "Logo ke liye naam ya description do.",
    "LOGO_EMPTY":          "Logo nahi bana. Dobara try karo.",
    "ENHANCE_NO_IMAGE":    "Enhance ke liye imageUrl parameter bhi bhejo.",
    "IMG2PROMPT_NO_IMAGE": "Image describe karne ke liye imageUrl bhi do.",
    "SEARCH_NO_QUERY":     "Kya dhundhna hai? Puri query likho.",
    "SEARCH_NO_RESULTS":   "Koi result nahi mila. Alag words try karo.",
    "SEARCH_UNAVAILABLE":  "Search engine abhi band hai.",
}

def fmt_err(msg):
    for code, friendly in ERROR_MAP.items():
        if code in msg:
            return friendly
    return "Kuch gadbad ho gayi. Dobara try karo."

# ── SAFE RESPONSE PARSER ───────────────────────────────────────────────────
def is_binary_image(res):
    """Check if response is a binary image."""
    ct = res.headers.get("content-type", "").lower()
    if "image/" in ct:
        return True
    # Check magic bytes
    b = res.content
    if len(b) >= 2:
        if b[:2] == b'\xff\xd8':   return True  # JPEG
        if b[:4] == b'\x89PNG':    return True  # PNG
        if b[:6] in (b'GIF87a', b'GIF89a'): return True  # GIF
        if b[:4] == b'RIFF':       return True  # WEBP
    return False

def binary_to_data_url(res):
    """Convert binary image response to base64 data URL."""
    ct = res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    b64 = base64.b64encode(res.content).decode("ascii")
    return f"data:{ct};base64,{b64}"

def parse_url_from_response(res):
    """Extract URL from JSON or plain-text response."""
    # Try JSON
    try:
        data = res.json()
        if isinstance(data, dict):
            return (
                data.get("image_url") or data.get("video_url") or
                data.get("url")       or data.get("result")    or
                data.get("logo_url")  or data.get("imageUrl")  or
                data.get("text")      or data.get("response")  or
                data.get("answer")    or ""
            )
        if isinstance(data, str):
            return data.strip()
    except Exception:
        pass

    # Try plain text
    try:
        text = res.content.decode("utf-8", errors="ignore").strip()
        return text
    except Exception:
        return ""

# ── AI CALL ────────────────────────────────────────────────────────────────
async def call_ai(system, user_msg, max_tokens=500):
    full_prompt = f"{system}\n\nUser: {user_msg}" if system else user_msg
    async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as client:
        res = await client.get(f"{AI_BASE}/ai", params={"prompt": full_prompt})

    if not res.is_success:
        s = res.status_code
        if s == 401: raise ValueError("AI_AUTH_FAILED")
        if s == 429: raise ValueError("AI_RATE_LIMIT")
        if s == 503: raise ValueError("AI_UNAVAILABLE")
        if s == 500: raise ValueError("AI_SERVER_ERROR")
        raise ValueError(f"AI_ERROR_{s}")

    result = parse_url_from_response(res)
    return result

async def enhance_prompt(raw):
    try:
        enhanced = await call_ai(IMAGE_ENHANCER_SYSTEM, raw, 150)
        return enhanced if enhanced else raw
    except Exception:
        return raw

# ── IMAGE GENERATE ─────────────────────────────────────────────────────────
async def action_image_generate(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("IMAGE_NO_PROMPT")

    enhanced = await enhance_prompt(prompt)

    async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
        res = await c.get(f"{AI_BASE}/generate", params={"prompt": enhanced})

    if not res.is_success:
        raise ValueError("IMAGE_BAD_PROMPT" if res.status_code == 400 else f"IMAGE_ERROR_{res.status_code}")

    # Handle binary image response
    if is_binary_image(res):
        data_url = binary_to_data_url(res)
        return {"type": "image", "prompt_used": enhanced, "image_url": data_url}

    # Handle JSON / text URL response
    url = parse_url_from_response(res)
    if not url:
        raise ValueError("IMAGE_EMPTY")
    return {"type": "image", "prompt_used": enhanced, "image_url": url}

# ── VIDEO GENERATE ─────────────────────────────────────────────────────────
async def action_video_generate(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("VIDEO_NO_PROMPT")

    enhanced = await enhance_prompt(prompt)

    async with httpx.AsyncClient(timeout=TIMEOUT_VIDEO) as c:
        res = await c.get(f"{AI_BASE}/video", params={"prompt": enhanced})

    if not res.is_success:
        raise ValueError(f"VIDEO_ERROR_{res.status_code}")

    if is_binary_image(res):
        data_url = binary_to_data_url(res)
        return {"type": "video", "prompt_used": enhanced, "video_url": data_url}

    url = parse_url_from_response(res)
    if not url:
        raise ValueError("VIDEO_EMPTY")
    return {"type": "video", "prompt_used": enhanced, "video_url": url}

# ── LOGO 3D ────────────────────────────────────────────────────────────────
async def action_logo_3d(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("LOGO_NO_PROMPT")

    enhanced = await enhance_prompt(prompt)

    async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
        res = await c.get(f"{LOGO_BASE}/logo", params={"prompt": enhanced})

    if not res.is_success:
        raise ValueError(f"LOGO_ERROR_{res.status_code}")

    if is_binary_image(res):
        data_url = binary_to_data_url(res)
        return {"type": "logo_3d", "prompt_used": enhanced, "image_url": data_url}

    url = parse_url_from_response(res)
    if not url:
        raise ValueError("LOGO_EMPTY")
    return {"type": "logo_3d", "prompt_used": enhanced, "image_url": url}

# ── ENHANCE ────────────────────────────────────────────────────────────────
async def action_enhance(image_url):
    if not image_url:
        raise ValueError("ENHANCE_NO_IMAGE")

    async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
        res = await c.get(f"{AI_BASE}/enhance", params={"url": image_url})

    if not res.is_success:
        raise ValueError(f"ENHANCE_ERROR_{res.status_code}")

    if is_binary_image(res):
        data_url = binary_to_data_url(res)
        return {"type": "enhanced_image", "original_url": image_url, "image_url": data_url}

    url = parse_url_from_response(res)
    if not url:
        raise ValueError("ENHANCE_EMPTY")
    return {"type": "enhanced_image", "original_url": image_url, "image_url": url}

# ── IMG2PROMPT ─────────────────────────────────────────────────────────────
async def action_img2prompt(image_url):
    if not image_url:
        raise ValueError("IMG2PROMPT_NO_IMAGE")

    async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as c:
        res = await c.get(f"{AI_BASE}/img2txt", params={"url": image_url})

    if not res.is_success:
        raise ValueError(f"IMG2PROMPT_ERROR_{res.status_code}")

    result = parse_url_from_response(res)
    if not result:
        raise ValueError("IMG2PROMPT_EMPTY")
    return {"type": "image_description", "description": result}

# ── SEARCH ─────────────────────────────────────────────────────────────────
async def action_search(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("SEARCH_NO_QUERY")

    async with httpx.AsyncClient(timeout=TIMEOUT_SEARCH) as c:
        res = await c.get(SEARCH_BASE, params={"prompt": prompt})

    if not res.is_success:
        raise ValueError("SEARCH_UNAVAILABLE" if res.status_code == 503 else f"SEARCH_ERROR_{res.status_code}")

    try:
        data = res.json()
    except Exception:
        raise ValueError("SEARCH_NO_RESULTS")

    answer = data.get("answer") or data.get("result") or data.get("text") or ""
    if not answer:
        raise ValueError("SEARCH_NO_RESULTS")

    summary = await call_ai(
        SEARCH_SUMMARIZER_SYSTEM,
        f'User asked: "{prompt}"\nSearch results: {answer}',
        300
    )
    sources = [
        {"name": s.get("name", "Source"), "url": s.get("url")}
        for s in (data.get("sources") or [])[:3]
        if s.get("url")
    ]
    return {"type": "search", "reply": summary, "sources": sources}

# ── EXECUTE ACTION ─────────────────────────────────────────────────────────
async def execute_action(action, prompt, image_url):
    if action == "chat":
        reply = await call_ai(CHAT_SYSTEM, prompt or "Hello", 600)
        return {"type": "chat", "reply": reply}
    elif action == "image_generate":
        return await action_image_generate(prompt)
    elif action == "video_generate":
        return await action_video_generate(prompt)
    elif action == "logo_3d":
        return await action_logo_3d(prompt)
    elif action == "enhance":
        return await action_enhance(image_url)
    elif action == "img2prompt":
        return await action_img2prompt(image_url)
    elif action == "search":
        return await action_search(prompt)
    else:
        raise ValueError(f"UNKNOWN_ACTION: {action}")

# ── CORE PROCESS ───────────────────────────────────────────────────────────
async def process(message, image_url):
    if not message or not message.strip():
        return 400, {"error": "message parameter zaroori hai", "example": "/api/chat?message=hello"}

    router_input = (
        f'User message: "{message}"\nUser also sent an image: {image_url}'
        if image_url else
        f'User message: "{message}"'
    )

    try:
        raw = await call_ai(ROUTER_SYSTEM, router_input, 800)
        clean = raw.strip()
        # Strip markdown fences if present
        if "```" in clean:
            parts = clean.split("```")
            for p in parts:
                p = p.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("{"):
                    clean = p
                    break
        # Extract JSON object
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start != -1 and end > start:
            clean = clean[start:end]
        parsed = json.loads(clean)
        routes = parsed.get("actions", [])
        if not isinstance(routes, list) or not routes:
            raise ValueError("empty routes")
    except Exception as e:
        print(f"Router failed ({e}), fallback to chat")
        routes = [{"action": "chat", "prompt": message, "reply": ""}]

    combined_reply = routes[0].get("reply", "") if routes else ""

    tasks = [
        execute_action(r.get("action", "chat"), r.get("prompt", ""), image_url)
        for r in routes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outputs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            err_str = str(result)
            outputs.append({
                "type":      "error",
                "action":    routes[i].get("action", "unknown"),
                "error":     fmt_err(err_str),
                "raw_error": err_str,
            })
        else:
            outputs.append(result)

    if len(outputs) == 1:
        return 200, {**outputs[0], "reply": combined_reply}

    return 200, {
        "reply":   combined_reply,
        "total":   len(outputs),
        "success": sum(1 for o in outputs if o["type"] != "error"),
        "failed":  sum(1 for o in outputs if o["type"] == "error"),
        "results": outputs,
    }

# ── FLASK ROUTES ───────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/chat", methods=["GET", "POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return "", 200

    if request.method == "GET":
        message   = request.args.get("message") or request.args.get("msg") or request.args.get("q") or ""
        image_url = request.args.get("imageUrl") or request.args.get("image") or request.args.get("img") or ""
    else:
        body      = request.get_json(silent=True) or {}
        message   = body.get("message", "")
        image_url = body.get("imageUrl", "")

    try:
        status, resp = asyncio.run(process(message, image_url))
        return jsonify(resp), status
    except Exception as err:
        return jsonify({
            "error": fmt_err(str(err)),
            "type":  "server_error",
            "dev":   "@MANDAL4482",
        }), 500

@app.route("/")
def index():
    return jsonify({
        "name":    "VIE AI Smart Router",
        "version": "3.0 Python",
        "dev":     "@MANDAL4482",
        "status":  "online",
        "usage": {
            "GET":  "/api/chat?message=hello",
            "POST": "/api/chat with body {message, imageUrl}",
        },
    })
