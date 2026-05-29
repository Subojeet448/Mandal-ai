# 🤖 VIE AI Smart Router — Python Edition
**Original JS by @MANDAL4482 → Python by Claude**

---

## 📁 File Structure

```
vie-ai-python/
├── api/
│   └── chat.py          ← Main API handler (Vercel serverless)
├── vercel.json          ← Vercel config
├── requirements.txt     ← Python dependencies
└── README.md
```

---

## 🚀 Vercel Deploy Kaise Karein

### Step 1 — Vercel CLI install karo
```bash
npm install -g vercel
```

### Step 2 — Login karo
```bash
vercel login
```

### Step 3 — Project folder mein jao
```bash
cd vie-ai-python
```

### Step 4 — Deploy karo
```bash
vercel --prod
```

Bas! Vercel automatically `requirements.txt` se `httpx` install karega aur `api/chat.py` ko serverless function banayega.

---

## 🔗 API Usage

### GET Request (Browser URL se)
```
https://your-project.vercel.app/api/chat?message=hello
https://your-project.vercel.app/api/chat?message=ek+cat+ki+image+banao
https://your-project.vercel.app/api/chat?message=enhance+karo&imageUrl=https://example.com/photo.jpg
```

### POST Request (Fetch/Axios se)
```javascript
const res = await fetch("https://your-project.vercel.app/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    message: "ek sunset ki image banao",
    imageUrl: ""  // optional
  })
});
const data = await res.json();
```

```python
import httpx

res = httpx.post(
    "https://your-project.vercel.app/api/chat",
    json={"message": "ek sunset ki image banao"}
)
print(res.json())
```

---

## 📤 Response Format

### Single Action
```json
{
  "type": "image",
  "reply": "Yeh lo teri image! 🎨",
  "prompt_used": "a stunning sunset over mountains...",
  "image_url": "https://..."
}
```

### Multiple Actions
```json
{
  "reply": "Dono kaam ho gaye! ✅",
  "total": 2,
  "success": 2,
  "failed": 0,
  "results": [
    { "type": "image", "image_url": "https://..." },
    { "type": "video", "video_url": "https://..." }
  ]
}
```

### Error Response
```json
{
  "type": "error",
  "error": "💬 Image ke liye description do.",
  "raw_error": "IMAGE_NO_PROMPT: ..."
}
```

---

## ⚙️ Supported Actions

| Action | Trigger |
|--------|---------|
| `chat` | Normal conversation, greetings, questions |
| `image_generate` | "image banao", "draw", "generate picture" |
| `video_generate` | "video banao", "animation" |
| `logo_3d` | "3D logo", "icon banao" |
| `enhance` | "enhance karo" + imageUrl |
| `img2prompt` | "kya hai is image mein?" + imageUrl |
| `search` | "aaj ka weather", current news/prices |

---

## 🛠️ Local Testing

```bash
pip install httpx

python -c "
import asyncio
from api.chat import main_handler

async def test():
    status, res = await main_handler('GET', {'message': ['hello']}, {})
    print(status, res)

asyncio.run(test())
"
```

---

**Dev: @MANDAL4482 | Python Port by Claude**
