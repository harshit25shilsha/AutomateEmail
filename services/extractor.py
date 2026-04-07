# services/extractor.py
import re
from bs4 import BeautifulSoup


# ── Clean HTML email body ─────────────────────────────────────
def clean_email_body(raw_body: str) -> str:
    if any(tag in raw_body.lower() for tag in ["<html", "<div", "<p>"]):
        soup = BeautifulSoup(raw_body, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        clean_text = soup.get_text(separator=" ")
        return " ".join(clean_text.split())
    return raw_body.strip()



def extract_sender_info(sender: str) -> dict:
    name  = None
    email = None

    email_match = re.search(r'<([^>]+)>', sender)
    if email_match:
        email = email_match.group(1).strip()
        raw_name = sender[:email_match.start()].strip().strip('"').strip("'")
        if raw_name:
            name = raw_name
    else:
        plain_email = re.search(r'[\w.\-+]+@[\w.\-]+\.\w+', sender)
        if plain_email:
            email = plain_email.group(0)

    return {"candidate_name": name, "sender_email": email}



JOB_PATTERNS = [
    r'(?:application\s+for|applying\s+for|apply\s+for|resume\s+for|cv\s+for)\s*[:\-]?\s*([A-Za-z0-9\s\+\#\.]+?)(?:\s+(?:role|position|job|post|opening|opportunity))?(?:[,\.\n]|$)',
    r'([A-Za-z0-9\s\+\#\.]+?)\s+(?:developer|engineer|designer|analyst|manager|intern|consultant|architect|lead|specialist|scientist)\s+(?:application|resume|cv|position|role|job)',
    r'(?:hiring|vacancy|opening)\s+(?:for\s+)?([A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n]|$)',
]

# ── BLACKLIST: subjects that look like job patterns but aren't ──
JOB_ROLE_BLACKLIST = [
    r'^opportunities matching',
    r'^opportunity matching',
    r'^job opportunities',
    r'^new job',
    r'matching your profile',
    r'matching your skills',
    r'has been received',
    r'verification code',
    r'sign.?up',
    r'otp',
    r'account created',
    r'security alert',
    r'registration',
    r'welcome to',
    r'sign.?in',
    r'purchase order',
    r'privacy settings',
    r'unsubscribe',
]

def extract_job_position(subject: str, body: str) -> str | None:
    for pattern in JOB_PATTERNS:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            position = match.group(1).strip()
            position = re.sub(r'\s+', ' ', position)

            if any(re.search(bl, position, re.IGNORECASE) for bl in JOB_ROLE_BLACKLIST):
                continue

            if 2 < len(position) < 60:
                return position.title()

    tech_keywords = re.findall(
        r'\b(python|java|react|node|angular|vue|flutter|django|fastapi|'
        r'devops|machine learning|data science|backend|frontend|fullstack|'
        r'full.stack|android|ios|php|golang|rust|c\+\+|dotnet|\.net|'
        r'aws|cloud|qa|testing|ui.ux|product manager|hr|sales)\b',
        subject, re.IGNORECASE
    )
    if tech_keywords:
        return " ".join(dict.fromkeys(tech_keywords)).title()

    return None


# ── Extract attachment info ───────────────────────────────────
def extract_attachment_info(attachment_names: list[str]) -> dict:
    types = []
    for name in attachment_names:
        ext_match = re.search(r'\.(\w+)$', name)
        if ext_match:
            types.append(ext_match.group(1).lower())
    return {
        "attachment_names": attachment_names,
        "attachment_types": list(set(types))
    }


# ── Check if email is a job application ──────────────────────
JOB_APPLICATION_KEYWORDS = [
    r'\b(job application|applying for|resume|cv|curriculum vitae|'
    r'cover letter|hiring|position|vacancy|opening|opportunity|'
    r'work experience|internship|fresher|experienced candidate)\b'
]

def is_job_application(subject: str, body: str) -> bool:
    text = f"{subject} {body[:500]}"
    for pattern in JOB_APPLICATION_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# ── Main extractor ────────────────────────────────────────────
def extract_email_data(
    sender:           str,
    subject:          str,
    raw_body:         str,
    date:             str,
    attachment_names: list[str]
) -> dict:

    clean_body       = clean_email_body(raw_body)
    sender_info      = extract_sender_info(sender)
    job_position     = extract_job_position(subject, clean_body)
    attachment_info  = extract_attachment_info(attachment_names)
    job_application  = is_job_application(subject, clean_body)

    return {
        "candidate_name"    : sender_info["candidate_name"],
        "sender_email"      : sender_info["sender_email"],
        "is_job_application": job_application,
        "job_position"      : job_position,
        "subject"           : subject,
        "date"              : date,
        "attachment_names"  : attachment_info["attachment_names"],
        "attachment_types"  : attachment_info["attachment_types"],
    }