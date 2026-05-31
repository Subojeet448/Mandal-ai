from flask import Flask, request, jsonify
import json
import asyncio
import httpx
import base64
import re

app = Flask(__name__)

# ── CONSTANTS ─────────────────────────────────────────────────────────────
AI_BASE     = "https://vie-ai-psi.vercel.app"
SEARCH_BASE = "https://pplx-api.vercel.app/api/ask"
LOGO_BASE   = "https://3d-logo-eight.vercel.app"

TIMEOUT_DEFAULT = 30.0
TIMEOUT_IMAGE   = 40.0
TIMEOUT_VIDEO   = 50.0
TIMEOUT_SEARCH  = 20.0

# ── SYSTEM PROMPTS ─────────────────────────────────────────────────────────
ROUTER_SYSTEM = """You are an action router. Analyze the user message and return ONLY a JSON object.

IMPORTANT RULES:
- If user wants ONLY to chat/talk/ask something = action "chat"
- If user wants image = action "image_generate"
- If user wants video = action "video_generate"
- If user wants 3D logo = action "logo_3d"
- If user sends imageUrl and wants enhancement = action "enhance"
- If user sends imageUrl and asks what is in it = action "img2prompt"
- If user asks about news/weather/current events/prices = action "search"
- If user wants BOTH image AND video = TWO separate action objects
- NEVER mix chat with other actions unless user is only chatting

Output format (ONLY this JSON, nothing else):
{"actions":[{"action":"<type>","prompt":"<english prompt>","reply":"<friendly reply in user language>"}]}

For enhance and img2prompt: prompt must be empty string ""
For chat: prompt = full user message
Translate all prompts to English."""

IMAGE_ENHANCER_SYSTEM = (
    "Expand this into a detailed image generation prompt under 80 words. "
    "Add lighting, style, 8k photorealistic quality. "
    "Output ONLY the prompt, nothing else."
)

SEARCH_SUMMARIZER_SYSTEM = (
    "Summarize these search results in 3-5 short friendly lines. "
    "Reply in the same language the user used."
)

CHAT_SYSTEM = (
    "You are VIE AI made by @MANDAL4482. "
    "Reply in the same language as the user (Hindi/English/Hinglish). "
    "Be short, friendly, helpful. "
    "You can generate images, videos, logos, search the web. "
    "Never say you cannot do something."
)

# ── ERROR MAP ──────────────────────────────────────────────────────────────
ERROR_MAP = {
    "AI_AUTH_FAILED":      "AI connection issue. Admin se contact karo.",
    "AI_RATE_LIMIT":       "AI server busy hai. Thodi der baad try karo.",
    "AI_UNAVAILABLE":      "AI service band hai. 1-2 min mein try karo.",
    "AI_SERVER_ERROR":     "AI mein error aaya. Dobara try karo.",
    "IMAGE_NO_PROMPT":     "Image ke liye description do. Example: 'cat ki image banao'",
    "IMAGE_FAILED":        "Image generate nahi hui. Dobara try karo.",
    "VIDEO_NO_PROMPT":     "Video ke liye description do.",
    "VIDEO_FAILED":        "Video generate nahi hui. Dobara try karo.",
    "LOGO_NO_PROMPT":      "Logo ke liye naam ya description do.",
    "LOGO_FAILED":         "Logo nahi bana. Dobara try karo.",
    "ENHANCE_NO_IMAGE":    "Enhance ke liye imageUrl parameter bhi bhejo.",
    "IMG2PROMPT_NO_IMAGE": "Image describe karne ke liye imageUrl bhi do.",
    "SEARCH_NO_QUERY":     "Kya dhundhna hai? Puri query likho.",
    "SEARCH_FAILED":       "Search nahi ho payi. Dobara try karo.",
}

def fmt_err(msg):
    for code, friendly in ERROR_MAP.items():
        if code in msg:
            return friendly
    return "Kuch gadbad ho gayi. Dobara try karo."

# ── HELPERS ────────────────────────────────────────────────────────────────
def is_binary_image(res):
    ct = res.headers.get("content-type", "").lower()
    if "image/" in ct:
        return True
    b = res.content
    if len(b) < 4:
        return False
    return (
        b[:2] == b'\xff\xd8' or      # JPEG
        b[:4] == b'\x89PNG' or       # PNG
        b[:6] in (b'GIF87a', b'GIF89a') or  # GIF
        b[:4] == b'RIFF'             # WEBP
    )

def binary_to_hosted_url(res, prompt_slug="image"):
    """
    vie-ai-psi /generate returns raw binary image.
    We convert to base64 data URL so client can display it directly.
    """
    ct = res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    b64 = base64.b64encode(res.content).decode("ascii")
    return f"data:{ct};base64,{b64}"

def extract_text(res):
    """Safely decode response text ignoring bad bytes."""
    try:
        return res.text.strip()
    except Exception:
        return res.content.decode("utf-8", errors="ignore").strip()

def parse_response(res):
    """
    Parse API response → return dict with useful fields.
    Handles: JSON dict, plain text URL, binary image.
    """
    if is_binary_image(res):
        return {"__binary__": True, "data_url": binary_to_hosted_url(res)}

    # Try JSON
    try:
        data = res.json()
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            return {"result": data.strip()}
    except Exception:
        pass

    # Plain text
    text = extract_text(res)
    return {"result": text} if text else {}

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
        raise ValueError(f"AI_SERVER_ERROR_{s}")

    data = parse_response(res)
    # AI text response — pick best field
    text = (
        data.get("response") or data.get("text") or
        data.get("answer")   or data.get("result") or ""
    )
    return str(text).strip()

async def enhance_prompt(raw):
    try:
        result = await call_ai(IMAGE_ENHANCER_SYSTEM, raw, 150)
        return result if result else raw
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
        raise ValueError(f"IMAGE_FAILED_{res.status_code}")

    data = parse_response(res)

    # Binary image → convert to base64 data URL
    if data.get("__binary__"):
        return {
            "type":        "image",
            "prompt_used": enhanced,
            "image_url":   data["data_url"],
            "format":      "base64"
        }

    # JSON with URL
    url = (
        data.get("image_url") or data.get("url") or
        data.get("result")    or data.get("imageUrl") or ""
    )
    if not url:
        raise ValueError("IMAGE_FAILED: no url in response")

    return {"type": "image", "prompt_used": enhanced, "image_url": url}

# ── VIDEO GENERATE ─────────────────────────────────────────────────────────
async def action_video_generate(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("VIDEO_NO_PROMPT")

    enhanced = await enhance_prompt(prompt)

    async with httpx.AsyncClient(timeout=TIMEOUT_VIDEO) as c:
        res = await c.get(f"{AI_BASE}/video", params={"prompt": enhanced})

    if not res.is_success:
        raise ValueError(f"VIDEO_FAILED_{res.status_code}")

    data = parse_response(res)

    # Binary video
    if data.get("__binary__"):
        ct = "video/mp4"
        b64 = base64.b64encode(res.content).decode("ascii")
        return {
            "type":        "video",
            "prompt_used": enhanced,
            "video_url":   f"data:{ct};base64,{b64}",
            "format":      "base64"
        }

    # JSON — vie-ai returns {"url": "https://...", "filename": "...", "status": "success"}
    url = (
        data.get("url")       or data.get("video_url") or
        data.get("result")    or data.get("videoUrl")  or ""
    )
    if not url:
        raise ValueError("VIDEO_FAILED: no url in response")

    return {
        "type":        "video",
        "prompt_used": enhanced,
        "video_url":   url,
        "filename":    data.get("filename", "")
    }

# ── LOGO 3D ────────────────────────────────────────────────────────────────
async def action_logo_3d(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("LOGO_NO_PROMPT")

    enhanced = await enhance_prompt(prompt)

    async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
        res = await c.get(f"{LOGO_BASE}/logo", params={"prompt": enhanced})

    if not res.is_success:
        raise ValueError(f"LOGO_FAILED_{res.status_code}")

    data = parse_response(res)

    if data.get("__binary__"):
        return {"type": "logo_3d", "prompt_used": enhanced, "image_url": data["data_url"], "format": "base64"}

    url = (
        data.get("image_url") or data.get("url") or
        data.get("logo_url")  or data.get("result") or ""
    )
    if not url:
        raise ValueError("LOGO_FAILED: no url in response")

    return {"type": "logo_3d", "prompt_used": enhanced, "image_url": url}

# ── ENHANCE ────────────────────────────────────────────────────────────────
async def action_enhance(image_url):
    if not image_url:
        raise ValueError("ENHANCE_NO_IMAGE")

    async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
        res = await c.get(f"{AI_BASE}/enhance", params={"url": image_url})

    if not res.is_success:
        raise ValueError(f"ENHANCE_FAILED_{res.status_code}")

    data = parse_response(res)

    if data.get("__binary__"):
        return {"type": "enhanced_image", "original_url": image_url, "image_url": data["data_url"], "format": "base64"}

    url = (
        data.get("enhanced_url") or data.get("url") or
        data.get("result")       or data.get("image_url") or ""
    )
    if not url:
        raise ValueError("ENHANCE_FAILED: no url")

    return {"type": "enhanced_image", "original_url": image_url, "image_url": url}

# ── IMG2PROMPT ─────────────────────────────────────────────────────────────
async def action_img2prompt(image_url):
    if not image_url:
        raise ValueError("IMG2PROMPT_NO_IMAGE")

    async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as c:
        res = await c.get(f"{AI_BASE}/img2txt", params={"url": image_url})

    if not res.is_success:
        raise ValueError(f"IMG2PROMPT_FAILED_{res.status_code}")

    data = parse_response(res)
    desc = (
        data.get("text")        or data.get("prompt") or
        data.get("description") or data.get("result") or ""
    )
    if not desc:
        raise ValueError("IMG2PROMPT_FAILED: empty response")

    return {"type": "image_description", "description": str(desc).strip()}

# ── SEARCH ─────────────────────────────────────────────────────────────────
async def action_search(prompt):
    if not prompt or not prompt.strip():
        raise ValueError("SEARCH_NO_QUERY")

    async with httpx.AsyncClient(timeout=TIMEOUT_SEARCH) as c:
        res = await c.get(SEARCH_BASE, params={"prompt": prompt})

    if not res.is_success:
        raise ValueError("SEARCH_FAILED")

    try:
        data = res.json()
    except Exception:
        raise ValueError("SEARCH_FAILED: bad response")

    answer = data.get("answer") or data.get("result") or data.get("text") or ""
    if not answer:
        raise ValueError("SEARCH_FAILED: empty answer")

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
        # Unknown action → fallback to chat
        reply = await call_ai(CHAT_SYSTEM, prompt or "Hello", 600)
        return {"type": "chat", "reply": reply}

# ── ROUTER ─────────────────────────────────────────────────────────────────
async def get_routes(message, image_url):
    """
    Returns list of action dicts.
    Falls back to chat if router fails.
    """
    # If image_url present and no special keyword → likely enhance or img2prompt
    # Let router decide but give it context
    router_input = (
        f'User message: "{message}"\nUser also sent an image URL: {image_url}'
        if image_url else
        f'User message: "{message}"'
    )

    try:
        raw = await call_ai(ROUTER_SYSTEM, router_input, 600)

        # Extract JSON from response
        raw = raw.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end <= start:
            raise ValueError("No JSON found")

        parsed = json.loads(raw[start:end])
        routes = parsed.get("actions", [])

        if not isinstance(routes, list) or not routes:
            raise ValueError("Empty actions")

        # Validate each route has required fields
        valid = []
        for r in routes:
            if isinstance(r, dict) and r.get("action"):
                valid.append({
                    "action": r["action"],
                    "prompt": r.get("prompt", ""),
                    "reply":  r.get("reply", ""),
                })
        if not valid:
            raise ValueError("No valid actions")

        return valid

    except Exception as e:
        print(f"Router failed: {e} | raw: {repr(raw) if 'raw' in dir() else 'N/A'}")
        return [{"action": "chat", "prompt": message, "reply": ""}]

# ── CORE PROCESS ───────────────────────────────────────────────────────────
async def process(message, image_url):
    if not message or not message.strip():
        return 400, {
            "error":   "message parameter zaroori hai",
            "example": "/api/chat?message=hello"
        }

    routes = await get_routes(message, image_url)
    combined_reply = routes[0].get("reply", "") if routes else ""

    # Execute all actions in parallel
    tasks = [
        execute_action(r["action"], r["prompt"], image_url)
        for r in routes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outputs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            err_str = str(result)
            outputs.append({
                "type":      "error",
                "action":    routes[i]["action"],
                "error":     fmt_err(err_str),
                "raw_error": err_str,
            })
        else:
            outputs.append(result)

    # Single action → flat clean response
    if len(outputs) == 1:
        out = outputs[0]
        if out["type"] == "chat":
            # Chat → clean response with just reply
            return 200, {
                "type":  "chat",
                "reply": out.get("reply") or combined_reply,
            }
        # Other action (image/video/etc)
        return 200, {**out, "reply": combined_reply}

    # Multiple actions → grouped
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
        "endpoints": {
            "chat":    "/api/chat?message=hello",
            "image":   "/api/chat?message=cat+ki+image+banao",
            "video":   "/api/chat?message=sunset+ka+video+banao",
            "logo":    "/api/chat?message=VIE+ka+3D+logo+banao",
            "enhance": "/api/chat?message=enhance+karo&imageUrl=https://...",
            "analyze": "/api/chat?message=is+image+mein+kya+hai&imageUrl=https://...",
            "search":  "/api/chat?message=aaj+ka+bitcoin+price",
        }
    })
