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
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os
import re
import logging

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"🔵 {request.method} {request.url.path} from {request.client.host}")
    try:
        response = await call_next(request)
        logger.info(f"✅ Response: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}", exc_info=True)
        raise



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

    @field_validator('comment')
    @classmethod
    def comment_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Comment cannot be empty')
        if len(v.strip()) < 10:
            raise ValueError('Comment must be at least 10 characters long')
        return v.strip()


def send_email(to_email: str, subject: str, html_content: str, text_content: str, reply_to: Optional[str] = None):
    """Отправка email через SMTP"""
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = os.getenv("EMAIL_USER")
        smtp_password = os.getenv("EMAIL_PASSWORD")
        
        logger.info(f"📧 Preparing to send email to: {to_email}")
        
        if not smtp_username or not smtp_password:
            logger.error("❌ Email credentials not configured")
            raise ValueError("Email credentials not configured")

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"SolProd Website <{smtp_username}>"
        message["To"] = to_email
        
        if reply_to:
            message.reply_to = reply_to

        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        
        logger.info(f"✅ Email sent! Status: {response.status_code}")

    except Exception as e:
        logger.error(f"❌ Error sending email: {str(e)}", exc_info=True)
        raise


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
Product: {data.productName or '-'}

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
        "email_configured": bool(os.getenv("SENDGRID_API_KEY"))
    }

@app.get("/")
async def root():
    return {
        "service": "SolProd Contact API",
        "status": "running",
        "endpoints": {
            "discuss_project": "/api/contact/discuss",
            "submit_review": "/api/contact/review",
            "health": "/api/health",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Starting server on port {port}")
    logger.info(f"📧 Email service configured for: {os.getenv('EMAIL_USER', 'Not configured')}")
    logger.info(f"🌐 CORS enabled for all origins")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )