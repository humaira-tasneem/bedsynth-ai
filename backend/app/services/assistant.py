"""Safe natural-language interpretation for the existing generation workflow."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import secrets
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bed, Department, Hospital, Workspace
from app.schemas import (
    AssistantChatRequest,
    AssistantConfigFields,
    AssistantConfigValidationRequest,
    AssistantGenerationConfig,
    AssistantHistoryMessage,
    AssistantFieldError,
    GeminiGenerationProposal,
    GenerationConfig,
)

logger = logging.getLogger(__name__)
MAX_WORKSPACE_HOSPITALS = 100
MAX_HOSPITAL_DEPARTMENTS = 100
MAX_CONVERSATION_CONTEXT = 8000
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_USER_AGENT = "BedSynth-AI/1.0"
PROVIDER_TIMEOUT_SECONDS = 15
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:mrn|medical record (?:number|#)|patient (?:name|id|identifier)|date of birth|dob|ssn|social security)\b", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){10,15}(?!\d)"),
    re.compile(r"\b(?:mr|mrs|ms|miss)\.\s+[A-Z][a-z]+\b"),
    re.compile(r"\b(?:diagnos(?:is|ed)|symptoms?|treatment|medications?|prescriptions?|allerg(?:y|ies)|lab(?:oratory)? results?|clinical notes?|medical history|vital signs?)\b", re.IGNORECASE),
    re.compile(r"\b(?:patient|person|individual)\s+(?:has|with|was diagnosed with|is taking|takes|received)\s+[A-Za-z-]+\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|µg|ml|millilit(?:er|re)s?|dosage)\b", re.IGNORECASE),
    re.compile(r"\b(?:blood pressure|heart rate|oxygen saturation|spo2|body temperature|blood glucose|hemoglobin|creatinine|biopsy|radiology report)\b", re.IGNORECASE),
)


def gemini_key_is_configured() -> bool:
    """Return key presence only; never expose the credential value."""
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def groq_key_is_configured() -> bool:
    """Return Groq key presence only; never expose the credential value."""
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def _name_key(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _parse_local_date_range(text: str) -> tuple[str, str] | None:
    """Parse explicit ISO or English month/day ranges without guessing dates."""
    separator = re.compile(r"\s*(?:to|through|until|[-–—])\s*", re.IGNORECASE)
    iso_dates = list(re.finditer(r"\b(?P<date>\d{4}-\d{2}-\d{2})\b", text))
    for first, second in zip(iso_dates, iso_dates[1:]):
        if not separator.fullmatch(text[first.end():second.start()]):
            continue
        try:
            start = date.fromisoformat(first.group("date"))
            end = date.fromisoformat(second.group("date"))
            return start.isoformat(), end.isoformat()
        except ValueError:
            return None

    months = (
        "January|February|March|April|May|June|July|August|September|October|November|December|"
        "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    )
    month_dates = list(re.finditer(
        rf"\b(?P<month>{months})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{{4}}))?\b",
        text,
        re.IGNORECASE,
    ))
    month_numbers = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
        "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    for first, second in zip(month_dates, month_dates[1:]):
        if not separator.fullmatch(text[first.end():second.start()]):
            continue
        first_year = first.group("year")
        second_year = second.group("year")
        if first_year is None and second_year is None:
            return None
        try:
            year = int(first_year or second_year)
            start = date(int(first_year or year), month_numbers[first.group("month").casefold().rstrip(".")], int(first.group("day")))
            end = date(int(second_year or year), month_numbers[second.group("month").casefold().rstrip(".")], int(second.group("day")))
            return start.isoformat(), end.isoformat()
        except ValueError:
            return None
    return None


def _local_proposal_from_explicit_values(
    user_messages: list[str],
    hospitals: list[dict[str, str]],
    departments: list[dict[str, str]],
) -> GeminiGenerationProposal:
    """Extract only explicit values for degraded operation when Gemini is down."""
    hospital_name = None
    for turn in reversed(user_messages):
        matches = [
            row for row in hospitals
            if _name_key(row["name"]) in _name_key(turn) or _name_key(row["code"]) in _name_key(turn)
        ]
        if len(matches) == 1:
            hospital_name = matches[0]["name"]
            break
        if len(matches) > 1:
            break

    date_range = None
    for turn in user_messages:
        parsed_range = _parse_local_date_range(turn)
        if parsed_range:
            date_range = parsed_range

    admissions = None
    for turn in user_messages:
        admission_matches = list(re.finditer(
            r"\b(?:(?:target|total)\s+)?(?P<count>\d{1,5})\s+(?:(?:synthetic|total)\s+)?admissions?\b|"
            r"\b(?P<after>\d{1,5})\s+target\s+admissions?\b|\badmissions?\s+(?:of|:)?\s*(?P<end>\d{1,5})\b",
            turn,
            re.IGNORECASE,
        ))
        if admission_matches:
            last = admission_matches[-1]
            admissions = int(last.group("count") or last.group("after") or last.group("end"))

    occupancy = None
    occupancy_patterns = (
        re.compile(r"\b(?:target\s+)?occupancy(?:\s+(?:target|rate))?\s*(?:of|at|is|:)?\s*(?P<value>\d{1,3})\s*(?:%|percent)(?![A-Za-z])", re.IGNORECASE),
        re.compile(r"\b(?P<value>\d{1,3})\s*(?:%|percent)(?![A-Za-z])\s*(?:target\s+)?occupancy\b", re.IGNORECASE),
    )
    for turn in user_messages:
        for pattern in occupancy_patterns:
            matches = list(pattern.finditer(turn))
            if matches:
                occupancy = int(matches[-1].group("value"))

    seed = None
    for turn in user_messages:
        seeds = list(re.finditer(r"\bseed\s*(?:is|:|=|to)?\s*(\d{1,10})\b", turn, re.IGNORECASE))
        if seeds:
            seed = int(seeds[-1].group(1))

    selected_department_names = None
    all_departments_pattern = re.compile(
        r"\b(?:all|every)\s+(?:(?:the|active)\s+)*(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?(?:(?:the|active)\s+)*departments?\b",
        re.IGNORECASE,
    )
    for turn in user_messages:
        if all_departments_pattern.search(turn):
            selected_department_names = [row["name"] for row in departments]
            continue
        found = [
            row["name"] for row in departments
            if _name_key(row["name"]) in _name_key(turn) or _name_key(row["code"]) in _name_key(turn)
        ]
        if found:
            selected_department_names = list(dict.fromkeys(found))
        elif re.search(r"\bdepartments?\b", turn, re.IGNORECASE):
            # Fail closed on an explicit but unrecognized department request;
            # downstream validation will return a field error instead of using all.
            selected_department_names = []

    return GeminiGenerationProposal(
        assistant_message=(
            "Gemini is temporarily unavailable. I parsed only explicit details locally; "
            "review the proposal carefully before continuing."
        ),
        hospital_name=hospital_name,
        start_date=date_range[0] if date_range else None,
        end_date=date_range[1] if date_range else None,
        target_admissions=admissions,
        target_occupancy_pct=occupancy,
        seed=seed,
        department_names=selected_department_names,
    )


def _contains_likely_patient_information(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_TEXT_PATTERNS)


def _workspace_hospitals(db: Session, workspace_id: int, *, include_unpublished: bool = False) -> list[Hospital]:
    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    filters = [Hospital.workspace_id == workspace_id, Hospital.is_archived.is_(False)]
    if not include_unpublished:
        filters.append(Hospital.available_to_users.is_(True))
    total = db.scalar(select(func.count(Hospital.id)).where(*filters)) or 0
    if total > MAX_WORKSPACE_HOSPITALS:
        raise HTTPException(status_code=422, detail="This workspace has too many active hospitals for the bounded assistant catalog. Use Hospital Studio or the standard generator.")
    return list(db.scalars(select(Hospital).where(*filters).order_by(Hospital.name, Hospital.id)).all())


def _catalog(hospitals: list[Hospital]) -> list[dict[str, str]]:
    # IDs are deliberately excluded from model context; the server resolves names/codes.
    return [{"name": hospital.name, "code": hospital.code} for hospital in hospitals]


def _bounded_history(history: list[AssistantHistoryMessage], current_message: str) -> list[dict[str, str]]:
    clean = [{"role": item.role, "content": item.content.strip()} for item in history[-10:] if item.content.strip()]
    used = len(current_message)
    bounded: list[dict[str, str]] = []
    for item in reversed(clean):
        remaining = MAX_CONVERSATION_CONTEXT - used
        if remaining <= 0:
            break
        content = item["content"][-remaining:]
        bounded.append({"role": item["role"], "content": content})
        used += len(content)
    return list(reversed(bounded))


def _parse_gemini_response(response) -> GeminiGenerationProposal:
    try:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, GeminiGenerationProposal):
            return parsed
        if isinstance(parsed, dict):
            return GeminiGenerationProposal.model_validate(parsed)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini returned no structured content.")
        return GeminiGenerationProposal.model_validate_json(text)
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail={
            "category": "malformed_response",
            "message": "Gemini returned an invalid configuration response. Please rephrase the request and try again.",
        }) from exc


def _gemini_proposal_json_schema() -> dict:
    """Return the small JSON Schema subset accepted by Gemini structured output.

    Keep this separate from Pydantic's full validation schema. The SDK's
    `response_schema` conversion maps Pydantic `additionalProperties` to a
    protobuf `additional_properties` field that Gemini rejects. This is raw
    JSON Schema for `response_json_schema`; server-side validation remains in
    `GeminiGenerationProposal` and the generation configuration models.
    Optional proposal fields may be omitted; Pydantic applies their `None`
    defaults after parsing.
    """
    return {
        "type": "object",
        "properties": {
            "assistant_message": {"type": "string"},
            "hospital_name": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "target_admissions": {"type": "integer"},
            "target_occupancy_pct": {"type": "integer"},
            "seed": {"type": "integer"},
            "department_names": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["assistant_message"],
    }


def _provider_error_status_code(exc: Exception) -> int | None:
    """Read the numeric provider status without formatting the SDK exception."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _is_provider_deadline_error(exc: Exception) -> bool:
    """Detect provider-side deadlines (as opposed to only local timeouts)."""
    status = str(getattr(exc, "status", "") or "").casefold()
    return _provider_error_status_code(exc) == 504 or "deadline_exceeded" in status


def _provider_retry_after_seconds(exc: Exception) -> int | None:
    """Extract a bounded retry delay without exposing provider error details."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None)
    raw_header = headers.get("retry-after") if headers is not None else None
    if raw_header is not None:
        try:
            return max(1, min(86_400, math.ceil(float(raw_header))))
        except (TypeError, ValueError, OverflowError):
            try:
                retry_at = parsedate_to_datetime(str(raw_header))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
                return max(1, min(86_400, math.ceil(seconds)))
            except (TypeError, ValueError, OverflowError):
                pass

    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        error_body = details.get("error")
        if isinstance(error_body, dict):
            details = error_body.get("details", [])
        else:
            details = details.get("details", [])
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("RetryInfo"):
                continue
            delay = detail.get("retryDelay")
            if isinstance(delay, str):
                match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", delay)
                if match:
                    return max(1, min(86_400, math.ceil(float(match.group(1)))))

    # Some SDK versions surface retry hints only in the provider message.
    message = str(getattr(exc, "message", "") or "")
    match = re.search(r"\bretry\s+(?:after|in)\s+(\d+(?:\.\d+)?)\s*(?:seconds?|s)\b", message, re.IGNORECASE)
    if match:
        return max(1, min(86_400, math.ceil(float(match.group(1)))))
    return None


def _gemini_error_response(exc: Exception) -> HTTPException:
    """Map provider errors to safe categories without logging provider content."""
    code = _provider_error_status_code(exc)
    provider_status = getattr(exc, "status", None)
    status_text = str(provider_status or "").casefold()
    provider_message = str(getattr(exc, "message", "") or "").casefold()
    error_name = type(exc).__name__.casefold()
    if code == 429 or "resourceexhausted" in error_name or "resource_exhausted" in status_text:
        category, http_status = "quota", 429
        friendly = "Gemini is temporarily unavailable because the request quota or rate limit was reached. Try again later."
    elif code == 404 or "not_found" in status_text or "not found" in str(getattr(exc, "message", "")).casefold():
        category, http_status = "model_not_found", 502
        friendly = "The configured Gemini model could not be found. Contact the administrator to review backend model configuration."
    elif (code in {401, 403} or "unauthenticated" in status_text or "permission_denied" in status_text
          or "invalid api key" in provider_message or "api key is not valid" in provider_message
          or "api key not valid" in provider_message):
        category, http_status = "authentication", 502
        friendly = "Gemini authentication failed. Check the backend API key configuration and access."
    elif _is_provider_deadline_error(exc) or "timeout" in error_name or "deadline" in error_name:
        category, http_status = "timeout", 504
        friendly = "Gemini did not respond before the request timed out. Try again."
    elif code == 503 or "unavailable" in status_text:
        category, http_status = "provider_unavailable", 503
        friendly = "Gemini is temporarily unavailable. Please try again in a few minutes."
    elif "connecterror" in error_name or "connectionerror" in error_name:
        category, http_status = "network_error", 502
        friendly = "The backend could not connect to Gemini. Check backend network or proxy connectivity and try again."
    else:
        category, http_status = "provider_error", 502
        friendly = "Gemini could not process this request. Try again or use the standard generator."

    retry_after = _provider_retry_after_seconds(exc)
    logger.warning(
        "Gemini request failed: category=%s exception_type=%s http_status=%s retry_after_seconds=%s",
        category,
        type(exc).__name__,
        code if code is not None else "unknown",
        retry_after if retry_after is not None else "unknown",
    )
    detail = {"category": category, "message": friendly}
    headers = None
    if retry_after is not None:
        detail["retry_after_seconds"] = retry_after
        headers = {"Retry-After": str(retry_after)}
    return HTTPException(status_code=http_status, detail=detail, headers=headers)


def interpret_with_gemini(
    message: str,
    history: list[dict[str, str]],
    hospitals: list[dict[str, str]],
    departments: list[dict[str, str]],
) -> GeminiGenerationProposal:
    """Call the official Google Gen AI SDK; keep it lazy for keyless test runs."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key_is_configured():
        raise HTTPException(status_code=503, detail={
            "category": "not_configured",
            "message": "The Gemini API key is not configured on the backend.",
        })

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        logger.error("Google Gen AI SDK is not installed.")
        raise HTTPException(status_code=503, detail={
            "category": "provider_error",
            "message": "The Gemini assistant is unavailable because its backend SDK is not installed.",
        }) from exc

    system_instruction = (
        "You translate the latest user request into a partial BedSynth synthetic operations generation configuration. "
        "Only use hospitals and departments from the supplied workspace catalog; return their exact name or code, never IDs. "
        "Do not invent missing dates, admission counts, target occupancy, hospital, or departments. Ask clarification in assistant_message "
        "when a required value is missing or ambiguous. Prior assistant messages are context only, not confirmed values. Preserve values "
        "unless the latest user explicitly changes them. Do not add unsupported fields. This is configuration only: never claim data was "
        "generated and never initiate generation. No patient records or patient information are provided. Return concise text."
    )
    contents = json.dumps({
        "workspace_hospital_catalog": hospitals,
        "selected_hospital_departments": departments,
        "conversation_history": history,
        "latest_user_request": message,
    }, ensure_ascii=False, separators=(",", ":"))
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=15_000),
        )
        request_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            # Send only Gemini's supported raw JSON Schema subset.
            # `_parse_gemini_response` and downstream config models
            # enforce the stricter application validation rules.
            response_json_schema=_gemini_proposal_json_schema(),
            max_output_tokens=1200,
            temperature=0.1,
            # This is a short configuration extraction task. Gemini 3.8 Flash
            # defaults to medium thinking; low reduces latency while server-
            # side Pydantic and generation-config validation remain authoritative.
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        )
        request = {
            "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            "contents": contents,
            "config": request_config,
        }
        with client:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(**request)
                    break
                except Exception as exc:
                    if attempt == 0 and _is_provider_deadline_error(exc):
                        logger.warning(
                            "Gemini request reached the provider deadline; retrying once: exception_type=%s http_status=%s provider_status=%s",
                            type(exc).__name__,
                            _provider_error_status_code(exc) or "unknown",
                            str(getattr(exc, "status", "unknown"))[:80],
                        )
                        continue
                    raise
    except HTTPException:
        raise
    except Exception as exc:  # SDK transport, quota, and service errors vary by version.
        raise _gemini_error_response(exc) from exc

    return _parse_gemini_response(response)


def _groq_proposal_json_schema() -> dict:
    """Strict Groq JSON Schema: optional application fields are nullable and required."""
    return {
        "type": "object",
        "properties": {
            "assistant_message": {"type": "string"},
            "hospital_name": {"type": ["string", "null"]},
            "start_date": {"type": ["string", "null"]},
            "end_date": {"type": ["string", "null"]},
            "target_admissions": {"type": ["integer", "null"]},
            "target_occupancy_pct": {"type": ["integer", "null"]},
            "seed": {"type": ["integer", "null"]},
            "department_names": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
        "required": [
            "assistant_message", "hospital_name", "start_date", "end_date",
            "target_admissions", "target_occupancy_pct", "seed", "department_names",
        ],
        "additionalProperties": False,
    }


def _groq_error_response(exc: Exception) -> HTTPException:
    """Map Groq transport/provider failures without returning raw response content."""
    code = _provider_error_status_code(exc)
    if code == 429:
        category, http_status, friendly = "quota", 429, "Groq quota or rate limit reached. Try again after the indicated wait."
    elif code in {401, 403}:
        category, http_status, friendly = "authentication", 502, "Groq authentication failed. Review the backend API key and account access."
    elif code == 404:
        category, http_status, friendly = "model_not_found", 502, "The configured Groq model is unavailable. Review GROQ_MODEL on the backend."
    elif code in {408, 504} or isinstance(exc, TimeoutError):
        category, http_status, friendly = "timeout", 504, "Groq did not respond before the request timed out."
    elif code is not None and code >= 500:
        category, http_status, friendly = "provider_unavailable", 503, "Groq is temporarily unavailable."
    elif isinstance(exc, URLError):
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            category, http_status, friendly = "timeout", 504, "Groq did not respond before the request timed out."
        else:
            category, http_status, friendly = "network_error", 502, "The backend could not connect to Groq. Check backend network connectivity."
    else:
        category, http_status, friendly = "provider_error", 502, "Groq could not process this request."

    retry_after = _provider_retry_after_seconds(exc)
    logger.warning(
        "Groq request failed: category=%s exception_type=%s http_status=%s retry_after_seconds=%s",
        category, type(exc).__name__, code or "unknown", retry_after or "none",
    )
    detail = {"category": category, "message": friendly}
    headers = None
    if retry_after is not None:
        detail["retry_after_seconds"] = retry_after
        headers = {"Retry-After": str(retry_after)}
    return HTTPException(status_code=http_status, detail=detail, headers=headers)


def interpret_with_groq(
    message: str,
    history: list[dict[str, str]],
    hospitals: list[dict[str, str]],
    departments: list[dict[str, str]],
) -> GeminiGenerationProposal:
    """Call Groq's OpenAI-compatible chat completions API with strict JSON Schema."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail={
            "category": "not_configured", "message": "The Groq API key is not configured on the backend.",
        })

    system_instruction = (
        "Convert the latest user request into a partial BedSynth synthetic operations generation configuration. "
        "Only use hospitals and departments from the supplied workspace catalog; return exact names or codes, never IDs. "
        "Do not invent missing dates, admission counts, target occupancy, hospital, or departments. Ask a concise clarification "
        "when a required value is missing or ambiguous. Prior assistant messages are context only. Preserve values unless the "
        "latest user explicitly changes them. Do not add unsupported fields. Never claim records were generated. No patient "
        "records or patient information are provided."
    )
    contents = json.dumps({
        "workspace_hospital_catalog": hospitals,
        "selected_hospital_departments": departments,
        "conversation_history": history,
        "latest_user_request": message,
    }, ensure_ascii=False, separators=(",", ":"))
    request_body = json.dumps({
        "model": os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": contents},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bedsynth_generation_proposal",
                "strict": True,
                "schema": _groq_proposal_json_schema(),
            },
        },
        "temperature": 0.1,
        "max_completion_tokens": 1200,
    }, ensure_ascii=False).encode("utf-8")
    http_request = Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": GROQ_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned empty structured content.")
        return GeminiGenerationProposal.model_validate_json(content)
    except HTTPError as exc:
        # Read and discard the body; provider payloads can contain request text or account details.
        try:
            exc.read()
        except Exception:
            pass
        raise _groq_error_response(exc) from exc
    except HTTPException:
        raise
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValidationError, ValueError) as exc:
        logger.warning("Groq returned malformed structured output: exception_type=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail={
            "category": "malformed_response",
            "message": "Groq returned an invalid structured configuration. The backend rejected it safely.",
        }) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise _groq_error_response(exc) from exc
    except Exception as exc:
        raise _groq_error_response(exc) from exc


def _format_generation_config(payload: AssistantConfigFields, workspace_id: int, hospital: Hospital,
                              departments: list[Department]) -> AssistantGenerationConfig:
    return AssistantGenerationConfig(
        **payload.model_dump(),
        workspace_id=workspace_id,
        hospital_id=hospital.id,
        hospital_name=hospital.name,
        department_names=[department.name for department in departments] if payload.department_ids is not None else None,
    )


def _validation_error_field(error: dict) -> str:
    location = error.get("loc") or ()
    if location:
        return str(location[0])
    message = error.get("msg", "").casefold()
    if "date" in message or "generation date range" in message:
        return "end_date"
    if "occupancy" in message:
        return "target_occupancy_pct"
    if "department" in message:
        return "department_ids"
    return "configuration"


def validate_assistant_config(db: Session, request: AssistantConfigValidationRequest) -> AssistantGenerationConfig:
    hospital = db.scalar(select(Hospital).where(
        Hospital.id == request.hospital_id,
        Hospital.workspace_id == request.workspace_id,
        Hospital.is_archived.is_(False),
    ))
    if hospital is None:
        raise HTTPException(status_code=422, detail={"field_errors": [{"field": "hospital_id", "message": "Choose an active hospital in the selected workspace."}]})
    selected: list[Department] = []
    if request.configuration.department_ids is not None:
        selected = list(db.scalars(select(Department).where(
            Department.id.in_(request.configuration.department_ids),
            Department.hospital_id == hospital.id,
            Department.is_archived.is_(False),
        ).order_by(Department.id)).all())
        if len(selected) != len(request.configuration.department_ids):
            raise HTTPException(status_code=422, detail={"field_errors": [{"field": "department_ids", "message": "Every department must be active and belong to the selected hospital."}]})

    if request.configuration.target_admissions > 0:
        bed_query = select(func.count(Bed.id)).join(Department, Department.id == Bed.department_id).where(
            Bed.hospital_id == hospital.id,
            Bed.status == "operational",
            Department.is_archived.is_(False),
        )
        if request.configuration.department_ids is not None:
            bed_query = bed_query.where(Bed.department_id.in_(request.configuration.department_ids))
        if (db.scalar(bed_query) or 0) == 0:
            raise HTTPException(status_code=422, detail={"field_errors": [{"field": "department_ids", "message": "Generation requires at least one operational bed in the selected departments."}]})

    generation_values = request.configuration.model_dump()
    try:
        validated = GenerationConfig.model_validate(generation_values)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"field_errors": [
            {"field": _validation_error_field(error), "message": error["msg"]}
            for error in exc.errors()
        ]}) from exc
    return _format_generation_config(AssistantConfigFields.model_validate(validated.model_dump(exclude={
        "scenario", "patient_profile", "arrival_profile", "department_demand_weights",
        "length_of_stay_profile", "department_length_of_stay_profiles", "waiting_queue",
        "bed_turnaround_profile", "department_bed_turnaround_profiles",
    })), request.workspace_id, hospital, selected)


def _hospital_matches(hospitals: list[Hospital], name_or_code: str) -> list[Hospital]:
    key = _name_key(name_or_code)
    return [hospital for hospital in hospitals if key in {_name_key(hospital.name), _name_key(hospital.code)}]


def _provider_failure_category(exc: HTTPException) -> str | None:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    category = detail.get("category")
    return category if category in {
        "not_configured", "quota", "authentication", "model_not_found", "timeout",
        "provider_unavailable", "network_error", "malformed_response", "provider_error",
    } else None


def _provider_health_from_category(category: str | None) -> str:
    return "not_configured" if category == "not_configured" else category or "provider_error"


def chat_with_assistant(db: Session, request: AssistantChatRequest, *, include_unpublished: bool = False) -> dict:
    # The assistant appends an application-assigned random seed to ready replies.
    # It is not user-supplied patient information, so omit only that exact,
    # backend-generated annotation from the privacy scan. User messages remain
    # screened in full, regardless of their contents.
    history_for_privacy_scan = [
        re.sub(
            r"\bThe application assigned seed \d+; you can edit it before continuing\.",
            "",
            item.content,
            flags=re.IGNORECASE,
        ) if item.role == "assistant" else item.content
        for item in request.history
    ]
    conversation_text = "\n".join([request.message, *history_for_privacy_scan])
    if _contains_likely_patient_information(conversation_text):
        raise HTTPException(status_code=422, detail="Remove patient-identifying or clinical information before using the assistant. Only fictional hospital operations generation requirements belong here.")
    hospitals = _workspace_hospitals(db, request.workspace_id, include_unpublished=include_unpublished)
    if not hospitals:
        return {
            "status": "needs_clarification",
            "assistant_message": "This workspace has no active hospitals yet. Configure a hospital in Hospital Studio, then return here.",
            "questions": [], "field_errors": [], "hospital_choices": [], "configuration": None,
            "seed_assigned_by_application": False,
        }

    history = _bounded_history(request.history, request.message)
    # Departments are scoped only after resolving a hospital candidate from the latest request/history.
    context_text = " ".join([request.message, *(item["content"] for item in history if item["role"] == "user")])
    possible_hospitals = [hospital for hospital in hospitals if _name_key(hospital.name) in _name_key(context_text) or _name_key(hospital.code) in _name_key(context_text)]
    if len(possible_hospitals) > 1:
        choices = [f"{row.name} ({row.code})" for row in possible_hospitals]
        return {
            "status": "needs_clarification",
            "assistant_message": f"This request could refer to multiple active hospitals. Please reply with one hospital code: {', '.join(choices)}.",
            "questions": ["Which hospital code should I use?"], "field_errors": [],
            "hospital_choices": choices, "configuration": None,
            "seed_assigned_by_application": False,
        }
    dept_catalog: list[dict[str, str]] = []
    if len(possible_hospitals) == 1:
        department_count = db.scalar(select(func.count(Department.id)).where(
            Department.hospital_id == possible_hospitals[0].id,
            Department.is_archived.is_(False),
        )) or 0
        if department_count > MAX_HOSPITAL_DEPARTMENTS:
            raise HTTPException(status_code=422, detail="This hospital has too many active departments for the bounded assistant catalog. Use the standard generator.")
        departments = list(db.scalars(select(Department).where(
            Department.hospital_id == possible_hospitals[0].id,
            Department.is_archived.is_(False),
        ).order_by(Department.name, Department.id)).all())
        dept_catalog = [{"name": department.name, "code": department.code} for department in departments]

    hospital_catalog = _catalog(hospitals)
    gemini_configured = gemini_key_is_configured()
    groq_configured = groq_key_is_configured()
    gemini_status = "configured" if gemini_configured else "not_configured"
    groq_status = "configured" if groq_configured else "not_configured"
    provider_metadata = {
        "assistant_source": "not_checked",
        "gemini_status": gemini_status,
        "groq_status": groq_status,
        "provider_category": None,
        "retry_after_seconds": None,
    }
    fallback_category = "local_only" if request.local_fallback_only else None
    gemini_failure = "local_only" if request.local_fallback_only else (None if gemini_configured else "not_configured")
    groq_failure = "local_only" if request.local_fallback_only else (None if groq_configured else "not_configured")
    retry_delays: list[int] = []

    if not request.local_fallback_only and gemini_configured:
        try:
            proposal = interpret_with_gemini(request.message, history, hospital_catalog, dept_catalog)
            gemini_status = "ready"
            provider_metadata["assistant_source"] = "gemini"
        except HTTPException as exc:
            gemini_failure = _provider_failure_category(exc)
            if gemini_failure is None:
                raise
            gemini_status = _provider_health_from_category(gemini_failure)
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if detail.get("retry_after_seconds"):
                retry_delays.append(int(detail["retry_after_seconds"]))

    # Exactly one secondary-provider attempt per user request; no automatic retries.
    if not request.local_fallback_only and provider_metadata["assistant_source"] != "gemini" and groq_configured:
        try:
            proposal = interpret_with_groq(request.message, history, hospital_catalog, dept_catalog)
            groq_status = "ready"
            provider_metadata["assistant_source"] = "groq"
        except HTTPException as exc:
            groq_failure = _provider_failure_category(exc)
            if groq_failure is None:
                raise
            groq_status = _provider_health_from_category(groq_failure)
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if detail.get("retry_after_seconds"):
                retry_delays.append(int(detail["retry_after_seconds"]))

    if provider_metadata["assistant_source"] != "gemini" and provider_metadata["assistant_source"] != "groq":
        if not request.local_fallback_only:
            fallback_category = groq_failure if groq_failure != "not_configured" else gemini_failure
            fallback_category = fallback_category or "provider_error"
        provider_metadata = {
            "assistant_source": "local",
            "gemini_status": gemini_status,
            "groq_status": groq_status,
            "provider_category": fallback_category,
            "retry_after_seconds": max(retry_delays) if retry_delays else None,
        }
        user_messages = [item["content"] for item in history if item["role"] == "user"]
        user_messages.append(request.message)
        proposal = _local_proposal_from_explicit_values(user_messages, hospital_catalog, dept_catalog)
        if fallback_category == "local_only":
            proposal.assistant_message = (
                "Local fallback is active. I parsed locally only the details stated explicitly in your messages; "
                "neither AI provider was called for this request. Review the proposal carefully."
            )
        elif gemini_status == "not_configured" and groq_status == "not_configured":
            proposal.assistant_message = (
                "Gemini and Groq are not configured. I parsed locally only the details stated explicitly in your messages; "
                "review the proposal carefully before continuing."
            )
        else:
            failure_names = {
                "quota": "quota exceeded", "authentication": "authentication failed",
                "model_not_found": "model unavailable", "timeout": "temporarily unavailable after a timeout",
                "provider_unavailable": "temporarily unavailable", "network_error": "network error",
                "malformed_response": "invalid structured response", "provider_error": "provider error",
            }
            failures = []
            if gemini_status not in {"ready", "not_configured"}:
                failures.append(f"Gemini {failure_names.get(gemini_status, 'unavailable')}")
            if groq_status not in {"ready", "not_configured"}:
                failures.append(f"Groq {failure_names.get(groq_status, 'unavailable')}")
            if not failures and gemini_status == "not_configured":
                failures.append("Gemini is not configured")
            if not failures and groq_status == "not_configured":
                failures.append("Groq is not configured")
            proposal.assistant_message = (
                f"{' and '.join(failures) or 'Both AI providers are unavailable'}. I parsed locally only details "
                "stated explicitly in your messages; no records were generated. Review the proposal carefully."
            )
        logger.info("Assistant used local explicit-value parsing (provider_category=%s).", fallback_category)
    else:
        provider_metadata.update({
            "assistant_source": provider_metadata["assistant_source"],
            "gemini_status": gemini_status,
            "groq_status": groq_status,
            "provider_category": gemini_failure if gemini_failure != "not_configured" else None,
            "retry_after_seconds": max(retry_delays) if retry_delays else None,
        })
    questions: list[str] = []
    field_errors: list[AssistantFieldError] = []
    hospital: Hospital | None = None
    if proposal.hospital_name:
        matches = _hospital_matches(hospitals, proposal.hospital_name)
        if len(matches) == 1:
            hospital = matches[0]
        elif len(matches) > 1:
            choices = [f"{row.name} ({row.code})" for row in matches]
            return {
                "status": "needs_clarification",
                "assistant_message": f"More than one hospital matches. Please reply with the hospital code: {', '.join(choices)}.",
                "questions": ["Which hospital code should I use?"], "field_errors": [],
                "hospital_choices": choices, "configuration": None,
                "seed_assigned_by_application": False,
                **provider_metadata,
            }
        else:
            field_errors.append(AssistantFieldError(field="hospital_name", message="I couldn't match that hospital to an active hospital in this workspace."))
    else:
        questions.append("Which active hospital in this workspace should the dataset use?")

    if proposal.start_date is None:
        questions.append("What start date should the generation period use?")
    if proposal.end_date is None:
        questions.append("What end date should the generation period use?")
    if proposal.target_admissions is None:
        questions.append("How many admissions should the generator create (0 to 5,000)?")
    if proposal.target_occupancy_pct is None:
        questions.append("What target occupancy percentage should it use (0 to 100)?")

    if hospital and proposal.department_names is not None:
        department_count = db.scalar(select(func.count(Department.id)).where(
            Department.hospital_id == hospital.id,
            Department.is_archived.is_(False),
        )) or 0
        if department_count > MAX_HOSPITAL_DEPARTMENTS:
            raise HTTPException(status_code=422, detail="This hospital has too many active departments for the bounded assistant catalog. Use the standard generator.")
        active_departments = list(db.scalars(select(Department).where(
            Department.hospital_id == hospital.id,
            Department.is_archived.is_(False),
        ).order_by(Department.name, Department.id)).all())
        selected: list[Department] = []
        if not active_departments:
            field_errors.append(AssistantFieldError(
                field="department_names",
                message="This hospital has no active departments. Add or activate departments in Hospital Studio before generating a dataset.",
            ))
        elif not proposal.department_names:
            field_errors.append(AssistantFieldError(
                field="department_names",
                message="No requested department matched this hospital's active departments. Provide an active department name or say 'all active departments'.",
            ))
        else:
            for requested_name in proposal.department_names:
                matches = [department for department in active_departments if _name_key(requested_name) in {_name_key(department.name), _name_key(department.code)}]
                if len(matches) != 1:
                    field_errors.append(AssistantFieldError(
                        field="department_names",
                        message=f"Couldn't uniquely match department '{requested_name}'. Use an active department name or code.",
                    ))
                    continue
                if matches[0] not in selected:
                    selected.append(matches[0])
        resolved_department_ids = [department.id for department in selected]
    else:
        resolved_department_ids = None

    if field_errors:
        return {
            "status": "invalid", "assistant_message": proposal.assistant_message,
            "questions": questions, "field_errors": field_errors,
            "hospital_choices": [], "configuration": None,
            "seed_assigned_by_application": False,
            **provider_metadata,
        }
    if questions:
        return {
            "status": "needs_clarification", "assistant_message": proposal.assistant_message,
            "questions": questions, "field_errors": [], "hospital_choices": [],
            "configuration": None, "seed_assigned_by_application": False,
            **provider_metadata,
        }

    seed_assigned = proposal.seed is None
    config_values = {
        "start_date": proposal.start_date,
        "end_date": proposal.end_date,
        "target_admissions": proposal.target_admissions,
        "target_occupancy_pct": proposal.target_occupancy_pct,
        "seed": proposal.seed if proposal.seed is not None else secrets.randbelow(2_147_483_648),
        "department_ids": resolved_department_ids,
    }
    try:
        valid_config = GenerationConfig.model_validate(config_values)
    except ValidationError as exc:
        return {
            "status": "invalid", "assistant_message": "I found a configuration issue. Correct the highlighted values before continuing.",
            "questions": [], "field_errors": [AssistantFieldError(
                field=_validation_error_field(error), message=error["msg"]
            ) for error in exc.errors()], "hospital_choices": [], "configuration": None,
            "seed_assigned_by_application": False,
            **provider_metadata,
        }

    try:
        configuration = validate_assistant_config(db, AssistantConfigValidationRequest(
            workspace_id=request.workspace_id,
            hospital_id=hospital.id,
            configuration=AssistantConfigFields.model_validate(valid_config.model_dump(exclude={
                "scenario", "patient_profile", "arrival_profile", "department_demand_weights",
                "length_of_stay_profile", "department_length_of_stay_profiles", "waiting_queue",
                "bed_turnaround_profile", "department_bed_turnaround_profiles",
            })),
        ))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        errors = detail.get("field_errors", [{"field": "configuration", "message": str(exc.detail)}])
        return {
            "status": "invalid", "assistant_message": "I found a configuration issue. Correct the highlighted values before continuing.",
            "questions": [], "field_errors": [AssistantFieldError(**item) for item in errors],
            "hospital_choices": [], "configuration": None, "seed_assigned_by_application": False,
            **provider_metadata,
        }
    message = proposal.assistant_message.strip()
    if seed_assigned:
        message = f"{message} The application assigned seed {valid_config.seed}; you can edit it before continuing."
    return {
        "status": "ready", "assistant_message": message, "questions": [],
        "field_errors": [], "hospital_choices": [],
        "configuration": configuration, "seed_assigned_by_application": seed_assigned,
        **provider_metadata,
    }
