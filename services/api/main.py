from fastapi import FastAPI, HTTPException, Body, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Literal
import pathlib, datetime, json, csv
from llm import generate_ad_copy, generate_email, generate_audit
from db import init_db, insert_lead, list_leads
from jobqueue import dispatch_task

app = FastAPI(title="AI Agency API", version="1.0.0")
init_db()


# -----------------------------
# Core models & simple endpoints
# -----------------------------

class Lead(BaseModel):
    name: str
    email: str
    brand: Optional[str] = ""
    notes: Optional[str] = ""


class CampaignRequest(BaseModel):
    brand: str
    product: str
    audience: Optional[str] = ""
    tone: Optional[str] = "high converting, brand-safe"
    platform: Literal["facebook", "instagram", "tiktok", "google"] = "facebook"
    email: Optional[str] = ""
    website: Optional[str] = ""
    budget: Optional[str] = ""


class AdCopyRequest(BaseModel):
    brand: str
    product: str
    audience: Optional[str] = ""
    tone: Optional[str] = "high converting, brand-safe"
    platform: Literal["facebook", "instagram", "tiktok", "google"] = "facebook"


class EmailCopyRequest(BaseModel):
    brand: str
    product: str
    audience: Optional[str] = ""
    tone: Optional[str] = "conversational, high converting"
    website: Optional[str] = ""


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/leads")
def create_lead(lead: Lead):
    insert_lead(lead.dict())
    return {"status": "ok"}


@app.get("/leads")
def get_leads():
    return {"leads": list_leads()}


@app.post("/campaigns/brief")
def create_brief(req: CampaignRequest, background_tasks: BackgroundTasks):
    payload = req.dict()
    dispatch_task("generate_campaign", payload)
    return {"status": "queued", "payload": payload}


@app.post("/copy/ad")
def make_ad_copy(req: AdCopyRequest):
    prompt = (
        f"Write a {req.platform} ad for the following:\n"
        f"Brand: {req.brand}\n"
        f"Product: {req.product}\n"
        f"Audience: {req.audience or 'cold prospects'}\n"
        f"Tone: {req.tone}\n"
        "Include a strong hook, body, and a call-to-action.\n"
        "Return only the ad copy text, no explanation."
    )
    ad_text = generate_ad_copy(prompt)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_dir = pathlib.Path("/app/out")
    out_dir.mkdir(exist_ok=True)
    fp = out_dir / f"ad-{ts}.txt"
    fp.write_text(str(ad_text), encoding="utf-8")
    return {"ad": ad_text, "saved_to": str(fp)}


@app.post("/copy/email")
def make_email_copy(req: EmailCopyRequest):
    prompt = (
        f"Write a marketing email for the following:\n"
        f"Brand: {req.brand}\n"
        f"Product: {req.product}\n"
        f"Audience: {req.audience or 'cold prospects'}\n"
        f"Tone: {req.tone}\n"
        f"Website: {req.website}\n"
        "Structure the email with subject line, preview text, greeting, body, and call-to-action.\n"
        "Return the full email including the subject line on the first line prefixed by 'Subject: '."
    )
    email_text = generate_email(prompt)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_dir = pathlib.Path("/app/out")
    out_dir.mkdir(exist_ok=True)
    fp = out_dir / f"email-{ts}.txt"
    fp.write_text(str(email_text), encoding="utf-8")
    return {"email": email_text, "saved_to": str(fp)}


@app.post("/audit")
def audit(website: str = Body(..., embed=True)):
    return {"audit": generate_audit(website)}


class MiniCampaign(BaseModel):
    brand: str
    product: str
    audience: Optional[str] = ""
    website: Optional[str] = ""
    budget: Optional[str] = ""
    email: Optional[str] = ""


@app.post("/mini-campaign")
def mini_campaign(payload: MiniCampaign):
    brand = payload.brand
    product = payload.product
    audience = payload.audience or "cold prospects"
    website = payload.website or ""
    budget = payload.budget or ""
    email_for_delivery = payload.email or ""

    ad_prompt = (
        f"Brand: {brand}\n"
        f"Product: {product}\n"
        f"Audience: {audience}\n"
        f"Website: {website}\n"
        f"Budget: {budget}\n"
        "Write 3 high-converting ad variants (primary text + headline + call-to-action) "
        "for a paid social campaign. Return them as a numbered list."
    )
    email_prompt = (
        f"Brand: {brand}\n"
        f"Product: {product}\n"
        f"Audience: {audience}\n"
        f"Website: {website}\n"
        "Write a marketing email to drive sales of this product. "
        "Include a compelling subject line (prefix with 'Subject:')."
    )

    ads = generate_ad_copy(ad_prompt)
    email_text = generate_email(email_prompt)

    out_dir = pathlib.Path("/app/out")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"campaign-{ts}.json"
    out_file.write_text(
        json.dumps({"ads": ads, "email": email_text}, indent=2),
        encoding="utf-8",
    )

    result = {"ads": ads, "email": email_text, "saved_to": str(out_file)}

    try:
        if payload.email:
            from mailer import send_campaign
            subj = f"{payload.brand}: Your New AI Campaign (Ads + Email)"
            body = (
                "Ads:\n" + str(ads) +
                "\n\nEmail:\n" + str(email_text) +
                "\n\n—\nALX Scales\nAI Systems That Scale E-Commerce Brands\nalxscales.ai@gmail.com"
            )
            send_campaign(payload.email, subj, body)
            result["emailed_to"] = payload.email
    except Exception as e:
        result["email_error"] = f"{type(e).__name__}: {e}"

    try:
        log_path = out_dir / "history.csv"
        is_new = not log_path.exists()
        with log_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["ts", "brand", "product", "audience", "website", "budget", "email"])
            writer.writerow([ts, brand, product, audience, website, budget, email_for_delivery])
    except Exception:
        pass

    return result


# -----------------------------
# Helper fns for Tally webhook
# -----------------------------

def _find_field(fields, label, default=None):
    label = (label or "").strip()
    for f in fields:
        f_label = (f.get("label") or "").strip()
        if f_label == label:
            return f.get("value", default)
    return default


def _get_plan(fields, default="Tier 1"):
    for f in fields:
        label = (f.get("label") or "").strip()
        if label == "Which Plan?":
            val = f.get("value")
            options = f.get("options") or []
            if isinstance(val, list) and val:
                selected_id = val[0]
                for opt in options:
                    text = opt.get("text")
                    if opt.get("id") == selected_id and text:
                        return text
            if isinstance(val, str) and val:
                return val
    return default


def _safe_text(value, fallback=""):
    """
    Normalize the model output into clean text.
    - If it's a string → return as-is (with unicode fixed)
    - If it's a list of strings → join them into readable multiline text
    - Otherwise → fallback to JSON or fallback string
    """

    # If already plain text:
    if isinstance(value, str):
        text = value
    # List of lines → join
    elif isinstance(value, list) and all(isinstance(x, str) for x in value):
        text = "\n".join(value)
    # Anything else → JSON stringify
    else:
        try:
            text = json.dumps(value, indent=2)
        except Exception:
            text = fallback

    # Fix escaped unicode (\u2014) AND raw unicode
    text = text.replace("\\u2014", "—")
    text = text.replace("\u2014", "—")

    # Clean accidental list markers from JSON-y lists
    text = text.replace("[", "").replace("]", "")

    return text.strip()


# -----------------------------
# Tally → Weekly Creative Pack
# -----------------------------

@app.post("/webhooks/tally/intake")
async def tally_intake(request: Request):
    # --- 1) Parse + log payload ---
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    debug_dir = pathlib.Path("/app/out/tally_raw")
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    raw_file = debug_dir / f"tally-{ts}.json"
    raw_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    data = payload.get("data", {})
    fields = data.get("fields", [])

    print("Tally field labels:", [f.get("label") for f in fields])

    plan = _get_plan(fields)
    print("Selected plan:", plan)

    # --- 2) Extract fields from Tally ---
    brand_name      = _find_field(fields, "Brand Name", "")
    website_url     = _find_field(fields, "Website URL", "")
    social_links    = _find_field(fields, "Social Media Links (optional)", "")
    main_product    = _find_field(fields, "Main Product / Service", "") or _find_field(fields, "Main Product / Service\n", "")
    product_url     = _find_field(fields, "Product/Service URL", "")
    ideal_customer  = _find_field(fields, "Describe your ideal customer", "")
    audience_age    = _find_field(fields, "Audience Age Range", "")
    main_benefit    = _find_field(fields, "Main benefit or value proposition", "")
    top_competitors = _find_field(fields, "Top Competitors (optional)", "")
    ad_tone         = _find_field(fields, "Ad tone/style you want", "")
    monthly_budget  = _find_field(fields, "Monthly Ad Budget", "")
    lifestyle_flag  = _find_field(fields, "Do you want AI-generated lifestyle images?", "")
    video_flag      = _find_field(fields, "Do you want AI-generated video ads?", "")
    additional_notes = _find_field(fields, "Additional Notes (optional)", "")
    client_name     = (_find_field(fields, "Your Name", "") or "").strip()
    client_email    = (_find_field(fields, "Business Email", "") or "").strip()
    package_email   = (_find_field(fields, "Where should we send your weekly campaign package?", "") or "").strip()
    phone           = _find_field(fields, "Phone (optional)", "")

    product_images = _find_field(fields, "Upload Product Images", []) or []
    extra_images   = _find_field(fields, "Additional Images (optional)", []) or []

    audience_desc = ideal_customer or f"{audience_age} audience"
    angle = main_benefit or "Scale sales with better ads and creative"

    base_context = f"""
Brand: {brand_name}
Product/Service: {main_product}
Ideal Customer: {audience_desc}
Main Benefit: {angle}
Tone/Style: Gen-Z professional, friendly, slightly connective
Notes: {additional_notes}
"""

    # --- 3) Generate 3 ready-to-post ads (separate calls) ---
    ads_blocks = []
    for i in range(1, 4):
        ad_prompt = base_context + f"""
Write ONE ready-to-post paid social ad for this brand (Meta / IG / TikTok).

Use this exact plain-text format:

Ad {i} — [short nickname]:
Platform: [Meta / IG / TikTok]
Placement: [Feed / Story / Reels]
Primary Text: [2–4 sentence ad copy written to convert, not instructions]
Headline: [6–9 word punchy headline]
CTA: [short call-to-action phrase]
Image Description: [detailed description for a lifestyle product image a designer or AI could make]
Aspect Ratio: [1080x1350 or 1080x1920]

IMPORTANT:
- The first line MUST start with exactly "Ad {i} —".
- Do NOT change the number {i} to anything else.
- No markdown (#, **, -, *).
- No bullet points.
- No explanations, only the ad in the exact format above.
"""
        try:
            ad_i = generate_ad_copy(ad_prompt)
        except Exception as e:
            print(f"[OPENAI_ERROR][ad_{i}] {repr(e)}")
            ad_i = f"Error generating Ad {i}. Please check backend logs."
        ads_blocks.append(_safe_text(ad_i, f"Error generating Ad {i}"))

    ads_text = "\n\n".join(ads_blocks)

    # --- 4) Generate UGC video script ---
    script_prompt = base_context + """
Write ONE short-form UGC video script (15–25 seconds) for this brand.

Return it in EXACTLY this format (no extra lines before or after):

Hook: [actual spoken line in the first 2–3 seconds]
Scene 1 (0–5s): [On screen:] ... [Line:] ...
Scene 2 (5–12s): [On screen:] ... [Line:] ...
Scene 3 (12–20s): [On screen:] ... [Line:] ...
On-Screen Text: [short text overlays, comma-separated]
Voiceover Script: [full VO lines if different from on-camera]
CTA Line: [final spoken line that pushes them to click or buy]

RULES:
- Do NOT write a list of separate one-liner slogans.
- This must be one coherent script with scenes that flow.
- No markdown.
- No bullet symbols.
- Do NOT add any extra headings, commentary, or explanation.
"""

    try:
        script_raw = generate_ad_copy(script_prompt)
    except Exception as e:
        print("[OPENAI_ERROR][script] OPENAI_ERROR(script_text):", repr(e))
        script_raw = "Error generating video script. Please check backend logs."
    script_text = _safe_text(script_raw, "Error generating video script. Please check backend logs.")

    # --- 5) Generate 3 image prompts ---
    image_prompts_prompt = base_context + """
Write exactly 3 short AI image prompts (1–2 sentences each) for lifestyle product photos.

Return them in EXACTLY 3 lines, like:

Image Prompt 1: ...
Image Prompt 2: ...
Image Prompt 3: ...

Each prompt should describe a realistic lifestyle scene that would make this product look desirable to the ideal customer.

RULES:
- Return exactly 3 lines, no more and no less.
- Each line MUST start with "Image Prompt 1:", "Image Prompt 2:", or "Image Prompt 3:".
- No markdown.
- No bullet symbols.
- Do NOT add any other text before or after the 3 lines.
"""

    try:
        image_raw = generate_ad_copy(image_prompts_prompt)
    except Exception as e:
        print("[OPENAI_ERROR][images] OPENAI_ERROR(image_prompts_text):", repr(e))
        image_raw = "Error generating image prompts. Please check backend logs."
    image_prompts_text = _safe_text(image_raw, "Error generating image prompts. Please check backend logs.")

    # --- 6) Generate targeting block ---
    targeting_prompt = base_context + """
Propose a simple paid social targeting pack for Meta Ads.

Use this exact format:

Targeting:
Location: [country or region]
Age: [age range]
Interests: [3–6 interest ideas]
Behavior: [e.g. Engaged Shoppers]
Why This Works: [1–3 sentences explaining why this targeting fits the brand and audience]

RULES:
- No markdown.
- No bullet symbols.
"""
    try:
        targeting_raw = generate_ad_copy(targeting_prompt)
    except Exception as e:
        print("[OPENAI_ERROR][targeting] OPENAI_ERROR(targeting_text):", repr(e))
        targeting_raw = "Error generating targeting recommendations. Please check backend logs."
    targeting_text = _safe_text(targeting_raw, "Error generating targeting recommendations. Please check backend logs.")

    # --- 7) Email wrapper (no subject, no greeting, no closing) ---
    email_prompt = f"""
You are writing a WEEKLY CREATIVE PACK email from ALX Scales to the client.

Brand: {brand_name}
Product: {main_product}
Website: {website_url or product_url}
Ideal Customer: {audience_desc}
Tone: Gen-Z professional, friendly, helpful, slightly connective

STRUCTURE (PLAIN TEXT ONLY):

Write:
- 2–3 intro sentences (like "Delivered! Here’s your creative pack for the week — everything is ready for you to launch today.")
- A short paragraph describing what’s inside (3 ad variations, 1 video script, 3 image prompts, targeting suggestions).
- 3–5 sentences summarizing the angles and vibe.
- A step-by-step "How to use this pack" section.

RULES:
- Do NOT include a subject line.
- Do NOT include any greeting (no 'Hi', 'Hey', or name).
- Do NOT include any closing or signature.
- Do NOT start with 'Subject:' or 'Hi' or 'Hey'.
- Only return the body content as plain text paragraphs.
"""

    try:
        email_raw = generate_email(email_prompt)
    except Exception as e:
        print("[OPENAI_ERROR][email] OPENAI_ERROR(generate_email):", repr(e))
        email_raw = "Here’s your creative pack for this week."

    email_raw = _safe_text(email_raw, "Here’s your creative pack for this week.")

    cleaned_lines = []
    for line in email_raw.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if not stripped:
            if cleaned_lines:
                cleaned_lines.append(line)
            continue
        if lower.startswith("subject:"):
            continue
        if lower.startswith("hi ") or lower.startswith("hey "):
            continue
        cleaned_lines.append(line)
    email_intro = "\n".join(cleaned_lines).strip()

    # --- 8) Assemble creative pack text ---
    creative_pack = (
    str(ads_text).strip()
    + "\n\nVideo Script:\n"
    + str(script_text).strip()
    + "\n\nImage Prompts:\n"
    + str(image_prompts_text).strip()
    + "\n\nTargeting Recommendations:\n"
    + str(targeting_text).strip()
)


    # --- 9) Persist JSON campaign file ---
    safe_brand = "".join(
        c for c in (brand_name or "brand").lower().replace(" ", "-")
        if c.isalnum() or c in ("-", "_")
    )
    client_dir = pathlib.Path("/app/out/clients") / safe_brand
    client_dir.mkdir(parents=True, exist_ok=True)

    out_file = client_dir / f"campaign-{ts}.json"
    out_payload = {
        "brand_name": brand_name,
        "website_url": website_url,
        "social_links": social_links,
        "main_product": main_product,
        "product_url": product_url,
        "ideal_customer": ideal_customer,
        "audience_age": audience_age,
        "main_benefit": main_benefit,
        "top_competitors": top_competitors,
        "ad_tone": ad_tone,
        "monthly_budget": monthly_budget,
        "lifestyle_flag": lifestyle_flag,
        "video_flag": video_flag,
        "additional_notes": additional_notes,
        "client_name": client_name,
        "client_email": client_email,
        "package_email": package_email,
        "phone": phone,
        "product_images": product_images,
        "extra_images": extra_images,
        "plan": plan,
        "created_at": ts,
        "ads_block": ads_text,
        "video_script": script_text,
        "image_prompts": image_prompts_text,
        "targeting": targeting_text,
        "creative_pack": creative_pack,
    }
    out_file.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    target_email = package_email or client_email
    result = {
        "saved_to": str(out_file),
        "brand": brand_name,
        "sent_to": target_email,
        "plan": plan,
    }

    # --- 10) Send email ---
    try:
        from mailer import send_campaign

        subject = f"Your Weekly Creative Pack — {brand_name}"

        body = (
            f"Hi {client_name or 'there'},\n\n"
            f"{email_intro}\n\n"
            "----------------------------\n"
            "CREATIVE PACK\n"
            "----------------------------\n\n"
            f"{creative_pack}\n\n"
            "----------------------------\n"
            "Brand summary\n"
            "----------------------------\n"
            f"Website: {website_url or product_url}\n"
            f"Ideal customer: {audience_desc}\n"
            f"Monthly ad budget: {monthly_budget}\n"
            f"Plan: {plan}\n\n"
            "If you’d like help tweaking or expanding this creative pack, just reply to this email.\n\n"
            "—\n"
            "ALX Scales\n"
            "AI Systems That Scale Brands\n"
            "alxscales.ai@gmail.com"
        )

        print("SMTP DEBUG → Attempting to send to:", target_email)
        if target_email:
            send_campaign(target_email, subject, body)
            print("SMTP DEBUG → Email sent successfully.")
            result["emailed"] = True
        else:
            print("SMTP DEBUG → No target_email provided, skipping send.")
            result["emailed"] = False

    except Exception as e:
        result["emailed"] = False
        result["email_error"] = f"{type(e).__name__}: {e}"
        print("EMAIL ERROR in tally_intake:", result["email_error"])

    return result
