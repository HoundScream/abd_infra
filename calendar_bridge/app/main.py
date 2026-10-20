from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import encrypt
from app.db.models import ExternalOrgDomain, JobDefinition, JobRun, OutgoingInviteRecord, ProcessedMessage, User
from app.db.session import get_db, init_db
from app.scheduler import can_run_job, is_job_running, run_job_now, start_scheduler
from app.services.org_domains import normalize_domain
from app.workers.incoming_invites import reparse_message_record
from app.ui_labels import (
    JOB_HELP,
    JOB_LABELS,
    decode_mime_header,
    explain_message_status,
    explain_outgoing_status,
    explain_run_summary,
    format_email_address,
    parse_details_json,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["job_labels"] = JOB_LABELS
templates.env.globals["job_help"] = JOB_HELP
templates.env.globals["explain_run"] = explain_run_summary

app = FastAPI(title="ABD Calendar Bridge", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
_scheduler = None


def _session_token() -> str:
    return hashlib.sha256(f"admin:{settings.admin_password}".encode()).hexdigest()


def require_admin(request: Request) -> None:
    if request.cookies.get("bridge_session") != _session_token():
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.on_event("startup")
def on_startup() -> None:
    global _scheduler
    init_db()
    _scheduler = start_scheduler()
    logger.info("Calendar Bridge API запущен (DRY_RUN=%s)", settings.dry_run)


@app.exception_handler(401)
async def unauthorized_handler(request: Request, _exc: HTTPException):
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse("Unauthorized", status_code=401)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(password: str = Form(...)):
    if password != settings.admin_password:
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("bridge_session", _session_token(), httponly=True, samesite="lax")
    return resp


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    jobs = db.scalars(select(JobDefinition).order_by(JobDefinition.id)).all()
    users = db.scalars(select(User).order_by(User.email)).all()
    job_by_id = {j.id: j for j in jobs}
    user_by_id = {u.id: u.email for u in users}
    recent_runs_raw = db.scalars(select(JobRun).order_by(desc(JobRun.started_at)).limit(20)).all()
    recent_runs = []
    for run in recent_runs_raw:
        job = job_by_id.get(run.job_id)
        slug = job.slug if job else ""
        recent_runs.append(
            {
                "run": run,
                "job": job,
                "user_email": user_by_id.get(run.user_id) if run.user_id else None,
                "explained": explain_run_summary(slug, run.summary, run.details_json),
            }
        )
    job_status = []
    for job in jobs:
        last = db.scalar(
            select(JobRun)
            .where(JobRun.job_id == job.id)
            .order_by(desc(JobRun.started_at))
            .limit(1)
        )
        job_status.append(
            {
                "job": job,
                "running": is_job_running(job.slug),
                "last": last,
            }
        )
    flash = request.query_params.get("flash", "")
    flash_slug = request.query_params.get("job", "")
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "jobs": jobs,
            "job_status": job_status,
            "users": users,
            "recent_runs": recent_runs,
            "settings": settings,
            "flash": flash,
            "flash_slug": flash_slug,
        },
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    users = db.scalars(select(User).order_by(User.email)).all()
    return templates.TemplateResponse(request, "users.html", {"users": users, "settings": settings})


@app.post("/users/add")
def add_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(""),
    imap_password: str = Form(...),
    caldav_password: str = Form(""),
    calendar_name: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request)
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        return RedirectResponse("/users?exists=1", status_code=303)
    user = User(
        email=email,
        display_name=display_name.strip(),
        imap_password_enc=encrypt(settings.secret_key, imap_password.strip()),
        caldav_password_enc=encrypt(settings.secret_key, (caldav_password or imap_password).strip()),
        calendar_name=calendar_name.strip(),
        enabled=True,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/users?added=1", status_code=303)


@app.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    user = db.get(User, user_id)
    if user:
        user.enabled = not user.enabled
        db.commit()
    return RedirectResponse("/users", status_code=303)


@app.get("/organizations", response_class=HTMLResponse)
def organizations_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    domains = db.scalars(
        select(ExternalOrgDomain).order_by(ExternalOrgDomain.domain)
    ).all()
    return templates.TemplateResponse(
        request, "organizations.html", {"domains": domains, "settings": settings}
    )


@app.post("/organizations/add")
def add_organization(
    request: Request,
    domain: str = Form(...),
    org_name: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request)
    normalized = normalize_domain(domain)
    if not normalized or "." not in normalized:
        return RedirectResponse("/organizations?invalid=1", status_code=303)
    if db.scalar(select(ExternalOrgDomain).where(ExternalOrgDomain.domain == normalized)):
        return RedirectResponse("/organizations?exists=1", status_code=303)
    db.add(
        ExternalOrgDomain(
            domain=normalized,
            org_name=org_name.strip(),
            notes=notes.strip(),
            enabled=True,
        )
    )
    db.commit()
    return RedirectResponse("/organizations?added=1", status_code=303)


@app.post("/organizations/{domain_id}/toggle")
def toggle_organization(domain_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = db.get(ExternalOrgDomain, domain_id)
    if row:
        row.enabled = not row.enabled
        db.commit()
    return RedirectResponse("/organizations", status_code=303)


@app.post("/organizations/{domain_id}/delete")
def delete_organization(domain_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = db.get(ExternalOrgDomain, domain_id)
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse("/organizations", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    jobs = db.scalars(select(JobDefinition).order_by(JobDefinition.id)).all()
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs, "settings": settings})


@app.get("/jobs/{slug}/runs", response_class=HTMLResponse)
def job_runs(slug: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    job = db.scalar(select(JobDefinition).where(JobDefinition.slug == slug))
    if not job:
        raise HTTPException(404)
    runs = db.scalars(
        select(JobRun).where(JobRun.job_id == job.id).order_by(desc(JobRun.started_at)).limit(100)
    ).all()
    user_by_id = {u.id: u.email for u in db.scalars(select(User)).all()}
    flash = request.query_params.get("flash", "")
    return templates.TemplateResponse(
        request,
        "job_runs.html",
        {
            "job": job,
            "runs": runs,
            "user_by_id": user_by_id,
            "settings": settings,
            "running": is_job_running(slug),
            "can_run": can_run_job(slug, job.enabled),
            "flash": flash,
        },
    )


@app.post("/jobs/{slug}/run")
def trigger_job(slug: str, request: Request):
    require_admin(request)
    result = run_job_now(slug)
    return RedirectResponse(f"/jobs/{slug}/runs?flash={result}", status_code=303)


@app.get("/messages", response_class=HTMLResponse)
def messages_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = db.scalars(
        select(ProcessedMessage).order_by(desc(ProcessedMessage.processed_at)).limit(200)
    ).all()
    user_map = {u.id: u.email for u in db.scalars(select(User)).all()}
    job_slug = "incoming_invites"
    rows_view = []
    for row in rows:
        details = parse_details_json(row.details_json)
        rows_view.append(
            {
                "id": row.id,
                "when": row.processed_at.strftime("%d.%m.%Y %H:%M") if row.processed_at else "—",
                "user_email": user_map.get(row.user_id, str(row.user_id)),
                "subject": decode_mime_header(row.subject),
                "sender": format_email_address(row.sender),
                "job_slug": job_slug,
                "job_title": JOB_LABELS[job_slug],
                "explanation": explain_message_status(
                    row.status,
                    row.details_json,
                    dry_run=settings.dry_run,
                    create_events_enabled=settings.create_events_enabled,
                ),
                "has_details": bool(details.get("uid") or details.get("summary")),
            }
        )
    return templates.TemplateResponse(
        request,
        "messages.html",
        {"rows": rows_view, "settings": settings},
    )


@app.get("/messages/{message_id}", response_class=HTMLResponse)
def message_detail(message_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = db.get(ProcessedMessage, message_id)
    if not row:
        raise HTTPException(404)
    user = db.get(User, row.user_id)
    details = parse_details_json(row.details_json)
    event = details if details.get("uid") or details.get("summary") else None
    incomplete = event and not event.get("dtstart")
    flash = request.query_params.get("flash", "")
    return templates.TemplateResponse(
        request,
        "message_detail.html",
        {
            "row": row,
            "user_email": user.email if user else str(row.user_id),
            "subject": decode_mime_header(row.subject),
            "sender": format_email_address(row.sender),
            "when": row.processed_at.strftime("%d.%m.%Y %H:%M:%S") if row.processed_at else "—",
            "explanation": explain_message_status(
                row.status,
                row.details_json,
                dry_run=settings.dry_run,
                create_events_enabled=settings.create_events_enabled,
            ),
            "event": event,
            "incomplete": incomplete,
            "flash": flash,
            "details_pretty": json.dumps(details, ensure_ascii=False, indent=2),
            "settings": settings,
        },
    )


@app.post("/messages/{message_id}/reparse")
def message_reparse(message_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        reparse_message_record(db, settings, message_id)
        return RedirectResponse(f"/messages/{message_id}?flash=reparsed", status_code=303)
    except ValueError as exc:
        return RedirectResponse(f"/messages/{message_id}?flash=error&msg={exc}", status_code=303)


@app.get("/outgoing", response_class=HTMLResponse)
def outgoing_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = db.scalars(
        select(OutgoingInviteRecord).order_by(desc(OutgoingInviteRecord.sent_at)).limit(200)
    ).all()
    user_map = {u.id: u.email for u in db.scalars(select(User)).all()}
    rows_view = []
    for row in rows:
        details = parse_details_json(row.details_json)
        event = details.get("event") or {}
        rows_view.append(
            {
                "id": row.id,
                "when": row.sent_at.strftime("%d.%m.%Y %H:%M") if row.sent_at else "—",
                "user_email": user_map.get(row.user_id, str(row.user_id)),
                "recipient": row.recipient_email,
                "event_summary": event.get("summary") or row.event_uid,
                "explanation": explain_outgoing_status(
                    row.status,
                    row.details_json,
                    dry_run=settings.dry_run,
                    outgoing_send_enabled=settings.outgoing_send_enabled,
                ),
            }
        )
    return templates.TemplateResponse(
        request,
        "outgoing.html",
        {"rows": rows_view, "settings": settings},
    )


@app.get("/outgoing/{record_id}", response_class=HTMLResponse)
def outgoing_detail(record_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = db.get(OutgoingInviteRecord, record_id)
    if not row:
        raise HTTPException(404)
    user = db.get(User, row.user_id)
    details = parse_details_json(row.details_json)
    event = details.get("event")
    email_preview = details if details.get("to") else None
    return templates.TemplateResponse(
        request,
        "outgoing_detail.html",
        {
            "row": row,
            "user_email": user.email if user else str(row.user_id),
            "when": row.sent_at.strftime("%d.%m.%Y %H:%M:%S") if row.sent_at else "—",
            "explanation": explain_outgoing_status(
                row.status,
                row.details_json,
                dry_run=settings.dry_run,
                outgoing_send_enabled=settings.outgoing_send_enabled,
            ),
            "email_preview": email_preview,
            "event": event,
            "details_pretty": json.dumps(details, ensure_ascii=False, indent=2),
            "settings": settings,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "dry_run": settings.dry_run}
