from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, EmailStr, field_validator, ValidationError
from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(
    title="SolProd Contact API",
    description="API for handling contact forms and reviews",
    version="1.0.0"
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Преобразуем ошибки валидации Pydantic в читаемый формат"""
    errors = exc.errors()

    error_messages = []
    for error in errors:
        field = error.get('loc', [])[-1] if error.get('loc') else 'field'
        msg = error.get('msg', 'Invalid value')

        if 'value_error.email' in str(error.get('type', '')):
            msg = f"Invalid email format"
        elif 'value_error' in str(error.get('type', '')):
            msg = f"{field.capitalize()}: {msg}"
        
        error_messages.append(msg)
    
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "detail": ". ".join(error_messages)
        }
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

    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Name cannot be empty')
        if len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip()

    @field_validator('phone')
    @classmethod
    def phone_must_be_valid(cls, v: str) -> str:
        phone_pattern = re.compile(r'^[\d\s\+\-\(\)]+$')
        if not phone_pattern.match(v):
            raise ValueError('Invalid phone number format')
        if len(re.sub(r'[\s\+\-\(\)]', '', v)) < 10:
            raise ValueError('Phone number must contain at least 10 digits')
        return v.strip()

    @field_validator('comment')
    @classmethod
    def comment_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Comment cannot be empty')
        if len(v.strip()) < 10:
            raise ValueError('Comment must be at least 10 characters long')
        return v.strip()


class ReviewRequest(BaseModel):
    name: str
    phone: str
    rating: int
    comment: str

    @field_validator('name')
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Name cannot be empty')
        if len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip()

    @field_validator('phone')
    @classmethod
    def phone_must_be_valid(cls, v: str) -> str:
        phone_pattern = re.compile(r'^[\d\s\+\-\(\)]+$')
        if not phone_pattern.match(v):
            raise ValueError('Invalid phone number format')
        if len(re.sub(r'[\s\+\-\(\)]', '', v)) < 10:
            raise ValueError('Phone number must contain at least 10 digits')
        return v.strip()

    @field_validator('rating')
    @classmethod
    def rating_must_be_valid(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError('Rating must be between 1 and 5')
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
            message["Reply-To"] = reply_to

        part1 = MIMEText(text_content, "plain")
        part2 = MIMEText(html_content, "html")
        message.attach(part1)
        message.attach(part2)

        logger.info(f"📤 Connecting to SMTP server: {smtp_server}:{smtp_port}")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            logger.info("🔐 Logging in to SMTP server")
            server.login(smtp_username, smtp_password)
            logger.info("✉️ Sending email")
            server.send_message(message)
        
        logger.info(f"✅ Email successfully sent to: {to_email}")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending email: {str(e)}", exc_info=True)
        raise


@app.post("/api/contact/discuss")
@limiter.limit("5/15minutes")
async def discuss_project(request: Request, data: DiscussProjectRequest):
    """Обработка формы обсуждения проекта"""
    logger.info(f"📝 New discuss project request from: {data.name} ({data.email})")
    
    try:

        admin_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 5px 5px; }}
                .field {{ margin-bottom: 20px; }}
                .field-label {{ font-weight: bold; color: #667eea; margin-bottom: 5px; }}
                .field-value {{ background: white; padding: 10px; border-radius: 3px; border-left: 3px solid #667eea; }}
                .footer {{ text-align: center; margin-top: 20px; color: #888; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🎯 New Project Discussion Request</h2>
                </div>
                <div class="content">
                    <div class="field">
                        <div class="field-label">👤 Name:</div>
                        <div class="field-value">{data.name}</div>
                    </div>
                    <div class="field">
                        <div class="field-label">📧 Email:</div>
                        <div class="field-value"><a href="mailto:{data.email}">{data.email}</a></div>
                    </div>
                    <div class="field">
                        <div class="field-label">📱 Phone:</div>
                        <div class="field-value"><a href="tel:{data.phone}">{data.phone}</a></div>
                    </div>
                    {f'''<div class="field">
                        <div class="field-label">🏷️ Product Name:</div>
                        <div class="field-value">{data.productName}</div>
                    </div>''' if data.productName else ''}
                    <div class="field">
                        <div class="field-label">💬 Comment:</div>
                        <div class="field-value">{data.comment.replace(chr(10), '<br>')}</div>
                    </div>
                    <div class="footer">
                        <p>Received at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        admin_text = f"""
New Project Discussion Request

Name: {data.name}
Email: {data.email}
Phone: {data.phone}
{f'Product Name: {data.productName}' if data.productName else ''}

Comment:
{data.comment}

Received at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """

        recipient_email = os.getenv("RECIPIENT_EMAIL", "solutions.production.manager@gmail.com")
        logger.info(f"📨 Sending admin email to: {recipient_email}")
        send_email(
            to_email=recipient_email,
            subject=f"🎯 New Project Discussion - {data.name}",
            html_content=admin_html,
            text_content=admin_text,
            reply_to=data.email
        )



        logger.info(f"✅ Successfully processed discuss project request from: {data.name}")
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Thank you! Your message has been sent successfully."
            }
        )

    except Exception as e:
        logger.error(f"❌ Error in discuss_project: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "detail": "Sorry, there was an error sending your message. Please try again."
            }
        )


@app.post("/api/contact/review")
@limiter.limit("5/15minutes")
async def submit_review(request: Request, data: ReviewRequest):
    """Обработка формы отзыва"""
    logger.info(f"⭐ New review from: {data.name} (Rating: {data.rating}/5)")
    
    try:
        stars = '⭐' * data.rating + '☆' * (5 - data.rating)

        admin_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 5px 5px; }}
                .field {{ margin-bottom: 20px; }}
                .field-label {{ font-weight: bold; color: #f5576c; margin-bottom: 5px; }}
                .field-value {{ background: white; padding: 10px; border-radius: 3px; border-left: 3px solid #f5576c; }}
                .rating {{ font-size: 24px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #888; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>⭐ New Review Received</h2>
                </div>
                <div class="content">
                    <div class="field">
                        <div class="field-label">👤 Name:</div>
                        <div class="field-value">{data.name}</div>
                    </div>
                    <div class="field">
                        <div class="field-label">📱 Phone:</div>
                        <div class="field-value"><a href="tel:{data.phone}">{data.phone}</a></div>
                    </div>
                    <div class="field">
                        <div class="field-label">⭐ Rating:</div>
                        <div class="field-value rating">{stars} ({data.rating}/5)</div>
                    </div>
                    <div class="field">
                        <div class="field-label">💬 Review:</div>
                        <div class="field-value">{data.comment.replace(chr(10), '<br>')}</div>
                    </div>
                    <div class="footer">
                        <p>Received at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        recipient_email = os.getenv("RECIPIENT_EMAIL", "solutions.production.manager@gmail.com")
        logger.info(f"📨 Sending review email to: {recipient_email}")
        send_email(
            to_email=recipient_email,
            subject=f"⭐ New Review ({data.rating}/5) - {data.name}",
            html_content=admin_html,
            text_content=f"New Review from {data.name}\nRating: {data.rating}/5\n\n{data.comment}"
        )

        logger.info(f"✅ Successfully processed review from: {data.name}")
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Thank you for your review!"
            }
        )

    except Exception as e:
        logger.error(f"❌ Error in submit_review: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "detail": "Sorry, there was an error submitting your review. Please try again."
            }
        )


@app.get("/api/health")
async def health_check():
    """Проверка работоспособности API"""
    logger.info("🏥 Health check requested")
    return {
        "status": "OK",
        "timestamp": datetime.now().isoformat(),
        "service": "SolProd Contact API",
        "version": "1.0.0",
        "email_configured": bool(os.getenv("EMAIL_USER"))
    }


@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "message": "SolProd Contact API",
        "version": "1.0.0",
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