import re
from bs4 import BeautifulSoup


def clean_email_body(raw_body: str) -> str:
    if not raw_body:
        return ""  
    if any(tag in raw_body.lower() for tag in ["<html", "<div", "<p", "<br"]):
        try:
            soup = BeautifulSoup(raw_body, "lxml")
            for tag in soup(["script", "style"]):
                tag.decompose()
            clean_text = soup.get_text(separator=" ")
            return " ".join(clean_text.split())
        except Exception:
            return re.sub(r'<[^>]+>', '', raw_body).strip()       
    return raw_body.strip()


def extract_sender_info(sender: str) -> dict:
    name = None
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


JOB_ROLE_BLACKLIST = [
    r'^opportunities?\s+matching',
    r'^new\s+job',
    r'matching your (profile|skills)',
    r'has been received',
    r'verification code',
    r'sign.?up',
    r'\botp\b',
    r'account created',
    r'security alert',
    r'registration',
    r'welcome to',
    r'sign.?in',
    r'purchase order',
    r'privacy settings',
    r'unsubscribe',
    r'^application$',
    r'^regarding$',
    r'^job$',
    r'^position$',
    r'^role$',
    r'interview\s+schedule',
    r'action required',
    r'invitation',
    r'^re:',
    r'^fwd:',
    r'\bmy\s+resume\b',
    r'\bsending\s+(you|this)\b',
    r'\bjob\s+application\b',
    r'\bregarding\b',
]

_SYSTEM_EMAIL_PATTERNS = re.compile(
    r'(noreply|no-reply|do-not-reply|account.?security|accountprotection'
    r'|microsoft\.com|outlook\.com|accounts\.google|mailer-daemon'
    r'|notifications?@|support@|info@|postmaster@)',
    re.IGNORECASE
)

_SYSTEM_SUBJECT_PATTERNS = re.compile(
    r'\b(welcome to|account (deactivated|created|connected|verified|updated|security)'
    r'|security info|new app.?s? connected|sign.?in|otp|verification code'
    r'|privacy statement|password reset|unsubscribe|update your account'
    r'|microsoft account|outlook\.com account)\b',
    re.IGNORECASE
)


def _is_system_email(sender_email: str, subject: str) -> bool:
    """Return True if this looks like a platform/system email, not a human job application."""
    if sender_email and _SYSTEM_EMAIL_PATTERNS.search(sender_email):
        return True
    if subject and _SYSTEM_SUBJECT_PATTERNS.search(subject):
        return True
    return False


def _is_blacklisted(text: str) -> bool:
    t = text.strip()
    return any(re.search(p, t, re.IGNORECASE) for p in JOB_ROLE_BLACKLIST)


TECH_KEYWORDS_PATTERN = re.compile(
    r'\b(python|java(?:script)?|react(?:\.?js)?|node(?:\.?js)?|angular|vue(?:\.?js)?|'
    r'flutter|django|fastapi|spring|'
    r'devops|machine\s+learning|data\s+science|data\s+engineer(?:ing)?|'
    r'backend|front.?end|full.?stack|'
    r'android|ios|mobile|php|golang|go\b|rust|c\+\+|c#|dotnet|\.net|'
    r'aws|gcp|azure|cloud|kubernetes|docker|'
    r'qa|quality\s+assurance|automation\s+tester?|'
    r'ui.?ux|product\s+manager?|scrum\s+master|'
    r'hr|human\s+resource|recruiter|sales|marketing|'
    r'blockchain|solidity|web3|cybersecurity|security\s+engineer|'
    r'embedded|firmware|hardware|vlsi|'
    r'sql|database\s+admin(?:istrator)?|dba)',
    re.IGNORECASE
)

ROLE_SUFFIX_PATTERN = re.compile(
    r'\b(developer|engineer|designer|analyst|manager|intern|consultant|'
    r'architect|lead|specialist|scientist|administrator|tester?|executive|'
    r'associate|coordinator|director|officer|head|'
    r'programmer|coder|hacker|technician|integrator|implementer|'
    r'maintainer|troubleshooter|debugger|reviewer|'
    r'researcher|modeler|annotator|labeler|curator|'
    r'illustrator|animator|videographer|photographer|'
    r'copywriter|content\s+writer|technical\s+writer|blogger|'
    r'supervisor|superintendent|president|vice\s+president|vp|'
    r'cto|ceo|coo|cfo|founder|co.?founder|'
    r'support|representative|agent|operator|handler|dispatcher|'
    r'moderator|auditor|inspector|evaluator|assessor|'
    r'strategist|planner|campaigner|promoter|advertiser|'
    r'account\s+manager|account\s+executive|business\s+developer|'
    r'growth\s+hacker|seo\s+specialist|'
    r'recruiter|talent\s+acquisition|hr\s+executive|hr\s+manager|'
    r'staffing\s+specialist|hiring\s+manager|'
    r'accountant|bookkeeper|tax\s+consultant|'
    r'lawyer|advocate|paralegal|compliance\s+officer|'
    r'devops|sre|site\s+reliability|platform\s+engineer|'
    r'cloud\s+engineer|network\s+engineer|security\s+engineer|'
    r'infrastructure\s+engineer|systems\s+engineer|'
    r'qa|qc|quality\s+engineer|automation\s+engineer|'
    r'performance\s+engineer|test\s+lead|test\s+manager|'
    r'trainee|apprentice|fellow|graduate|fresher)\b',
    re.IGNORECASE
)

_PURE_JOB_TITLE_PATTERN = re.compile(
    r'^(?:(?:senior|junior|lead|sr\.?|jr\.?|associate|principal|staff)\s+)?'
    r'(?:[A-Za-z0-9#\+\.]+\s+){0,4}'    
    r'(?:developer|engineer|designer|analyst|manager|intern|consultant|'
    r'architect|lead|specialist|scientist|administrator|tester|'
    r'qa|devops|researcher|programmer|executive|coordinator|'
    r'recruiter|accountant|copywriter|writer|trainer|fresher)'
    r'(?:\s+(?:trainee|intern|lead|head|associate|fresher|graduate))?'
    r'\s*$',
    re.IGNORECASE
)

_JOB_ROLE_FOR_PATTERN = re.compile(
    r'(?:job\s+role\s+for|opening\s+for|vacancy\s+for|hiring\s+for|role\s+for)\s+'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',
    re.IGNORECASE
)

def _subject_is_pure_job_title(subject: str) -> bool:
    return bool(_PURE_JOB_TITLE_PATTERN.match(subject.strip()))


_SUBJECT_PATTERNS = [
    r'(?:job\s+role\s+for|opening\s+for|vacancy\s+for|hiring\s+for|role\s+for)\s+'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'(?:application\s+for|applying\s+for|apply\s+for|resume\s+for|cv\s+for)\s*[:\-]?\s*'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:\s+(?:role|position|job|post|opening|opportunity))?'
    r'(?:[,\.\n(]|$)',

    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s+'
    r'(?:developer|engineer|designer|analyst|manager|intern|consultant|architect|lead|specialist|scientist)'
    r'\s+(?:application|resume|cv|position|role|job)',

    r'\bfor\s+([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s+(?:position|role|job|opening|post)\b',

    r'interview\s+(?:schedule\s*[:\-]?\s*|for\s+)([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)'
    r'(?:\s*[\(\[].*?[\)\]])?(?:[,\.\n]|$)',

    r'^([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s+(?:position|role|opening|vacancy)(?:[,\.\n(]|$)',

    r'(?:your\s+)?application\s+for\s+([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)'
    r'\s+(?:has\s+been|position|role)(?:[,\.\s(]|$)',

    r'hiring\s*[:\-]?\s*(?:a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'(?:job\s+)?vacancy\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'opening\s+for\s+(?:a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'^([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s*[\-\|]\s*(?:job\s+)?(?:application|resume|cv|candidature)(?:[,\.\n(]|$)',

    r'^(?:job\s+)?(?:application|resume|cv)\s*[\-\|]\s*([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'(?:shortlisted|selected|chosen)\s+for\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s*(?:position|role|job|[,\.\n(]|$)',

    r'offer\s+(?:letter\s+)?(?:for\s+)?[\-\|]?\s*(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'(?:rejection|regret|declined?)\s+.*?(?:for\s+)?(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s+(?:position|role|job|opening)',

    r'^([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s+(?:opportunity|opening)\s+(?:at|with|@)\s+\w',

    r'(?:screening|technical|hr|final)\s+(?:round|interview)\s*[\-\|]?\s*(?:for\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'(?:assessment|test|assignment)\s+for\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s*(?:position|role|job|[,\.\n(]|$)',

    r'(?:joining\s+letter|appointment)\s*[\-\|:]?\s*(?:as\s+(?:a\s+|an\s+)?)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'internship\s+(?:application\s+)?(?:for\s+|[\-\|]\s*)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)(?:[,\.\n(]|$)',

    r'(?:fresher|entry\s+level|junior|senior|lead)\s+([A-Za-z0-9][A-Za-z0-9\s\+\#\.]+?)\s+(?:application|resume|cv|position|role)(?:[,\.\n(]|$)',
]


def _extract_from_subject(subject: str) -> str | None:
    _STRIP_PREFIX = re.compile(
        r'^(?:applying\s+for|apply\s+for|application\s+for|resume\s+for|cv\s+for'
        r'|job\s+role\s+for|opening\s+for|vacancy\s+for|hiring\s+for|role\s+for'
        r'|job\s+opening\s+for|position\s+of|post\s+of)\s+',
        re.IGNORECASE
    )
    stripped = subject.strip()
    remainder = _STRIP_PREFIX.sub('', stripped).strip().rstrip('.,;:')
    if _subject_is_pure_job_title(remainder) and not _is_blacklisted(remainder):
        return remainder.title()

    if _subject_is_pure_job_title(stripped) and not _is_blacklisted(stripped):
        return stripped.title()

    for pattern in _SUBJECT_PATTERNS:
        m = re.search(pattern, subject, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().rstrip('.,;:')
            candidate = re.sub(r'\s+', ' ', candidate)
            if _is_blacklisted(candidate):
                continue
            if 2 < len(candidate) < 80:
                return candidate.title()
    return None


_BODY_PATTERNS = [
    r'(?:applying|applied|application)\s+(?:for\s+(?:the\s+)?|to\s+(?:the\s+)?)?'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:position|role|job|opening|post|vacancy)',

    r'interested\s+in\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+'
    r'(?:position|role|job|opening|post|vacancy)',

    r'(?:position|role|post|vacancy)\s+of\s+([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:[,\.\n(]|$)',

    r'for\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:at|with|@)\s+\w',

    r'(?:job\s+title|position|role|designation)\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:[,\.\n(]|$)',

    r'(?:apply|applied|applying)\s+as\s+(?:a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:[,\.\n(]|$)',

    r'writing\s+to\s+(?:apply|express)\s+.*?(?:for|in)\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:position|role|job|opening)',

    r'(?:my\s+)?(?:resume|cv|curriculum\s+vitae)\s+for\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:position|role|job|opening|post)',

    r'candidate\s+for\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s*(?:position|role|job|opening|post|[,\.\n(]|$)',

    r'(?:experience|working|worked)\s+as\s+(?:a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:[,\.\n(]|$)',

    r'(?:currently|presently)\s+working\s+as\s+(?:a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:\s+at|\s+in|[,\.\n(]|$)',

    r'regarding\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:position|role|job|opening|post|vacancy)',

    r'seek(?:ing)?\s+(?:a\s+|an\s+|the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:position|role|job|opening|post)',

    r'opportunity\s+(?:for\s+|as\s+)(?:a\s+|an\s+|the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s*(?:position|role|job|[,\.\n(]|$)',

    r'I\s+am\s+(?:a\s+|an\s+)?(?:experienced\s+|fresher\s+|senior\s+|junior\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:with\s+\d|developer|engineer|looking)',

    r'(?:strong|keen|great)\s+interest\s+in\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+(?:position|role|job|opening)',

    r'(?:hiring|recruiting)\s+(?:for\s+)?(?:a\s+|an\s+)?([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:\s+position|\s+role|\s+job|[,\.\n(]|$)',

    r'(?:resume|cv|application)\s+(?:regarding|for)\s+job\s+application\s+for\s+'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:[,\.\n(]|$)',

    r'sending\s+(?:you\s+)?(?:my\s+)?(?:resume|cv)\s+regarding\s+'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:[,\.\n(]|$)',

    r'(?:this\s+is\s+(?:an?\s+)?application\s+for\s+)'
    r'([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)(?:\s+job|\s+role|\s+position|[,\.\n(]|$)',

    r'interest\s+in\s+the\s+([A-Za-z0-9][A-Za-z0-9\s\+\#\.\-]+?)\s+position\s+at\s+\w',
]

_MAX_ROLE_WORDS = 20


def _extract_from_body(body: str) -> str | None:
    snippet = body[:1000]
    for pattern in _BODY_PATTERNS:
        m = re.search(pattern, snippet, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().rstrip('.,;:')
            candidate = re.sub(r'\s+', ' ', candidate)
            if _is_blacklisted(candidate):
                continue
            if len(candidate.split()) > _MAX_ROLE_WORDS:
                continue
            if 2 < len(candidate) < 80:
                return candidate.title()
    return None


def _extract_via_keywords(subject: str, body: str) -> str | None:
    for text in (subject, body[:500]):
        tech_matches = list(TECH_KEYWORDS_PATTERN.finditer(text))
        role_matches = list(ROLE_SUFFIX_PATTERN.finditer(text))

        if not role_matches:
            continue

        for role_m in role_matches:
            best_tech = None
            best_dist = 999
            for tech_m in tech_matches:
                dist = abs(tech_m.start() - role_m.start())
                if dist < best_dist and dist <= 60:
                    best_dist = dist
                    best_tech = tech_m

            if best_tech:
                if best_tech.start() < role_m.start():
                    label = f"{best_tech.group(0)} {role_m.group(0)}"
                else:
                    label = f"{role_m.group(0)} {best_tech.group(0)}"
                label = re.sub(r'\s+', ' ', label).strip()
                if not _is_blacklisted(label) and 4 < len(label) < 60:
                    return label.title()

        if text is subject and tech_matches:
            label = " ".join(dict.fromkeys(m.group(0) for m in tech_matches[:2])).title()
            if not _is_blacklisted(label):
                return label

    return None


def extract_job_position(subject: str, body: str, sender_email: str = "") -> str | None:
    if _is_system_email(sender_email, subject):
        return None
    return (
        _extract_from_subject(subject)
        or _extract_from_body(body)
        or _extract_via_keywords(subject, body)
    )


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


JOB_APPLICATION_KEYWORDS = re.compile(
    r'\b(job\s+application|applying\s+for|resume|cv|curriculum\s+vitae|'
    r'cover\s+letter|hiring|position|vacancy|opening|opportunity|'
    r'work\s+experience|internship|fresher|experienced\s+candidate|'
    r'regarding\s+.*(?:developer|engineer|designer|analyst|manager)|'
    r'application\s+for\s+\w.*job|'
    r'application\s+for\s+\w.*role|'
    r'application\s+for\s+\w.*position)\b',
    re.IGNORECASE
)


def is_job_application(subject: str, body: str, sender_email: str = "") -> bool:
    body = body or ""
    subject = subject or ""
    
    is_reply = bool(re.match(r'^(Re|Fwd):', subject, re.IGNORECASE))
    
    if _is_system_email(sender_email, subject) and not is_reply:
        return False

    strong_subject_signals = [
        r'(?:developer|engineer|role|position|job)\s+application',
        r'application\s+for\s+.*?(?:developer|engineer|role|position)',
        r'regarding\s+.*?(?:developer|engineer|role|position|job)'
    ]
    if any(re.search(p, subject, re.IGNORECASE) for p in strong_subject_signals):
        return True

    if _subject_is_pure_job_title(subject.strip()):
        return True
    
    subject_has_role = bool(
        TECH_KEYWORDS_PATTERN.search(subject) or ROLE_SUFFIX_PATTERN.search(subject)
    )
    
    body_has_signal = bool(re.search(
        r'\b(resume|cv|application|applying|trainee|developer|engineer|'
        r'position|role|job|hiring|fresher|cover\s+letter)\b',
        body[:500], re.IGNORECASE
    ))
    
    if subject_has_role and body_has_signal:
        return True

    text = f"{subject} {body[:500]}"
    return bool(JOB_APPLICATION_KEYWORDS.search(text))


def extract_email_data(
    sender:           str,
    subject:          str,
    raw_body:         str,
    date:             str,
    attachment_names: list[str]
) -> dict:
    clean_body      = clean_email_body(raw_body)
    sender_info     = extract_sender_info(sender)
    sender_email    = sender_info["sender_email"] or ""

    job_position    = extract_job_position(subject, clean_body, sender_email)
    attachment_info = extract_attachment_info(attachment_names)
    job_application = is_job_application(subject, clean_body, sender_email)

    if not sender_info["candidate_name"]:
        sig_match = re.search(r'(?:Regards|Best|Thanks|Sincerely),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', clean_body)
        if sig_match:
            sender_info["candidate_name"] = sig_match.group(1)

    return {
        "candidate_name"    : sender_info["candidate_name"],
        "sender_email"      : sender_email,
        "is_job_application": job_application,
        "job_position"      : job_position,
        "subject"           : subject,
        "date"              : date,
        "attachment_names"  : attachment_info["attachment_names"],
        "attachment_types"  : attachment_info["attachment_types"],
    }