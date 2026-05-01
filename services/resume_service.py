import os, re, docx, PyPDF2, json
import tempfile
import spacy
import boto3
import uuid
import fitz 
import time
import mimetypes
from groq import Groq
from botocore.exceptions import NoCredentialsError
from typing import List, Optional
from PyPDF2 import PdfReader, PdfWriter
import pdfminer.pdfparser as _pdfparser
import pdfminer.pdfdocument as _pdfdoc
from pdfminer.pdftypes import resolve1 as _resolve1
from pdfminer.pdfpage import PDFPage as _PDFPage
from fastapi import UploadFile
from datetime import datetime
from zoneinfo import ZoneInfo
import phonenumbers
from dateutil import parser
from dateutil import parser as date_parser

nlp = spacy.load("en_core_web_sm")

groq_client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)


EMAIL_REGEX       = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,10}\b'
BASIC_PHONE_REGEX = r'(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{3,5}'
DATE_PATTERNS     = [
    r'(\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\-]+\d{4})\s*(?:to|\-|\–)\s*(Present|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\-]+\d{4})',
    r'(\d{1,2}\/\d{4}|\d{4})\s*(?:to|\-|\–)\s*(Present|\d{1,2}\/\d{4}|\d{4})'
]
_LINKEDIN_RAW = (
    r'(?:linkedin\s*[:\-\|]?\s*)?'
    r'(?:https?://)?(?:www\.)?'
    r'linkedin\.com/(?:in|pub|company)/[A-Za-z0-9\-_%]+'
)
_GITHUB_RAW = (
    r'(?:github\s*[:\-\|]?\s*)?'
    r'(?:https?://)?(?:www\.)?'
    r'github\.com/[A-Za-z0-9\-_]+'
)
_PORTFOLIO_RAW = (
    r'(?:portfolio\s*[:\-\|]?\s*)'           # must have label to avoid noise
    r'(?:https?://)?[A-Za-z0-9\-_.]+\.[A-Za-z]{2,}/[^\s]*'
)

LINKEDIN_REGEX  = re.compile(_LINKEDIN_RAW,  re.IGNORECASE)
GITHUB_REGEX    = re.compile(_GITHUB_RAW,    re.IGNORECASE)
PORTFOLIO_REGEX = re.compile(_PORTFOLIO_RAW, re.IGNORECASE)


def _normalise_url(raw: str) -> str:
    """Ensure the URL starts with https://"""
    raw = raw.strip().rstrip('/')
    if not raw.lower().startswith("http"):
        raw = "https://" + raw
    return raw


def extract_hyperlinks_from_pdf(file_obj) -> dict:
    links = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    try:
        if isinstance(file_obj, str):
            f = open(file_obj, "rb")
            should_close = True
        else:
            file_obj.seek(0)
            f = file_obj
            should_close = False

        parser = _pdfparser.PDFParser(f)
        doc    = _pdfdoc.PDFDocument(parser)

        for page in _PDFPage.create_pages(doc):
            if "Annots" not in page.attrs:
                continue
            annots = _resolve1(page.attrs["Annots"])
            if not annots:
                continue
            for annot in annots:
                annot = _resolve1(annot)
                subtype = annot.get("Subtype")
                if not (subtype and getattr(subtype, "name", None) == "Link"):
                    continue
                action = annot.get("A")
                if not action:
                    continue
                action = _resolve1(action)
                uri = action.get("URI")
                if not uri:
                    continue
                if isinstance(uri, bytes):
                    uri = uri.decode("utf-8", errors="ignore")
                uri = uri.strip()
                if not uri or uri.startswith("mailto:") or uri.startswith("tel:"):
                    continue
                if "linkedin.com" in uri and not links["linkedin"]:
                    links["linkedin"] = uri if uri.startswith("http") else "https://" + uri
                elif "github.com" in uri and not links["github"]:
                    links["github"] = uri if uri.startswith("http") else "https://" + uri
                else:
                    links["other"].append(uri)

        if should_close:
            f.close()
    except Exception as e:
        print(f"[WARN] PDF hyperlink extraction failed: {e}")
    return links


def extract_profile_urls(text: str) -> dict:

    linkedin = github = portfolio = None

    m = LINKEDIN_REGEX.search(text)
    if m:
        raw = re.sub(r'^(?:linkedin\s*[:\-\|]\s*)', '', m.group(0), flags=re.IGNORECASE).strip()
        linkedin = _normalise_url(raw)

    m = GITHUB_REGEX.search(text)
    if m:
        raw = re.sub(r'^(?:github\s*[:\-\|]\s*)', '', m.group(0), flags=re.IGNORECASE).strip()
        github = _normalise_url(raw)

    m = PORTFOLIO_REGEX.search(text)
    if m:
        raw = re.sub(r'^(?:portfolio\s*[:\-\|]\s*)', '', m.group(0), flags=re.IGNORECASE).strip()
        portfolio = _normalise_url(raw)

    return {"linkedin": linkedin, "github": github, "portfolio": portfolio}


SKILLS = [
    # --- LANGUAGES ---
    "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go", "Rust", "Ruby",
    "PHP", "Perl", "Swift", "Kotlin", "R", "Scala", "Objective-C", "MATLAB", "Shell Scripting",
    "Dart", "Solidity", "GraphQL", "SQL", "NoSQL", "Bash",

    # --- FRONTEND FRAMEWORKS & LIBS ---
    "HTML", "CSS", "SASS", "LESS", "Bootstrap", "Tailwind CSS", "React", "Angular", "Vue.js",
    "Next.js", "Nuxt.js", "Svelte", "jQuery", "Gatsby", "GSAP", "Material UI", "ShadCN",
    "Chakra UI", "Ant Design", "Redux", "Zustand", "Recoil", "MobX", "Storybook", "Vite",

    # --- BACKEND & FRAMEWORKS ---
    "Node.js", "Express.js", "Django", "Flask", "FastAPI", "Spring Boot", "ASP.NET",
    "Laravel", "Symfony", "CodeIgniter", "NestJS", "Strapi", "Socket.io", "Hapi.js",

    # --- DATABASES ---
    "PostgreSQL", "MySQL", "MariaDB", "SQLite", "MongoDB", "Cassandra", "Redis", "Elasticsearch",
    "Firebase", "DynamoDB", "CouchDB", "Neo4j", "Snowflake", "BigQuery", "Oracle Database",
    "Microsoft SQL Server", "Supabase", "Prisma", "Sequelize", "Mongoose",

    # --- CLOUD & DEVOPS ---
    "AWS", "Azure", "Google Cloud", "IBM Cloud", "Heroku", "DigitalOcean", "Vercel", "Netlify",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "GitLab CI/CD", "GitHub Actions",
    "CircleCI", "Nginx", "Apache", "Prometheus", "Grafana", "Linux Administration",

    # --- TESTING ---
    "Jest", "Cypress", "Selenium", "Mocha", "Chai", "Puppeteer", "Playwright", "React Testing Library",
    "JUnit", "Pytest", "Postman",

    # --- MOBILE & WEB3 ---
    "React Native", "Flutter", "Android Development", "iOS Development", "Web3.js", "Ethers.js",

    # --- DATA SCIENCE & AI ---
    "Machine Learning", "Deep Learning", "Data Science", "Artificial Intelligence",
    "Natural Language Processing", "Computer Vision", "Data Analysis", "Data Visualization",
    "Pandas", "NumPy", "Matplotlib", "Seaborn", "TensorFlow", "Keras", "PyTorch", "Scikit-learn",
    "LangChain", "OpenAI API", "HuggingFace", "Spark", "Hadoop",

    # --- ARCHITECTURE & CONCEPTS ---
    "DSA", "OOP", "REST APIs", "SDLC", "Microservices", "Serverless", "JWT", "OAuth",
    "Agile", "Scrum", "Kanban", "Waterfall", "JIRA", "Confluence", "Git", "GitHub", "GitLab",

    # --- DESIGN & TOOLS ---
    "UI/UX Design", "Figma", "Adobe XD", "Sketch", "Canva", "Photoshop",

    # --- SOFT SKILLS & BUSINESS ---
    "SEO", "SEM", "Google Analytics", "Accounting", "Financial Analysis", "Technical Writing",
    "Research", "Customer Service", "Sales", "Negotiation", "Public Speaking", "Problem Solving",
    "MS Excel", "MS-PowerPoint", "Team Leadership", "Communication Skills",
]

SECTION_HEADERS = {
    "experience": [
        "experience", "work experience", "professional experience",
        "employment history", "career history", "work history",
        "internship / experience", "internship/experience",
        "internship & experience", "internship", "work & experience",
    ],
    "education": [
        "education", "academic background", "academic qualifications",
        "educational background", "education and training",
    ],
    "projects":       ["projects", "project work", "key projects", "personal projects"],
    "certifications": ["certifications", "certificates", "licenses", "certifications & awards",
                       "certifications and awards", "professional certifications"],
}

EXTRA_STOP_HEADERS = [
    "internship / experience", "internship/experience", "internship",
    "achievements", "personal details", "declaration",
    "extra curricular", "volunteer", "hobbies", "references",
    "technical skills", "professional summary", "summary",
]



def upload_file_to_s3(file: UploadFile, folder="resumes") -> str:
    try:
        ext = file.filename.split(".")[-1].lower()
        key = f"{folder}/{uuid.uuid4()}.{ext}"
        content_type, _ = mimetypes.guess_type(file.filename)
        if not content_type:
            content_type = "application/octet-stream"

        if ext == "pdf":
            temp_file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf").name
            file.file.seek(0)
            reader = PdfReader(file.file)
            writer = PdfWriter()
            writer.append_pages_from_reader(reader)
            writer.add_metadata({"/Title": file.filename, "/Author": ""})
            with open(temp_file_path, "wb") as f:
                writer.write(f)
            upload_path = temp_file_path
        else:
            temp_file_path = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}").name
            file.file.seek(0)
            with open(temp_file_path, "wb") as f:
                f.write(file.file.read())
            upload_path = temp_file_path

        with open(upload_path, "rb") as f:
            s3_client.upload_fileobj(
                f,
                os.getenv("AWS_BUCKET_NAME"),
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "ContentDisposition": f'inline; filename="{file.filename}"'
                }
            )
        os.remove(temp_file_path)
        url = f"https://{os.getenv('AWS_BUCKET_NAME')}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{key}"
        return url

    except NoCredentialsError:
        print("AWS credentials not available")
        return None
    except Exception as e:
        print(f"Failed to upload to S3: {e}")
        return None


def extract_text(file: UploadFile) -> str:
    try:
        if file.filename.lower().endswith(".pdf"):
            file.file.seek(0)
            try:
                reader = PyPDF2.PdfReader(file.file, strict=False)
            except Exception as e:
                print(f"[ERROR] Cannot read PDF: {file.filename} -> {e}")
                return ""
            full_text = []
            for page in reader.pages:
                try:
                    page_text = page.extract_text()
                    if page_text:
                        lines = [line.strip() for line in page_text.split("\n") if line.strip()]
                        full_text.extend(lines)
                except Exception as e:
                    print(f"[ERROR] Failed reading PDF page in {file.filename}: {e}")
            return "\n".join(full_text)

        elif file.filename.lower().endswith(".docx"):
            file.file.seek(0)
            try:
                doc = docx.Document(file.file)
            except Exception as e:
                print(f"[ERROR] Failed to parse DOCX file: {file.filename}, error: {e}")
                return ""
            full_text = []
            for para in doc.paragraphs:
                if para.text.strip():
                    full_text.append(para.text.strip())
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            full_text.append(cell.text.strip())
            return "\n".join(full_text)

        elif file.filename.lower().endswith(".txt"):
            file.file.seek(0)
            return file.file.read().decode("utf-8", errors="ignore")

    except Exception as e:
        print(f"[ERROR] extract_text crashed for {file.filename}: {e}")
        return ""

    return ""


def extract_text_and_links(file: UploadFile) -> tuple[str, dict]:
    
    text = extract_text(file)

    pdf_links = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    if file.filename.lower().endswith(".pdf"):
        pdf_links = extract_hyperlinks_from_pdf(file.file)

    return text, pdf_links


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    return text.replace('\x00', '').strip()


def extract_name(text: str) -> Optional[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and len(lines[0].split()) > 6:
        first_chunk = re.split(r'\s{2,}|\|', lines[0])[0].strip()
        lines = [first_chunk] + lines[1:]
    blacklist = {
        'resume', 'cv', 'curriculum', 'developer', 'engineer', 
        'consultant', 'manager',
        'mca', 'bca', 'btech', 'mtech', 'bsc', 'msc', 'mba',
        'ba', 'ma', 'bcom', 'mcom', 'phd', 'bca', 'pgdm',
        'hsc', 'ssc', 'diploma', 'intermediate',
        'haldwani', 'dehradun', 'delhi', 'mumbai', 'bangalore',
    }

    def is_valid_name_line(line: str) -> bool:
        words = line.split()
        if not (2 <= len(words) <= 4):
            return False
        if not all(w[0].isupper() for w in words if w.isalpha()):
            return False
        if any(w.lower() in blacklist for w in words):  
            return False
        if any(char.isdigit() for char in line):
            return False
        if ',' in line:           
            return False
        if line.startswith(('●', '•', '-', '*', '/')):  
            return False
        if re.search(r'[@|+]', line):
            return False
        return True

    for line in lines:
        match = re.search(r"(?i)^name\s*[:\-]\s*([A-Za-z\s.]+)$", line)
        if match:
            candidate = match.group(1).strip()
            if is_valid_name_line(candidate):
                return candidate

    for line in lines[:8]:
        if is_valid_name_line(line):
            return line

    doc = nlp(text[:800])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            if is_valid_name_line(name):
                return name

    return None


def extract_phone_numbers(text: str) -> List[str]:
    numbers = []
    for match in phonenumbers.PhoneNumberMatcher(text, None):
        try:
            formatted = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            if formatted not in numbers:
                numbers.append(formatted)
        except Exception:
            continue
    return numbers


def extract_section(text: str, section_names: List[str]) -> List[str]:
    lines = text.splitlines()
    cleaned = [l.strip() for l in lines if l.strip()]
    joined_text = "\n".join(cleaned)

    pattern = '|'.join([re.escape(h) for h in section_names])

    split = re.split(rf"(?im)^[ \t]*({pattern})[ \t]*$", joined_text)
    if len(split) < 3:
        split = re.split(rf"(?i)({pattern})", joined_text)
        if len(split) < 3:
            return []

    content = split[2]

    all_stop_headers = (
        [h for headers in SECTION_HEADERS.values() for h in headers]
        + EXTRA_STOP_HEADERS
    )
    stop_pattern = '|'.join([re.escape(h) for h in all_stop_headers])
    stop_match = re.search(rf"(?i)({stop_pattern})", content)
    if stop_match:
        content = content[:stop_match.start()]

    return [l.strip() for l in content.strip().splitlines() if l.strip()]


def extract_skills(text: str) -> List[str]:
    lower_text = text.lower()
    found = set()
    for skill in SKILLS:
        if re.search(rf'\b{re.escape(skill.lower())}\b', lower_text):
            found.add(skill)
    return list(found)


def extract_education_section(text: str) -> List[str]:
    raw_lines = extract_section(text, SECTION_HEADERS["education"])
    cleaned = []
    for line in raw_lines:
        line = re.sub(r'^[•\-\*\u2022]+\s*', '', line)
        line = re.sub(r'Education[:\-\s]*', '', line, flags=re.I)
        if line.strip():
            cleaned.append(line.strip())
    return cleaned


def normalize_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip().replace('.', '')
    if date_str.lower() in ("present", "current"):
        return None
    # Expand 2-digit year → 4-digit (e.g. "April 24" → "April 2024", "Aug 22" → "Aug 2022")
    date_str = re.sub(
        r'(\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|'
        r'Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+)(\d{2})\b',
        lambda m: m.group(1) + ('20' if int(m.group(2)) <= 30 else '19') + m.group(2),
        date_str,
        flags=re.IGNORECASE
    )
    try:
        dt = date_parser.parse(date_str)
        return f"{dt.year}-{dt.month:02d}"
    except Exception:
        return None
    

def extract_date_range(text):
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            start, end = m.groups()
            return normalize_date(start), normalize_date(end)
    return None, None


def parse_with_llm(text: str) -> dict:
    prompt = f"""
You are an advanced ATS resume parser.

Extract structured data from the resume text below.

Return ONLY valid JSON (no explanation, no markdown, no backticks).

Schema:
{{
  "name": "",
  "email": "",
  "phone": "",
  "gender": "",
  "linkedin": "",
  "github": "",
  "portfolio": "",
  "skills": [],
  "experience": [
    {{
      "role": "",
      "company": "",
      "startDate": "",
      "endDate": "",
      "description": "",
      "projects": [
        {{
          "name": "",
          "description": "",
          "technologies": []
        }}
      ]
    }}
  ],
  "education": [
    {{
      "degree": "",
      "institution": "",
      "year": "",
      "board": "",
      "percentage": ""
    }}
  ],
  "projects": [
    {{
      "name": "",
      "description": "",
      "technologies": []
    }}
  ],
  "certifications": [
    {{
      "name": "",
      "issuer": "",
      "year": "",
      "url": ""
    }}
  ]
}}

Rules:
- For linkedin/github/portfolio: extract the URL even if it appears as plain text like "LinkedIn: linkedin.com/in/john" or "GitHub - github.com/john". Always return a full URL starting with https://.
- For experience[].projects: if the candidate mentions working on specific named projects WITHIN a job entry, list them here. These will be merged into the global projects list.
- For certifications: extract every certification, license, or course completion mentioned anywhere in the resume.
- For gender: extract only if explicitly stated (Male/Female/Other). Return empty string if not found.
- For dates: ALWAYS use full 4-digit year format "Month YYYY" (e.g. "August 2022", "April 2024"). 
  If the resume shows a 2-digit year like "Aug 22", expand it to "Aug 2022". 
  Use "Present" for current roles. Never return 2-digit years.
WORK EXPERIENCE RULES (strictly follow these):
- If the company line contains "As:" or "As:-" followed by a title 
  (e.g. "Millenium Intech Pvt Ltd As: - React Developer"), 
  split it: everything before "As:" is the company, everything after is the role.
- "role" must be the JOB TITLE only (e.g. "React Developer", "Senior Software Development Engineer", "SDE Intern"). Never put company name, dates, bullets, or technology lists in role.
- "company" must be the EMPLOYER NAME only (e.g. "Millenium Intech Pvt Ltd", "TCS", "Bluestock Fintech"). Never put role, dates, or descriptions in company.
- If a person worked at ONE company but on MULTIPLE projects with different date ranges, create ONE experience entry for that company — use the earliest startDate and the latest endDate (or "Present"). Do NOT create a separate experience entry per project.
- "startDate" and "endDate" must be dates only (e.g. "January 2022", "Present"). Never leave them empty if dates are visible in the resume.
- "description" should be a brief 1-2 sentence summary of responsibilities. Do not put bullet lists here.
- "projects" inside an experience entry: only fill this if the resume explicitly names a project within that job. Leave as [] otherwise.
- If the resume has no explicit 'Work Experience' section header but has a 'Professional Summary' 
  paragraph describing a role, extract the role and company from that summary as a work experience entry.
  Look for patterns like "X years of experience as [role] at [company]" or 
  "developer with experience in [company-type] building [tech]".
STRICT EXPERIENCE RULES:
- "role" = job title ONLY. Never include tech, dates, or bullets.
- "company" = employer name ONLY. Stop at the first comma if what follows looks like tech.
- Technologies at the end of an experience entry (e.g. "Technologies Used: ...") 
  belong to that entry — they are NOT a new experience entry.
- Do NOT create a new experience entry just because you see a "Technologies Used:" line.
- If multiple projects are listed under ONE employer, create ONE experience entry only.

PROJECT RULES (strictly follow these):
- Some resumes write projects like:
    "Language: Java, Spring Boot, MySQL"  ← this is the tech stack, NOT the project name
    "Description: ..."                    ← this has the real description
    The project name in this case should be extracted from the Description text 
    (e.g. "CABA" or "Swabi"), NOT from the Language line.
- Never use a line starting with "Language:" as the project name.
- Always extract technologies from the "Language:" line into the technologies array.
- "name" must be the project title ONLY. If the resume writes "Formify – Full-Stack Form Builder Next.js, React, Prisma, Tailwind", the name is "Formify" or at most "Formify – Full-Stack Form Builder". Never include technology names in the project name.
- "technologies" must be a list of tech strings extracted from the project line or its bullets (e.g. ["Next.js", "React", "Prisma", "Tailwind"]). Always populate this — never leave it as [].
- "description" should be the project description text from the bullets below the project heading.
- If the project heading line contains both a name and tech stack separated by "–", "-", "|", or just spaces after the title, split them: everything before the separator is the name, everything after goes into technologies.

Resume Text:
{text[:12000]}
"""

    max_retries = 3
    retry_delays = [60, 120, 180] 
    for attempt in range(max_retries):
        try:
            response = groq_client.chat.completions.create(
                #model="llama-3.3-70b-versatile",
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                timeout=30
            )
            content = response.choices[0].message.content
            try:
                return json.loads(content)
            except Exception:
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))
            return {}

        except Exception as e:
            err = str(e)
            if "429" in err and attempt < max_retries - 1:
                wait = retry_delays[attempt]
                print(f"[LLM RATE LIMIT] attempt {attempt+1}/{max_retries}, waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                print(f"[LLM ERROR]: {e}")
                break

    return {}


def extract_projects_from_experience(llm_experiences: list) -> list:
    
    extracted = []
    for exp in llm_experiences:
        if not isinstance(exp, dict):
            continue
        inner_projects = exp.get("projects") or []
        company = exp.get("company", "")
        role    = exp.get("role", "")
        for proj in inner_projects:
            if not isinstance(proj, dict) or not proj.get("name"):
                continue
            # Enrich description with context if description is empty
            desc = proj.get("description", "")
            if not desc and (company or role):
                desc = f"Worked on this project at {company} as {role}.".strip(". ") + "."
            extracted.append({
                "name":        proj.get("name", ""),
                "description": desc,
                "technologies": proj.get("technologies") or [],
            })
    return extracted



def build_certifications_from_llm(llm_certs: list) -> list:
    result = []
    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    for cert in llm_certs:
        if not isinstance(cert, dict):
            continue
        name = cert.get("name", "").strip()
        if not name:
            continue
        result.append({
            "certificationId": None,
            "name":   name,
            "issuer": cert.get("issuer", "") or "",
            "year":   cert.get("year", "")   or "",
            "url":    cert.get("url", "")    or "",
            "createdAt": now_str,
            "updatedAt": now_str,
        })
    return result


def parse_certifications_from_text(cert_lines: list) -> list:
    """Fallback: convert raw certification lines into structured dicts."""
    result = []
    now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    for line in cert_lines:
        line = line.strip()
        if not line:
            continue
        year_match = re.search(r'\b(20\d{2}|19\d{2})\b', line)
        year = year_match.group(0) if year_match else ""
        name = re.sub(r'\b(20\d{2}|19\d{2})\b', '', line).strip(" -|,")
        if name:
            result.append({
                "certificationId": None,
                "name":   name,
                "issuer": "",
                "year":   year,
                "url":    "",
                "createdAt": now_str,
                "updatedAt": now_str,
            })
    return result



def parse_resume_text(text: str):
    name  = extract_name(text)
    emails = re.findall(EMAIL_REGEX, text)
    email  = emails[0] if emails else None

    phones = extract_phone_numbers(text)
    if not phones:
        fallback_phones = [
            p for p in re.findall(BASIC_PHONE_REGEX, text)
            if len(re.sub(r'\D', '', p)) >= 10
        ]
        phones = fallback_phones
    phone = phones[0] if phones else None

    skills        = extract_skills(text)
    experience    = extract_section(text, SECTION_HEADERS["experience"])
    all_lines     = [l.strip() for l in text.splitlines() if l.strip()]
    work_experiences = parse_work_experiences(all_lines)
    education     = extract_education_section(text)
    projects      = extract_section(text, SECTION_HEADERS["projects"])
    certifications = extract_section(text, SECTION_HEADERS["certifications"])

    profile_urls  = extract_profile_urls(text)

    return {
        "name":           name,
        "email":          email,
        "phone":          phone,
        "skills":         skills,
        "experience":     experience,
        "work_experiences": work_experiences,
        "education":      education,
        "projects":       projects,
        "certifications": certifications,
        "linkedin":       profile_urls["linkedin"],
        "github":         profile_urls["github"],
        "portfolio":      profile_urls["portfolio"],
        "raw_text":       sanitize_text(text),
    }


def split_name(full_name: Optional[str]):
    if not full_name:
        return None, None
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_education_items(education_lines: List[str]):
    edu_list = []
    i = 0

    degree_map = {
        r"\bB\.?TECH\b": "Bachelor of Technology",
        r"\bB\.?E\.?\b": "Bachelor of Engineering",
        r"\bM\.?TECH\b": "Master of Technology",
        r"\bM\.?E\.?\b": "Master of Engineering",
        r"\bMCA\b": "Master of Computer Applications",
        r"\bBCA\b": "Bachelor of Computer Applications",
        r"\bB\.?SC\s+I\.?T\b": "B.Sc. in Information Technology",
        r"\bM\.?SC\s+I\.?T\b": "M.Sc. in Information Technology",
        r"\bMBA\b": "Master of Business Administration",
        r"\bB\.?COM\b": "Bachelor of Commerce",
        r"\bB\.?SC\b": "Bachelor of Science",
        r"\bM\.?SC\b": "Master of Science",
        r"\bC\.?A\.?\b": "Chartered Accountant",
        r"\bPH\.?D\b": "Doctor of Philosophy",
        r"\bB\.?A\.?\b": "Bachelor of Arts",
        r"\bM\.?A\.?\b": "Master of Arts",
        r"\bINTERMEDIATE\b|\b12TH\b|\bHSC\b": "Intermediate (12th)",
        r"\b10TH\b|\bHIGHSCHOOL\b|\bSSC\b": "High School (10th)",
    }

    while i < len(education_lines):
        line = education_lines[i].strip()

        if not line or any(kw in line.lower() for kw in ["internship", "experience", "---"]):
            i += 1
            continue

        context_window = " ".join(education_lines[i:i+3]).replace('\n', ' ')

        degree = ""
        for pattern, full_name in degree_map.items():
            if re.search(pattern, context_window, re.I):
                degree = full_name
                break

        uni_match = re.search(r'([^,0-9]+(?:University|Institute|College|Academy|School))', context_window, re.I)
        uni_name = uni_match.group(1).strip() if uni_match else ""

        if degree or uni_name:
            edu_type = "GRADUATION"
            degree_upper = degree.upper()

            if any(x in degree_upper for x in ["MASTER", "M.TECH", "MBA", "MCA", "M.SC", "M.A", "M.E"]):
                edu_type = "POST_GRADUATION"
            elif "PH.D" in degree_upper or "PHILOSOPHY" in degree_upper:
                edu_type = "DOCTORATE"
            elif any(x in degree_upper for x in ["10TH", "12TH", "SCHOOL", "INTERMEDIATE", "SSC", "HSC"]):
                edu_type = "SCHOOLING"
            elif not degree and "School" in uni_name:
                edu_type = "SCHOOLING"

            years = re.findall(r'\b(20\d{2}|19\d{2})\b', context_window)
            year = max(years) if years else ""

            edu_list.append({
                "educationId": None,
                "type": edu_type,
                "institutionName": uni_name,
                "passingYear": year,
                "degreeName": degree,
                "board": "",
                "percentage": "",
                "university": uni_name,
                "createdAt": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S"),
                "updatedAt": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S"),
                "educationStatus": "COMPLETED",
            })
            i += 2
        else:
            i += 1

    return edu_list


def parse_work_experiences(lines, candidateId=None):
    work_experiences = []

    date_range_pattern = re.compile(
        r'(?P<start>(?:January|February|March|April|May|June|July|August|September|October|November|December|'
        r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4})\s*[-–\u2014to/]+\s*'
        r'(?P<end>Present|Current|'
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December|'
        r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4})',
        re.I,
    )

    action_verbs = [
        "Managed", "Led", "Developed", "Prepared", "Assisted",
        "Monitored", "Handled", "Maintained", "Conducted"
    ]

    experience_headers = [
        "work experience", "professional experience", "employment history",
        "career history", "work history", "experience",
        "internship experience", "internship & experience",
        "internship/experience", "internship / experience",
        "internship",
    ]

    stop_headers = [
        "skills", "education", "certifications", "projects",
        "achievements", "personal details", "declaration",
        "extra curricular", "volunteer", "hobbies", "references",
        "technical skills", "professional summary", "summary",
    ]

    def _normalize(d):
        if not d or str(d).lower() in ("present", "current"):
            return None
        d = re.sub(
            r'^([A-Za-z]+)\s+(\d{2})$',
            lambda m: f"{m.group(1)} {2000 + int(m.group(2))}",
            d.strip()
        )
        try:
            dt = date_parser.parse(d, default=datetime(2000, 1, 1))
            return f"{dt.year}-{dt.month:02d}"
        except Exception:
            return normalize_date(d)

    def _is_bullet_or_description(line):
        return (
            line.startswith(("•", "-", "*", "·", "○")) or
            any(line.lower().startswith(v.lower()) for v in action_verbs) or
            # tech/tools lines
            re.match(r'(?i)^(technologies used|tools used|tech stack|languages?)\s*:', line) is not None
        )


    def _is_experience_header(line):
        return any(line.lower().strip() == h for h in experience_headers)

    def _is_stop_header(line):
        return any(line.lower().strip() == h for h in stop_headers)

    def _looks_like_company_or_role(line):
        if not line:
            return False
        if _AS_ROLE_PATTERN.match(line.strip()):
            return True
        if _is_bullet_or_description(line):
            return False
        if _is_tech_string(line):
            return False
        if len(line.split()) > 10:
            return False
        return True

    in_experience = False
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if _is_experience_header(line):
            in_experience = True
            i += 1
            continue

        if in_experience and _is_stop_header(line):
            in_experience = False
            i += 1
            continue

        if not in_experience:
            i += 1
            continue

        dr = date_range_pattern.search(line)
        if dr:
            start, end = dr.group("start"), dr.group("end")

            # Walk back to find company/role — skip bullets and tech lines
            context = []
            back_idx = i - 1
            while back_idx >= 0 and len(context) < 3:
                prev_line = lines[back_idx].strip()
                if not prev_line:
                    back_idx -= 1
                    continue
                if _is_experience_header(prev_line) or _is_stop_header(prev_line):
                    break
                if not _looks_like_company_or_role(prev_line):
                    back_idx -= 1
                    continue
                context.append(prev_line)
                back_idx -= 1

            role = ""
            company = ""

            if len(context) >= 2:
                company = context[0]
                role = context[1]
            elif len(context) == 1:
                company = context[0]

            # Also check if date line itself has company info after stripping the date
            remaining_text = date_range_pattern.sub("", line).strip(", |–-\u2014").strip()
            if remaining_text and _looks_like_company_or_role(remaining_text):
                if not company:
                    company = remaining_text
                elif remaining_text.lower() not in company.lower():
                    company = f"{company}, {remaining_text}"

            # Apply the same post-processing as LLM path
            entry = {
                "candidateId":      candidateId,
                "workExperienceId": None,
                "role":             role,
                "companyName":      company,
                "startDate":        _normalize(start),
                "endDate":          _normalize(end),
                "isCurrentlyWorking": bool(end and end.lower() in ("present", "current")),
            }
            entry = _split_role_company(entry)
            entry = _clean_work_experience(entry)

            if entry.get("companyName"):
                work_experiences.append(entry)

        i += 1

    return work_experiences

def parse_projects(lines, candidateId=None):
    projects = []
    proj_id = 1
    current_proj = None

    date_pattern = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}', re.I)
    tools_pattern = re.compile(r'Tools\s+Used\s*:\s*(.+)', re.I)

    bad_lines = {
        "technical skills", "extra curricular", "strength and weakness",
        "technology stacks", "last updated", "page", "programming languages",
        "design and development tools", "web technologies", "databases",
        "cloud platforms", "volunteer work", "reading books", "education",
        "certifications", "interests", "hobbies"
    }

    def _normalize(d):
        if not d or str(d).lower() in ("present", "current"):
            return None
        try:
            dt = date_parser.parse(d)
            return f"{dt.year}-{dt.month:02d}"
        except Exception:
            return None

    def clean_text(line):
        return re.sub(r'\s+', ' ', line).strip()

    def save_current():
        nonlocal current_proj, proj_id
        if not current_proj:
            return
        name = current_proj.get("projectName")
        desc_list = current_proj.get("description", [])
        if not name or (not desc_list and not current_proj.get("technologies")):
            current_proj = None
            return
        description = " ".join(desc_list).strip()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        projects.append({
            "candidateId": candidateId,
            "projectId": None,
            "projectName": name,
            "client": None,
            "startDate": _normalize(current_proj.get("startDate")),
            "endDate": _normalize(current_proj.get("endDate")),
            "role": None,
            "technologies": current_proj.get("technologies", []),
            "description": description if description else None,
            "projectIndustry": None,
            "duration": None,
            "projectUrl": None,
            "projectImages": [],
        })
        proj_id += 1
        current_proj = None

    def is_heading(line, raw_line=None):
        l = line.lower()
        if any(bad in l for bad in bad_lines):
            return False
        if len(l.split()) > 12:
            return False
        action_verbs = (
            "developed", "built", "created", "implemented", "used", "designed", "integrated",
            "engineered", "coded", "programmed", "deployed", "delivered", "shipped", "constructed",
            "configured", "assembled"
        )
        if any(l.startswith(v) for v in action_verbs):
            return False
        if line.strip().endswith(".") and len(l.split()) > 4:
            return False
        if line.startswith(("•", "-")):
            return False
        return 1 < len(l.split())

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = clean_text(raw_line.strip("•- \t"))
        if not line:
            i += 1
            continue

        lower = line.lower()

        if any(bad in lower for bad in bad_lines):
            save_current()
            i += 1
            continue

        m = tools_pattern.search(line)
        if m:
            if not current_proj:
                current_proj = {
                    "projectName": f"Project {proj_id}",
                    "startDate": None, "endDate": None,
                    "technologies": [], "description": []
                }
            current_proj["technologies"] = [t.strip() for t in m.group(1).split(",") if t.strip()]
            i += 1
            continue

        if date_pattern.fullmatch(line):
            if current_proj:
                if not current_proj.get("startDate"):
                    current_proj["startDate"] = line
                else:
                    current_proj["endDate"] = line
            i += 1
            continue

        if is_heading(line, raw_line):
            save_current()

            proj_name = line
            proj_techs = []

            tech_split = re.split(r'\s{2,}|\s[\u2013\-\|]\s', line, maxsplit=1)
            if len(tech_split) == 2:
                candidate_name, candidate_techs = tech_split
                tech_tokens = [t.strip() for t in re.split(r'[,/]', candidate_techs) if t.strip()]
                if len(tech_tokens) >= 2 or any(
                    kw.lower() in candidate_techs.lower()
                    for kw in ("react", "node", "python", "java", "next", "vue", "django",
                               "spring", "typescript", "javascript", "tailwind", "prisma",
                               "mongodb", "firebase", "aws", "docker", "flask", "express")
                ):
                    proj_name  = candidate_name.strip()
                    proj_techs = tech_tokens

            current_proj = {
                "projectName": proj_name,
                "startDate": None, "endDate": None,
                "technologies": proj_techs, "description": []
            }
            dm = date_pattern.search(line)
            if dm:
                current_proj["startDate"] = dm.group()
            i += 1
            continue

        if current_proj:
            text = "GitHub Link" if "github.com" in lower else line
            current_proj["description"].append(text)

        i += 1

    save_current()
    return projects



def calculate_parsability_score(text: str) -> dict:
    if not text.strip():
        return {"score": 0.0, "details": {}, "parsable": False}

    checks = {
        "name": bool(extract_name(text)),
        "email": bool(re.search(EMAIL_REGEX, text)),
        "phone": bool(extract_phone_numbers(text)),
        "skills": bool(extract_skills(text)),
        "education": bool(extract_education_section(text)),
        "experience": bool(extract_section(text, SECTION_HEADERS["experience"])),
    }

    score = (sum(1 for v in checks.values() if v) / len(checks)) * 100
    parsable = score >= 80

    return {
        "score":   round(score, 2),
        "details": checks,
        "parsable": parsable,
    }

 
def extract_hyperlinks_from_pdf(file_obj) -> dict:
    
    links = {"linkedin": None, "github": None, "portfolio": None, "other": []}
    try:
 
        if isinstance(file_obj, str):
            doc = fitz.open(file_obj)
        elif hasattr(file_obj, '_path'):
            doc = fitz.open(file_obj._path)
        elif hasattr(file_obj, 'name') and isinstance(file_obj.name, str):
            doc = fitz.open(file_obj.name)
        else:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            data = file_obj.read()
            doc = fitz.open(stream=data, filetype="pdf")
 
        for page in doc:
            for link in page.get_links():
                uri = link.get("uri", "")
                if not uri:
                    continue
                if isinstance(uri, bytes):
                    uri = uri.decode("utf-8", errors="ignore")
                uri = uri.strip()
                if not uri or uri.startswith("mailto:") or uri.startswith("tel:"):
                    continue
                if not uri.startswith("http"):
                    uri = "https://" + uri
 
                if "linkedin.com" in uri and not links["linkedin"]:
                    links["linkedin"] = uri
                elif "github.com" in uri and not links["github"]:
                    links["github"] = uri
                elif not links["portfolio"] and any(
                    kw in uri.lower()
                    for kw in ("portfolio", "netlify", "vercel", "github.io")
                ):
                    links["portfolio"] = uri
                else:
                    links["other"].append(uri)
 
        doc.close()
 
    except Exception as e:
        print(f"[WARN] PDF hyperlink extraction failed: {e}")
 
    return links


_TECH_KEYWORDS = {
    "lambda", "api gateway", "sns", "sqs", "s3", "kafka", "terraform",
    "docker", "kubernetes", "redis", "mongodb", "sql", "postgresql",
    "mysql", "node", "nodejs", "react", "angular", "vue", "python",
    "java", "spring", "aws", "azure", "gcp", "typescript", "javascript",
    "graphql", "nestjs", "express", "django", "flask", "hibernate",
    "firebase", "dynamodb", "elasticsearch", "rabbitmq", "nginx",
    "jenkins", "webrtc", "sap hana",
}


def _is_tech_string(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    for kw in _TECH_KEYWORDS:
        if lower.startswith(kw):
            return True
    if text.count(",") >= 2:  
        return True
    tech_hits = sum(1 for kw in _TECH_KEYWORDS if kw in lower)
    if tech_hits >= 1:  
        return True
    return False

_TITLE_KEYWORDS = [
    "intern", "engineer", "developer", "manager", "analyst",
    "architect", "designer", "lead", "consultant", "associate",
    "sde", "swe", "devops", "qa", "tester", "director", "officer",
    "specialist", "coordinator", "executive", "trainee",
]

_AS_ROLE_PATTERN = re.compile(r'^.+?\s+[Aa]s\s*:\s*-?\s*.+$')

def _split_role_company(exp: dict) -> dict:
    role    = exp.get("role", "") or ""
    company = exp.get("companyName", "") or ""

    company = re.sub(r'^[^A-Z]*?,\s*', '', company).strip()

    as_match = re.search(r'^(.+?)\s+[Aa]s\s*[:\-]+\s*(.+)$', company)
    if as_match:
        candidate_company = as_match.group(1).strip()
        candidate_role    = as_match.group(2).strip()
        if candidate_company and candidate_role:
            exp["companyName"] = candidate_company
            exp["role"]        = candidate_role
            return exp

    if not role and company:
        for sep in [" – ", " — ", " - ", " | "]:
            if sep in company:
                left, right = company.split(sep, 1)
                left  = left.strip()
                right = re.sub(r'\s*\([^)]*\)\s*$', '', right.strip()).strip()
                if any(kw in left.lower() for kw in _TITLE_KEYWORDS):
                    exp["role"]        = left
                    exp["companyName"] = right
                    return exp

    if role and _is_tech_string(role):
        exp["role"] = ""

    exp["companyName"] = company
    return exp


def _clean_work_experience(exp: dict) -> dict:
    company = exp.get("companyName", "") or ""

    company = re.sub(r'^[^A-Z]*?,\s*', '', company).strip()
    if not exp.get("role") and company:
        for sep in [" – ", " — ", " - ", " | "]:
            if sep in company:
                left, right = company.split(sep, 1)
                left  = left.strip()
                right = re.sub(r'\s*\([^)]*\)\s*$', '', right.strip()).strip()
                if any(kw in left.lower() for kw in _TITLE_KEYWORDS):
                    exp["role"]        = left
                    exp["companyName"] = right
                    return exp

    if _is_tech_string(company):
        parts    = [p.strip().rstrip(".") for p in company.split(",")]
        non_tech = [p for p in parts if p and not _is_tech_string(p) and len(p) > 1]
        company  = non_tech[-1] if non_tech else ""

    exp["companyName"] = company
    return exp







