import os
from typing import List
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def _fallback_outputs(prompt: str) -> List[str]:
    # Last-resort fallback if SDK/key is missing
    return [f"[FAKE OUTPUT] {prompt} :: Variation {i+1}" for i in range(5)]

def _client():
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None
    return OpenAI(api_key=api_key)

def generate_ad_copy(prompt: str) -> List[str]:
    """
    Returns 5 ad variants. If the key/SDK is missing, returns fallback text.
    """
    client = _client()
    if not client:
        return _fallback_outputs(prompt)

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Write 5 short, punchy direct-response ad variants as a bulleted list. "
                    "Each line should be a complete ad sentence. Audience and product details:\n"
                    f"{prompt}"
                )
            }],
            temperature=0.9,
        )
        text = resp.choices[0].message.content or ""
        lines = [l.strip(" -•\t").strip() for l in text.split("\n") if l.strip()]
        variants = [l for l in lines if l][:5]
        return variants if variants else _fallback_outputs(prompt)
    except Exception as e:
        return _fallback_outputs(prompt)

def generate_email(prompt: str) -> str:
    """
    Returns a single marketing email (subject + body).
    If OpenAI errors, we print the error and return it so you see it in the response.
    """
    client = _client()
    if not client:
        return "\n\n".join(_fallback_outputs(prompt))

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Write a marketing email. Start with 'Subject: ...' on the first line, "
                    "then a blank line, then the BODY. "
                    "Do NOT include any placeholders or square brackets. "
                    "Use the recipient name 'Alex' and the site URL 'https://astrobottles.com'. "
                    "Keep it concise and persuasive.\n"
                    f"Brief: {prompt}"
                )
            }],
            temperature=0.8,
        )
        return resp.choices[0].message.content or "Subject:\n\n(Empty body)"
    except Exception as e:
        import traceback
        err = f"OPENAI_ERROR(generate_email): {type(e).__name__}: {e}"
        print("[OPENAI_ERROR][email]", err)
        traceback.print_exc()
        return err

def generate_audit(website: str):
    import json, re
    client = _client()
    if not client:
        return {
            "website": website,
            "score": 72,
            "quick_wins": [
                "Add social proof above the fold",
                "Tighten headline to a concrete benefit",
                "Compress hero image, improve LCP"
            ],
            "next_steps": [
                "Set up baseline analytics & pixels",
                "Launch BOF retargeting",
                "Create 3-email post-purchase flow"
            ]
        }

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f"Perform a quick CRO audit for {website}. "
                    "Return STRICT JSON ONLY (no backticks, no prose) with keys: "
                    "score (0-100), quick_wins (exactly 3 items), next_steps (exactly 3 items)."
                )
            }],
            temperature=0.7,
        )
        content = resp.choices[0].message.content or ""
        # Extract first {...} block and parse
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                data["website"] = website
                return data
            except:
                pass
        # Fallback if parse fails
        return {"website": website, "note": content}
    except Exception:
        return {
            "website": website,
            "score": 72,
            "quick_wins": [
                "Add social proof above the fold",
                "Tighten headline to a concrete benefit",
                "Compress hero image, improve LCP"
            ],
            "next_steps": [
                "Set up baseline analytics & pixels",
                "Launch BOF retargeting",
                "Create 3-email post-purchase flow"
            ]
        }
