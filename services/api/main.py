from fastapi import FastAPI, HTTPException, Body, Request, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import pathlib, datetime, json, csv, os
from llm import generate_ad_copy, generate_email, generate_audit
from db import init_db, insert_lead, list_leads
from jobqueue import dispatch_task

app = FastAPI(title="AI Agency API", version="1.0.0")
init_db()

class Lead(BaseModel):
    name: str
    email: str
    brand: Optional[str]=""
    niche: Optional[str]=""
    website: Optional[str]=""

class CampaignRequest(BaseModel):
    objective: Literal["leads","sales","retention"] = "leads"
    channels: List[Literal["email","ads","sms","seo","ugc"]] = ["email","ads"]
    brand: str = "Brand"
    product: str = "Product"
    audience: str = "broad"

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
    dispatch_task("tasks.generate_full_campaign", payload)
    return {"queued": True, "message": "Campaign generation started."}

@app.post("/copy/ad")
def ad_copy(brand: str, product: str, audience: str="broad"):
    prompt = f"Write 5 direct-response ad variants for {brand}'s {product} to {audience}."
    return {"copy": generate_ad_copy(prompt)}

@app.post("/copy/email")
def copy_email(brand: str, product: str, angle: str = "", name: str = "Alex", url: str = "https://astrobottles.com"):
    prompt = f"{brand} {product}: {angle} | Recipient: {name} | URL: {url}"
    return {"email": generate_email(prompt)}

    out_dir = pathlib.Path("/app/out")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    fp = out_dir / f"email-{ts}.txt"
    fp.write_text(email_text, encoding="utf-8")

    return {"email": email_text, "saved_to": str(fp)}

@app.post("/audit")
def audit(website: str):
    return {"audit": generate_audit(website)}

from fastapi import Body

class MiniCampaign(BaseModel):
    brand: str
    product: str
    audience: Optional[str] = ""
    angle: Optional[str] = ""
    name: Optional[str] = "Alex"
    url: Optional[str] = "https://example.com"
    email: Optional[str] = None  # optional so tests don't crash
@app.post("/campaigns/mini")
def campaigns_mini(payload: MiniCampaign = Body(...)):
    ad_prompt = f"{payload.brand} {payload.product} for {payload.audience}: {payload.angle}".strip()
    email_prompt = f"{payload.brand} {payload.product}: {payload.angle} | Recipient: {payload.name} | URL: {payload.url}".strip()

    ads = generate_ad_copy(ad_prompt)
    email_text = generate_email(email_prompt)

    # Save to disk
    import pathlib, datetime, json
    out_dir = pathlib.Path("/app/out"); out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"campaign-{ts}.json"
    out_file.write_text(json.dumps({"ads": ads, "email": email_text}, indent=2), encoding="utf-8")

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
        import csv
        log_path = out_dir / "history.csv"
        first_write = not log_path.exists()
        with log_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if first_write:
                w.writerow(["timestamp","brand","product","audience","angle","name","url","emailed_to","saved_to","email_error"])
            w.writerow([
                datetime.datetime.utcnow().isoformat(),
                payload.brand, payload.product, payload.audience, payload.angle, payload.name, payload.url,
                result.get("emailed_to",""), result.get("saved_to",""), result.get("email_error","")
            ])
    except Exception:
        pass

    return result
def _find_field(fields, label, default=None):
    """Helper to get a field value from Tally by its label."""
    for f in fields:
        if f.get("label") == label:
            return f.get("value", default)
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
    fields = data.get("fields", [])

    print("Tally field labels:", [f.get("label") for f in fields])

# if not fields:
#     raise HTTPException(status_code=400, detail="No fields found in Tally payload")


    # === map your exact labels ===
    brand_name     = (_find_field(fields, "Brand Name", "") or "").strip()
    website_url    = _find_field(fields, "Website URL", "")
    social_links   = _find_field(fields, "Social Media Links (optional)", "")
    main_product   = (_find_field(fields, "Main Product / Service", "") or "").strip()
    product_url    = _find_field(fields, "Product/Service URL", "")
    ideal_customer = _find_field(fields, "Describe your ideal customer", "")
    audience_age   = _find_field(fields, "Audience Age Range", "")
    main_benefit   = _find_field(fields, "Main benefit or value proposition", "")
    competitors    = _find_field(fields, "Top Competitors (optional)", "")
    ad_tone        = _find_field(fields, "Ad tone/style you want", "")
    monthly_budget = _find_field(fields, "Monthly Ad Budget", "")
    lifestyle_flag = _find_field(fields, "Do you want AI-generated lifestyle images?", "")
    video_flag     = _find_field(fields, "Do you want AI-generated video ads?", "")
    additional_notes = _find_field(fields, "Additional Notes (optional)", "")
    client_name    = (_find_field(fields, "Your Name", "") or "").strip()
    client_email   = (_find_field(fields, "Business Email", "") or "").strip()
    package_email  = (_find_field(fields, "Where should we send your weekly campaign package?", "") or "").strip()
    phone          = _find_field(fields, "Phone (optional)", "")

    # uploads will come as lists/objects from Tally
    product_images = _find_field(fields, "Upload Product Images", []) or []
    extra_images   = _find_field(fields, "Additional Images (optional)", []) or []

# if not brand_name or not main_product or not client_email:
#     raise HTTPException(
#         status_code=400,
#         detail="Missing required fields: Brand Name, Main Product / Service, or Business Email."
#     )

    audience_desc = ideal_customer or f"{audience_age} audience"
    angle = main_benefit or "Scale sales with better ads and creative"

    ad_prompt = (
        f"Brand: {brand_name}\n"
        f"Product/Service: {main_product}\n"
        f"Ideal customer: {audience_desc}\n"
        f"Main benefit: {angle}\n"
        f"Tone/style: {ad_tone}\n"
        f"Budget: {monthly_budget}\n"
        f"Notes: {additional_notes}\n"
    )

    email_prompt = (
        f"Write a marketing email for {brand_name} promoting {main_product}.\n"
        f"Website: {website_url or product_url}\n"
        f"Ideal customer: {audience_desc}\n"
        f"Main benefit: {angle}\n"
        f"Use the recipient name '{client_name or 'there'}'.\n"
        f"Include a clear CTA to visit {website_url or product_url}.\n"
        f"Tone: {ad_tone or 'high-converting but natural'}.\n"
    )

    # call your existing AI
    try:
        ads = generate_ad_copy(ad_prompt)
        email_text = generate_email(email_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")

    target_email = package_email or client_email

    # save under /app/out/clients/<brand>/
    safe_brand = "".join(c for c in brand_name.lower().replace(" ", "-") if c.isalnum() or c in ("-", "_"))
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
        "competitors": competitors,
        "ad_tone": ad_tone,
        "monthly_budget": monthly_budget,
        "lifestyle_images_requested": lifestyle_flag,
        "video_ads_requested": video_flag,
        "additional_notes": additional_notes,
        "client_name": client_name,
        "client_email": client_email,
        "package_email": package_email,
        "phone": phone,
        "product_images": product_images,
        "extra_images": extra_images,
        "generated_ads": ads,
        "generated_email": email_text,
        "created_at": ts,
    }
    out_file.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    result = {"saved_to": str(out_file), "brand": brand_name, "sent_to": target_email}

    # email the package
    try:
        from mailer import send_campaign

        subject = f"{brand_name}: Your ALX Scales Campaign Package"
        body = (
            f"Hi {client_name or 'there'},\n\n"
            f"Here is your latest campaign package from ALX Scales.\n\n"
            f"=== Ads ===\n- " + "\n- ".join(ads) +
            "\n\n=== Email ===\n" + email_text +
            "\n\n=== Notes ===\n"
            f"Website: {website_url or product_url}\n"
            f"Ideal customer: {audience_desc}\n"
            f"Monthly Ad Budget: {monthly_budget}\n"
            f"Requested lifestyle images: {lifestyle_flag}\n"
            f"Requested video ads: {video_flag}\n"
            "\nIf you want us to launch and manage these ads for you, just reply to this email.\n"
            "\n—\nALX Scales\nAI Systems That Scale Brands\nalxscales.ai@gmail.com"
        )
        if target_email:
            send_campaign(target_email, subject, body)
            result["emailed"] = True
        else:
            result["emailed"] = False
        except Exception as e:
    result["emailed"] = False
    result["email_error"] = f"{type(e).__name__}: {e}"
    print("EMAIL ERROR in tally_intake:", result["email_error"])

    # log CSV
    log_path = client_dir / "submissions.csv"
    first_write = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if first_write:
            w.writerow([
                "timestamp","brand_name","main_product","client_name","client_email",
                "package_email","monthly_budget","saved_to","emailed","email_error"
            ])
        w.writerow([
            ts, brand_name, main_product, client_name, client_email,
            target_email, monthly_budget, str(out_file), result.get("emailed"), result.get("email_error","")
        ])

    return result
