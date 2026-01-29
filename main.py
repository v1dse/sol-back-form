from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
import smtplib
import os
import re
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("main")

# -------------------- ENV --------------------
load_dotenv()

# -------------------- APP --------------------
app = FastAPI(
    title="SolProd Contact API",
    version="1.0.0"
)

# -------------------- RATE LIMIT --------------------
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- VALIDATION HANDLER --------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    errors = []
    for e in exc.errors():
        field = e.get("loc", ["field"])[-1]
        msg = e.get("msg", "Invalid value")
        errors.append(f"{field}: {msg}")
    return JSONResponse(
        status_code=422,
        content={"success": False, "detail": ". ".join(errors)}
    )

# -------------------- REQUEST LOGGER --------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"🔵 {request.method} {request.url.path} from {request.client.host}")
    response = await call_next(request)
    logger.info(f"✅ Response: {response.status_code}")
    return response

# -------------------- MODELS --------------------
class DiscussProjectRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    productName: Optional[str] = None
    comment: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str):
        if not re.match(r"^[\d\s\+\-\(\)]+$", v):
            raise ValueError("Invalid phone format")
        if len(re.sub(r"\D", "", v)) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return v.strip()

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, v: str):
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Comment must be at least 10 characters")
        return v

# -------------------- EMAIL SENDER --------------------
def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    reply_to: Optional[str] = None
):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    email_user = os.getenv("EMAIL_USER")
    email_password = os.getenv("EMAIL_PASSWORD")

    if not email_user or not email_password:
        logger.error("❌ Email credentials missing")
        return

    try:
        logger.info(f"📧 Sending email to {to_email}")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"SolProd Website <{email_user}>"
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(email_user, email_password)
            server.send_message(msg)

        logger.info("✅ Email sent successfully")

    except Exception as e:
        logger.error(f"❌ Email error: {e}", exc_info=True)

# -------------------- ENDPOINTS --------------------
@app.post("/api/contact/discuss")
@limiter.limit("5/15minutes")
async def discuss_project(
    request: Request,
    data: DiscussProjectRequest,
    background_tasks: BackgroundTasks
):
    logger.info(f"📝 New request from {data.name}")

    recipient = os.getenv(
        "RECIPIENT_EMAIL",
        "solutions.production.manager@gmail.com"
    )

    html = f"""
    <h2>New Project Discussion</h2>
    <p><b>Name:</b> {data.name}</p>
    <p><b>Email:</b> {data.email}</p>
    <p><b>Phone:</b> {data.phone}</p>
    <p><b>Product:</b> {data.productName or '-'}</p>
    <p><b>Comment:</b><br>{data.comment}</p>
    <p><small>{datetime.now()}</small></p>
    """

    text = f"""
Name: {data.name}
Email: {data.email}
Phone: {data.phone}
Product: {data.productName}

Comment:
{data.comment}
"""

    background_tasks.add_task(
        send_email,
        recipient,
        f"🎯 New Project Discussion - {data.name}",
        html,
        text,
        data.email
    )

    return {
        "success": True,
        "message": "Thank you! Your message has been sent."
    }

@app.get("/api/health")
async def health():
    return {
        "status": "OK",
        "timestamp": datetime.utcnow().isoformat(),
        "email_configured": bool(os.getenv("EMAIL_USER"))
    }

@app.get("/")
async def root():
    return {
        "service": "SolProd Contact API",
        "status": "running",
        "docs": "/docs"
    }
