from fastapi import FastAPI, HTTPException, Body, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Literal
import pathlib, datetime, json, csv
from llm import generate_ad_copy, generate_email, generate_audit
from db import init_db, insert_lead, list_leads
from jobqueue import dispatch_task

app = FastAPI(title="AI Agency API", version="1.0.0")
init_db()


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
    # Kick off async generation via Celery
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
    fp.write_text(ad_text, encoding="utf-8")
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
    fp.write_text(email_text, encoding="utf-8")
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

    # Try emailing if provided — never crash the request
    try:
        if payload.email:
            from mailer import send_campaign  # local import to avoid hard fail if file missing
            subj = f"{payload.brand}: Your New AI Campaign (Ads + Email)"
            body = (
                "Ads:\n- " + "\n- ".join(ads) +
                "\n\nEmail:\n" + email_text +
                "\n\n—\nALX Scales\nAI Systems That Scale E-Commerce Brands\nalxscales.ai@gmail.com"
            )
            send_campaign(payload.email, subj, body)
            result["emailed_to"] = payload.email
    except Exception as e:
        result["email_error"] = f"{type(e).__name__}: {e}"

    # Optional: append a CSV log line (history.csv)
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


def _find_field(fields, label, default=None):
    """
    Helper to get a field value from Tally by its label.
    We strip whitespace/newlines so labels like "Main Product / Service\\n" still match.
    """
    label = (label or "").strip()
    for f in fields:
        f_label = (f.get("label") or "").strip()
        if f_label == label:
            return f.get("value", default)
    return default


def _get_plan(fields, default: str = "Tier 1") -> str:
    """
    Find the selected plan (Tier 1 / Tier 2 / Tier 3) from the Tally fields.

    The field looks like:
      label: "\\nWhich Plan?\\n"
      type: MULTIPLE_CHOICE
      value: [<option_id>]
      options: [{id, text}, ...]

    This helper maps the option id -> its text (e.g. "Tier 2").
    """
    for f in fields:
        label = (f.get("label") or "").strip()
        if label == "Which Plan?":
            val = f.get("value")
            options = f.get("options") or []

            # MULTIPLE_CHOICE gives a list of option IDs
            if isinstance(val, list) and val:
                selected_id = val[0]
                for opt in options:
                    if opt.get("id") == selected_id:
                        return opt.get("text") or default

            # If for some reason it's already text:
            if isinstance(val, str) and val:
                return val

    return default


@app.post("/webhooks/tally/intake")
async def tally_intake(request: Request):
    """
    Webhook endpoint for Tally 'ALX Scales – New Client Intake' form.
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    # Save raw payload for debugging
    debug_dir = pathlib.Path("/app/out/tally_raw")
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    raw_file = debug_dir / f"tally-{ts}.json"
    raw_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    data = payload.get("data", {})
    fields = data.get("fields", []) or []

    print("Tally field labels:", [f.get("label") for f in fields])

    # Extract fields by label (with stripping handled in _find_field)
    brand_name = _find_field(fields, "Brand Name", "")
    website_url = _find_field(fields, "Website URL", "")
    social_links = _find_field(fields, "Social Media Links (optional)", "")
    main_product = _find_field(fields, "Main Product / Service", "") or _find_field(
        fields, "Main Product / Service\n", ""
    )
    product_url = _find_field(fields, "Product/Service URL", "")
    ideal_customer = _find_field(fields, "Describe your ideal customer", "")
    audience_age = _find_field(fields, "Audience Age Range", "")
    main_benefit = _find_field(fields, "Main benefit or value proposition", "")
    top_competitors = _find_field(fields, "Top Competitors (optional)", "")
    ad_tone = _find_field(fields, "Ad tone/style you want", "")
    monthly_budget = _find_field(fields, "Monthly Ad Budget", "")
    lifestyle_flag = _find_field(fields, "Do you want AI-generated lifestyle images?", "")
    video_flag = _find_field(fields, "Do you want AI-generated video ads?", "")
    additional_notes = _find_field(fields, "Additional Notes (optional)", "")
    client_name = (_find_field(fields, "Your Name", "") or "").strip()
    client_email = (_find_field(fields, "Business Email", "") or "").strip()
    package_email = (_find_field(fields, "Where should we send your weekly campaign package?", "") or "").strip()
    phone = _find_field(fields, "Phone (optional)", "")

    # uploads will come as lists/objects from Tally
    product_images = _find_field(fields, "Upload Product Images", []) or []
    extra_images = _find_field(fields, "Additional Images (optional)", []) or []

    audience_desc = ideal_customer or f"{audience_age} audience"
    angle = main_benefit or "Scale sales with better ads and creative"

    # Determine plan (Tier 1 / Tier 2 / Tier 3)
    plan = _get_plan(fields)
    print("Selected plan:", plan)

    # ---------- PROMPTS (Tier scaffolding) ----------

    # Tier 1 prompts (used for all tiers for now)
    tier1_ad_prompt = f"""
    You are a senior creative strategist for paid social ads (Meta, TikTok, IG, TikTok Shop).

    Your job is to create POST-READY ad creatives for this brand.
    No concepts, no brainstorming, no explanations.
    Only finished assets that the client can upload today.

    Brand: {brand_name}
    Product/Service: {main_product}
    Ideal Customer: {audience_desc}
    Main Benefit: {angle}
    Tone/Style: Gen-Z professional, friendly, slightly connective
    Notes: {additional_notes}

    DELIVERABLES (PLAIN TEXT ONLY):

    1) READY-TO-POST ADS
    Create 3 separate ads. For EACH ad, use this exact format, with blank lines between ads:

    Ad 1 — [short nickname for the angle]:
    Platform: [Meta / IG / TikTok]
    Placement: [Feed / Story / Reels]
    Primary Text: [2–4 sentence ad copy written to convert, not instructions]
    Headline: [punchy, 6–9 words]
    CTA: [short call-to-action phrase]
    Image Description: [detailed description for a lifestyle product image a designer or AI could make]
    Aspect Ratio: [1080x1350 or 1080x1920]

    Ad 2 — [angle nickname]:
    Platform:
    Placement:
    Primary Text:
    Headline:
    CTA:
    Image Description:
    Aspect Ratio:

    Ad 3 — [angle nickname]:
    Platform:
    Placement:
    Primary Text:
    Headline:
    CTA:
    Image Description:
    Aspect Ratio:

    2) IMAGE PROMPTS
    Write exactly 3 short AI image prompts (1–2 sentences each) for lifestyle product photos.
    Format them exactly like this:
    Image Prompt 1: ...
    Image Prompt 2: ...
    Image Prompt 3: ...

    3) VIDEO SCRIPT (UGC, 15–25 SECONDS)
    Write ONE complete UGC-style script a creator could literally read on camera.
    Do NOT describe what they "should" say — write the actual spoken lines.
    Use this format:

    Video Script:
    Hook: [actual line spoken in the first 2–3 seconds]
    Scene 1: [what’s on screen] / [what is said]
    Scene 2: [on screen] / [what is said]
    Scene 3: [on screen] / [what is said]
    On-Screen Text: [short text overlays]
    Voiceover Script: [full VO lines if different from on-camera]
    CTA Line: [final line that pushes them to click or buy]

    4) TARGETING PACK (FOR META ADS)
    Provide a simple targeting pack in this format:

    Targeting:
    Location: [country or region]
    Age: [age range]
    Interests: [3–6 interest ideas]
    Behavior: [e.g. Engaged Shoppers]
    Why This Works: [1–2 sentences explaining why this targeting fits the brand and audience]

    RULES:
    - Do NOT use markdown (#, **, -, *, etc.).
    - Do NOT list concepts or ideas, only finished outputs.
    - Do NOT explain what you are doing.
    - Follow the exact labels and structure above so it’s easy to read and copy.
    """

    tier1_email_prompt = f"""
    You are writing a WEEKLY CREATIVE PACK email from ALX Scales to the client.

    Brand: {brand_name}
    Product: {main_product}
    Website: {website_url or product_url}
    Ideal Customer: {audience_desc}
    Tone: Gen-Z professional, friendly, helpful, slightly connective
    Client Name: {client_name or 'there'}

    STRUCTURE (PLAIN TEXT ONLY):

    1) Greeting:
    Short, friendly, with their name if available.

    2) Intro:
    Example tone:
    "Delivered! Here’s your creative pack for the week — everything is ready for you to launch today."

    3) What’s Inside:
    Briefly list what they’re getting this week:
    - 3 ready-to-post ad variations
    - 1 short-form video script
    - 3 image prompts
    - Targeting suggestions

    4) Short Highlights:
    In 3–5 sentences, summarize:
    - The main angles of the ads
    - The focus of the video script
    - The overall vibe for this week’s creative.

    5) How To Use This Pack:
    Give moderate-detail, clear, step-by-step instructions:
    1. Open Canva (or your creative tool) and create visuals using the image descriptions.
    2. Use 1080x1350 or 1080x1920 formats for ads.
    3. Paste the Primary Text, Headline, and CTA from the creative pack into your ad platform.
    4. Record the UGC video script using the scenes provided.
    5. Launch your ads using the targeting block as a starting point.
    6. If they need help, tell them to reply to the email.

    6) Close:
    Encouraging, supportive, brand-aligned closing line.

    RULES:
    - Do NOT include subject line (that will be added separately).
    - Do NOT use markdown.
    - Do NOT repeat the full ads or script. This email is a friendly wrapper around the creative pack.
    - Keep it concise and human, not robotic.
    """

    # For now, Tier 2 and Tier 3 reuse Tier 1 prompts.
    # Later you can replace these with dedicated Tier 2 / Tier 3 prompts without changing the logic.
    tier2_ad_prompt = tier1_ad_prompt
    tier2_email_prompt = tier1_email_prompt
    tier3_ad_prompt = tier1_ad_prompt
    tier3_email_prompt = tier1_email_prompt

    if plan == "Tier 1":
        ad_prompt = tier1_ad_prompt
        email_prompt = tier1_email_prompt
    elif plan == "Tier 2":
        ad_prompt = tier2_ad_prompt
        email_prompt = tier2_email_prompt
    else:  # Tier 3 or anything else
        ad_prompt = tier3_ad_prompt
        email_prompt = tier3_email_prompt

    # call your existing AI
    try:
        ads = generate_ad_copy(ad_prompt)
    except Exception as e:
        print("[OPENAI_ERROR][ads] OPENAI_ERROR(generate_ad_copy):", repr(e))
        ads = "Error generating ads. Please check backend logs."

    try:
        email_text = generate_email(email_prompt)
    except Exception as e:
        print("[OPENAI_ERROR][email] OPENAI_ERROR(generate_email):", repr(e))
        email_text = "Error generating email. Please contact support."

    # persist under /app/out/clients/<brand>/
    safe_brand = "".join(
        c for c in (brand_name or "").lower().replace(" ", "-")
        if c.isalnum() or c in ("-", "_")
    )
    client_dir = pathlib.Path("/app/out/clients") / (safe_brand or "unknown-brand")
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
        "generated_ads": ads,
        "generated_email": email_text,
        "plan": plan,
        "created_at": ts,
    }
    out_file.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    target_email = package_email or client_email
    result = {
        "saved_to": str(out_file),
        "brand": brand_name,
        "sent_to": target_email,
        "plan": plan,
    }

    # email the package
    try:
        from mailer import send_campaign

        subject = f"Your Weekly Creative Pack — {brand_name}"

        # ads is our full creative pack text
        ads_block = ads if isinstance(ads, str) else "\n\n".join(ads)
        email_intro = (email_text or "").strip()

        body = (
            f"Hi {client_name or 'there'},\n\n"
            f"{email_intro}\n\n"
            "----------------------------\n"
            "CREATIVE PACK\n"
            "----------------------------\n\n"
            f"{ads_block}\n\n"
            "----------------------------\n"
            "Brand summary\n"
            "----------------------------\n"
            f"Website: {website_url or product_url}\n"
            f"Ideal customer: {audience_desc}\n"
            f"Monthly ad budget: {monthly_budget}\n"
            f"Plan: {plan}\n\n"
            "If you want us to launch and manage these ads for you, just reply to this email.\n\n"
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
