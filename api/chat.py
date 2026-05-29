from flask import Flask, request, jsonify
import json
import asyncio
import httpx

app = Flask(__name__)

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
You are "VIE AI" a powerful multi-modal AI assistant made by @MANDAL4482.
IMAGE GENERATION - ek sunset ki image banao
VIDEO GENERATION - ek video banao mountains ka
IMAGE ENHANCEMENT - is photo ko enhance karo
IMAGE UNDERSTANDING - is image mein kya hai?
REAL-TIME SEARCH - aaj ka weather kya hai?
SMART CONVERSATION - Hindi, English, or Hinglish
NEVER say I cannot generate images. You CAN do everything.
If asked kya tum AI ho? Yes, main VIE AI hun, @MANDAL4482 ka banaya hua.
"""

ROUTER_SYSTEM = """You are an intelligent multi-action router for VIE AI.
Respond ONLY in this EXACT JSON format, no markdown, no extra text:
{
  "actions": [
    {
      "action": "<action_type>",
      "prompt": "<extracted clean prompt in English>",
      "reply": "<short friendly reply in same language as user>"
    }
  ]
}
Action types: chat, image_generate, video_generate, logo_3d, enhance, img2prompt, search
RULES:
1. Multiple tasks = multiple action objects
2. prompt must be English translation of user request
3. reply = ONE short reply for all actions in user language
4. For enhance and img2prompt: prompt = ""
5. ONLY output valid JSON. Nothing else."""

IMAGE_ENHANCER_SYSTEM = """You are an expert AI image prompt engineer.
Expand the user request into a rich detailed prompt with lighting, quality tags like 8k photorealistic, composition, mood.
Keep under 80 words. Output ONLY the enhanced prompt, no explanation, no quotes."""

SEARCH_SUMMARIZER_SYSTEM = """You are a helpful assistant summarizing search results.
Give a SHORT clear answer in 3-5 lines in the SAME language the user asked. Be friendly."""

CHAT_SYSTEM = f"""{AI_CAPABILITIES}
You are VIE AI, friendly helpful smart.
Reply in the SAME language the user wrote in.
Keep replies SHORT, 2-4 lines for simple questions.
NEVER say you cannot generate images or videos."""

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
    "ENHANCE_NO_IMAGE":    "Enhance ke liye image URL bhi bhejo.",
    "IMG2PROMPT_NO_IMAGE": "Image describe karne ke liye URL bhi do.",
    "SEARCH_NO_QUERY":     "Kya dhundhna hai? Puri query likho.",
    "SEARCH_NO_RESULTS":   "Koi result nahi mila. Alag words try karo.",
    "SEARCH_UNAVAILABLE":  "Search engine abhi band hai.",
}

def format_error(msg):
    for code, friendly in ERROR_MAP.items():
        if code in msg:
            return friendly
    return f"Kuch gadbad ho gayi: {msg.split(':')[0]}. Dobara try karo."

# ── ASYNC HELPERS ──────────────────────────────────────────────────────────
async def call_ai(system, user_msg, max_tokens=500):
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
        raise ValueError(f"AI_ERROR_{s}")
    data = res.json()
    return (data.get("content") or [{}])[0].get("text", "").strip()

async def enhance_prompt(raw):
    try:
        return await call_ai(IMAGE_ENHANCER_SYSTEM, raw, 150)
    except:
        return raw

async def search_and_summarize(query):
    async with httpx.AsyncClient(timeout=TIMEOUT_SEARCH) as client:
        res = await client.get(SEARCH_BASE, params={"prompt": query})
    if not res.is_success:
        raise ValueError("SEARCH_UNAVAILABLE" if res.status_code == 503 else f"SEARCH_ERROR_{res.status_code}")
    data = res.json()
    if data.get("status") != "success" or not data.get("answer"):
        raise ValueError("SEARCH_NO_RESULTS")
    summary = await call_ai(SEARCH_SUMMARIZER_SYSTEM, f'User asked: "{query}"\nResults: {data["answer"]}', 300)
    sources = [{"name": s.get("name", "Source"), "url": s.get("url")} for s in (data.get("sources") or [])[:3]]
    return {"answer": summary, "sources": sources}

async def execute_action(action, prompt, image_url):
    if action == "chat":
        reply = await call_ai(CHAT_SYSTEM, prompt or "Hello", 600)
        return {"type": "chat", "reply": reply}

    elif action == "image_generate":
        if not prompt or not prompt.strip(): raise ValueError("IMAGE_NO_PROMPT")
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
        if not prompt or not prompt.strip(): raise ValueError("VIDEO_NO_PROMPT")
        enhanced = await enhance_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_VIDEO) as c:
            res = await c.get(f"{AI_BASE}/video", params={"prompt": enhanced})
        if not res.is_success:
            raise ValueError(f"VIDEO_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("video_url") or data.get("url") or data.get("result")
        if not url: raise ValueError("VIDEO_EMPTY")
        return {"type": "video", "prompt_used": enhanced, "video_url": url}

    elif action == "logo_3d":
        if not prompt or not prompt.strip(): raise ValueError("LOGO_NO_PROMPT")
        enhanced = await enhance_prompt(prompt)
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
            res = await c.get(f"{LOGO_BASE}/logo", params={"prompt": enhanced})
        if not res.is_success: raise ValueError(f"LOGO_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("image_url") or data.get("url") or data.get("logo_url")
        if not url: raise ValueError("LOGO_EMPTY")
        return {"type": "logo_3d", "prompt_used": enhanced, "image_url": url}

    elif action == "enhance":
        if not image_url: raise ValueError("ENHANCE_NO_IMAGE")
        async with httpx.AsyncClient(timeout=TIMEOUT_IMAGE) as c:
            res = await c.get(f"{AI_BASE}/enhance", params={"url": image_url})
        if not res.is_success: raise ValueError(f"ENHANCE_ERROR_{res.status_code}")
        data = res.json()
        url = data.get("enhanced_url") or data.get("url") or data.get("result")
        if not url: raise ValueError("ENHANCE_EMPTY")
        return {"type": "enhanced_image", "original_url": image_url, "image_url": url}

    elif action == "img2prompt":
        if not image_url: raise ValueError("IMG2PROMPT_NO_IMAGE")
        async with httpx.AsyncClient(timeout=TIMEOUT_DEFAULT) as c:
            res = await c.get(f"{AI_BASE}/img2txt", params={"url": image_url})
        if not res.is_success: raise ValueError(f"IMG2PROMPT_ERROR_{res.status_code}")
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

async def process(method, message, image_url):
    if not message or not message.strip():
        return 400, {"error": "message parameter zaroori hai", "example": "/api/chat?message=hello"}

    router_input = f'User message: "{message}"\nImage: {image_url}' if image_url else f'User message: "{message}"'

    try:
        raw = await call_ai(ROUTER_SYSTEM, router_input, 1000)
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
        routes = parsed.get("actions", [])
        if not isinstance(routes, list) or not routes:
            raise ValueError("empty")
    except Exception as e:
        print(f"Router failed: {e}")
        routes = [{"action": "chat", "prompt": message, "reply": ""}]

    combined_reply = routes[0].get("reply", "") if routes else ""
    tasks = [execute_action(r.get("action", "chat"), r.get("prompt", ""), image_url) for r in routes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outputs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            raw_err = str(result)
            outputs.append({"type": "error", "action": routes[i].get("action", "unknown"),
                            "error": format_error(raw_err), "raw_error": raw_err})
        else:
            outputs.append(result)

    if len(outputs) == 1:
        return 200, {**outputs[0], "reply": combined_reply}

    return 200, {
        "reply": combined_reply,
        "total": len(outputs),
        "success": sum(1 for o in outputs if o.get("type") != "error"),
        "failed": sum(1 for o in outputs if o.get("type") == "error"),
        "results": outputs,
    }

# ── FLASK ROUTES ───────────────────────────────────────────────────────────
@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
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
        status, resp = asyncio.run(process(request.method, message, image_url))
        return jsonify(resp), status
    except Exception as err:
        return jsonify({
            "error": format_error(str(err)),
            "type": "server_error",
            "dev": "@MANDAL4482"
        }), 500

# ── ROOT ROUTE ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({
        "name": "VIE AI Smart Router",
        "version": "3.0 Python",
        "dev": "@MANDAL4482",
        "usage": {
            "GET":  "/api/chat?message=hello",
            "POST": "/api/chat  body: {message: 'hello'}"
        }
    })

if __name__ == "__main__":
    app.run(debug=True)
