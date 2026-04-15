import os
import re
import tempfile
import mimetypes
import uuid
from typing import List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import docx
import PyPDF2
import spacy
import phonenumbers
import boto3
from botocore.exceptions import NoCredentialsError
from fastapi import UploadFile
from PyPDF2 import PdfReader, PdfWriter
from dateutil import parser
from dateutil import parser as date_parser

nlp = spacy.load("en_core_web_sm")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION"),
)

EMAIL_REGEX       = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,10}\b'
BASIC_PHONE_REGEX = r'(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{3,5}'
LINKEDIN_REGEX    = r'(https?:\/\/(?:www\.)?linkedin\.com\/[A-Za-z0-9\-\_\/]+)'
SKYPE_REGEX       = r'(?i)(?:Skype\s*ID|Skype)\s*[:\-]?\s*([A-Za-z0-9\.\-_]+)'
AADHAAR_REGEX     = r'\b\d{4}\s?\d{4}\s?\d{4}\b'
PAN_REGEX         = r'\b[A-Z]{5}[0-9]{4}[A-Z]\b'
GENDER_REGEX = r'(?i)(?:gender|sex)\s*[:\-]?\s*(Male|Female|Other)\b'
DATE_PATTERNS     = [
    r'(\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\-]+\d{4})\s*(?:to|\-|\–)\s*(Present|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\-]+\d{4})',
    r'(\d{1,2}\/\d{4}|\d{4})\s*(?:to|\-|\–)\s*(Present|\d{1,2}\/\d{4}|\d{4})'
]

SKILLS = [
    "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go", "Rust", "Ruby",
    "PHP", "Perl", "Swift", "Kotlin", "R", "Scala", "Objective-C", "MATLAB", "Shell Scripting",
    "HTML", "CSS", "SASS", "LESS", "Bootstrap", "Tailwind CSS", "React", "Angular", "Vue.js",
    "Next.js", "Nuxt.js", "Node.js", "Express.js", "Svelte", "jQuery", "Django", "Flask",
    "FastAPI", "Spring Boot", "ASP.NET", "Laravel", "Symfony", "CodeIgniter", "Struts", "Gatsby",
    "PostgreSQL", "MySQL", "MariaDB", "SQLite", "MongoDB", "Cassandra", "Redis", "Elasticsearch",
    "Firebase", "DynamoDB", "CouchDB", "Neo4j", "Snowflake", "BigQuery", "Oracle Database",
    "Microsoft SQL Server", "AWS", "Azure", "Google Cloud", "IBM Cloud", "Heroku", "DigitalOcean",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "GitLab CI/CD", "GitHub Actions",
    "Bash", "Linux Administration", "Machine Learning", "Deep Learning",
    "Data Science", "Artificial Intelligence", "Natural Language Processing", "Computer Vision",
    "Data Analysis", "Data Visualization", "Pandas", "NumPy", "Matplotlib", "Seaborn",
    "TensorFlow", "Keras", "PyTorch", "Scikit-learn", "React Native", "Flutter",
    "Android Development", "iOS Development", "Ethical Hacking", "Penetration Testing",
    "Cybersecurity", "Agile", "Scrum", "Kanban", "Waterfall", "JIRA", "Confluence",
    "UI/UX Design", "Figma", "Adobe XD", "Sketch", "SEO", "SEM", "Google Analytics",
    "Accounting", "Financial Analysis", "Technical Writing", "Research",
    "Customer Service", "Sales", "Negotiation", "Public Speaking",
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
    "certifications": ["certifications", "certificates", "licenses"],
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
                    "ContentDisposition": f'inline; filename="{file.filename}"',
                },
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


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    return text.replace('\x00', '').strip()


def extract_name(text: str) -> Optional[str]:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blacklist = {'resume', 'cv', 'curriculum', 'developer', 'engineer', 'consultant', 'manager'}
    for line in lines:
        match = re.search(r"(?i)^name\s*[:\-]\s*([A-Za-z\s.]+)$", line)
        if match:
            candidate = match.group(1).strip()
            if 2 <= len(candidate.split()) <= 4:
                return candidate
    if lines:
        first_line = lines[0]
        words = first_line.split()
        if (2 <= len(words) <= 4 and
                all(w[0].isupper() for w in words if w.isalpha()) and
                all(w.lower() not in blacklist for w in words) and
                not any(char.isdigit() for char in first_line)):
            return first_line
    for line in lines[:5]:
        words = line.split()
        if (2 <= len(words) <= 4 and
                all(w[0].isupper() for w in words if w.isalpha()) and
                all(w.lower() not in blacklist for w in words) and
                not any(char.isdigit() for char in line)):
            return line
    doc = nlp(text[:800])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            if (2 <= len(name.split()) <= 4 and
                    not any(char.isdigit() for char in name) and
                    not any(word.lower() in blacklist for word in name.split())):
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


def parse_resume_text(text: str):
    name = extract_name(text)
    emails = re.findall(EMAIL_REGEX, text)
    email = emails[0] if emails else None
    phones = extract_phone_numbers(text)
    if not phones:
        fallback_phones = [
            p for p in re.findall(BASIC_PHONE_REGEX, text)
            if len(re.sub(r'\D', '', p)) >= 10
        ]
        phones = fallback_phones
    phone = phones[0] if phones else None
    skills = extract_skills(text)
    experience = extract_section(text, SECTION_HEADERS["experience"])
    education = extract_education_section(text)
    projects = extract_section(text, SECTION_HEADERS["projects"])
    certifications = extract_section(text, SECTION_HEADERS["certifications"])
    linkedin_match = re.search(LINKEDIN_REGEX, text)
    skype_match = re.search(SKYPE_REGEX, text)
    aadhaar_match = re.search(AADHAAR_REGEX, text)
    pan_match = re.search(PAN_REGEX, text)
    gender_match = re.search(GENDER_REGEX, text)

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "skills": skills,
        "experience": experience,
        "education": education,
        "projects": projects,
        "certifications": certifications,
        "linkedin": linkedin_match.group(0) if linkedin_match else None,
        "skypeId": skype_match.group(1) if skype_match else None,
        "aadharCardNumber": aadhaar_match.group(0) if aadhaar_match else None,
        "panCardNumber": pan_match.group(0) if pan_match else None,
        "gender": gender_match.group(1).capitalize() if gender_match else None,
        "raw_text": sanitize_text(text),
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
    buffer = []

    skip_keywords = [
        "internship", "declaration", "achievements", "personal details",
        "i hereby", "experience", "---"
    ]

    degree_map = {
        r"B\.?TECH":        "Bachelor of Technology",
        r"B\.?E\.?":        "Bachelor of Engineering",
        r"M\.?TECH":        "Master of Technology",
        r"M\.?E\.?":        "Master of Engineering",
        r"B\.?SC":          "Bachelor of Science",
        r"M\.?SC":          "Master of Science",
        r"MCA":             "Master of Computer Applications",
        r"MBA":             "Master of Business Administration",
        r"BCA":             "Bachelor of Computer Applications",
        r"B\.?COM":         "Bachelor of Commerce",
        r"M\.?COM":         "Master of Commerce",
        r"INTERMEDIATE":    "Intermediate (12th)",
        r"12TH":            "Intermediate (12th)",
        r"10TH":            "High School (10th)",
        r"HIGHSCHOOL":      "High School (10th)",
        r"HIGH\s+SCHOOL":   "High School (10th)",
        r"MATRICULATION":   "High School (10th)",
        r"PHD|PH\.D":       "Doctor of Philosophy",
    }

    def detect_degree(line):
        for pattern, full_name in degree_map.items():
            if re.search(pattern, line, re.I):
                return full_name
        return None

    def extract_university(line):
        uni_match = re.search(
            r'([\w\s\.]+(?:University|Institute of Technology|Institute|College|Academy|School)[^,\n]*)',
            line, re.I
        )
        if uni_match:
            return uni_match.group(1).strip(" ,.-•–()")
        return None

    def clean_institution(line, university):
        cleaned = re.sub(
            r'\b(Bachelor\s+of\s+Technology|Bachelor\s+of\s+Engineering|Master\s+of\s+Technology|'
            r'Master\s+of\s+Science|Bachelor\s+of\s+Science|Master\s+of\s+Computer\s+Applications|'
            r'Master\s+of\s+Business\s+Administration|Bachelor\s+of\s+Computer\s+Applications|'
            r'B\.?TECH|M\.?TECH|B\.?E\.?|M\.?E\.?|B\.?SC|M\.?SC|MCA|MBA|BCA|B\.?COM|M\.?COM|'
            r'INTERMEDIATE|12TH|10TH|HIGHSCHOOL|HIGH\s+SCHOOL|MATRICULATION|PHD|PH\.D|'
            r'SGPA|CGPA|PERCENTAGE|in\b)\b',
            '', line, flags=re.I
        )
        cleaned = re.sub(r'\b(20\d{2}|19\d{2})\b', '', cleaned)
        cleaned = re.sub(r'\d+(\.\d+)?\s*%', '', cleaned)
        if university:
            cleaned = cleaned.replace(university, '')
        cleaned = re.sub(
            r'\b(Computer\s+Science|Information\s+Technology|Electronics|Mechanical|Civil|'
            r'Electrical|Chemical|Biotechnology|Mathematics|Physics|Commerce|Arts|Science)\b',
            '', cleaned, flags=re.I
        )
        cleaned = re.sub(r'[()&]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(" ,.-•–/")
        return cleaned if len(cleaned.strip()) >= 3 else None

    def process_block(block, idx):
        line = " ".join(block).strip()

        if not line or len(line) < 5:
            return None
        if any(kw in line.lower() for kw in skip_keywords):
            return None

        year_matches = re.findall(r'(20\d{2}|19\d{2})', line)
        year = year_matches[-1] if year_matches else None

        degree = detect_degree(line)

        perc_match = re.search(
            r'(\d+(\.\d+)?)\s*%|\b(SGPA|CGPA)\s*[:\-]?\s*(\d+(\.\d+)?)', line, re.I
        )
        percentage = None
        if perc_match:
            percentage = perc_match.group(1) or perc_match.group(4)

        university = extract_university(line)
        institution = clean_institution(line, university)

        if not institution or len(institution.strip()) < 3:
            institution = university 

        if not institution or len(institution.strip()) < 3:
            return None

        return {
            "educationId":       None,
            "type":              "",
            "institutionName":   institution,
            "passingYear":       year,
            "degreeName":        degree or "",
            "board":             "",
            "percentage":        percentage or "",
            "university":        university or "",
            "createdAt":         datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S"),
            "updatedAt":         datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S"),
            "educationStatus":   "COMPLETED",
        }

    i = 0
    while i < len(education_lines):
        line = education_lines[i].strip()

        if re.match(r'^[\d\s\-–]+$', line) and re.search(r'(20\d{2}|19\d{2})', line):
            if edu_list:
                year_matches = re.findall(r'(20\d{2}|19\d{2})', line)
                edu_list[-1]["passingYear"] = year_matches[-1] if year_matches else None
            i += 1
            continue

        buffer.append(line)
        if len(buffer) == 2 or i == len(education_lines) - 1:
            result = process_block(buffer, i)
            if result:
                edu_list.append(result)
            buffer = []
        i += 1

    return edu_list

def parse_work_experiences(lines, candidateId=None):
    work_experiences = []
    exp_id = 1
    current_exp = None

    date_range_pattern = re.compile(
        r'(?P<start>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s?\d{4})\s*[-–to]+\s*'
        r'(?P<end>Present|Current|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s?\d{4})',
        re.I,
    )

    def _normalize(d):
        if not d or str(d).lower() in ("present", "current"):
            return None
        try:
            dt = parser.parse(d)
            return f"{dt.year}-{dt.month:02d}"
        except Exception:
            return None

    def clean_role_and_company(text):
        role = text
        company = None
        if " at " in text:
            role, company = text.split(" at ", 1)
        else:
            tokens = text.split()
            if len(tokens) > 2 and tokens[-1][0].isupper():
                company_tokens = []
                for t in reversed(tokens):
                    if t[0].isupper():
                        company_tokens.insert(0, t)
                    else:
                        break
                company = " ".join(company_tokens)
                role = text.replace(company, "").strip()
        return role.strip() or None, company.strip() if company else None

    def save_current():
        nonlocal current_exp, exp_id
        if current_exp and (current_exp.get("role") or current_exp.get("companyName") or current_exp.get("description")):
            if isinstance(current_exp.get("description"), list):
                desc = " ".join(current_exp["description"]).strip()
                current_exp["description"] = desc if desc else None
            if current_exp.get("role"):
                r, c = clean_role_and_company(current_exp["role"])
                if r:
                    current_exp["role"] = r
                if c and not current_exp.get("companyName"):
                    current_exp["companyName"] = c
            desc = current_exp.get("description") or ""
            current_exp["isRemote"] = "virtual" in desc.lower()
            if current_exp["isRemote"]:
                current_exp["description"] = desc.replace("Virtual", "").strip() or None
            if current_exp["role"] and current_exp["role"].startswith("/"):
                current_exp = None
                return
            current_exp.pop("description", None)
            current_exp.pop("isRemote", None)
            work_experiences.append(current_exp)
            exp_id += 1
        current_exp = None

    def is_header_line(line):
        common_verbs = ("built", "developed", "integrated", "improved", "contributed", "worked", "used", "created", "cleaned")
        words = line.lower().split()
        if not words:         
            return False
        if len(words) > 10:
            return False
        if any(words[0].startswith(v) for v in common_verbs):
            return False
        if line.startswith("•") or line.startswith("-"):
            return False
        return True

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.strip("•- \t").strip()
        if not line:
            i += 1
            continue

        dr = date_range_pattern.search(line)
        start = end = None
        if dr:
            start, end = dr.group("start"), dr.group("end")
            line = date_range_pattern.sub("", line).strip()

        if is_header_line(line) and ("," in line or dr or not current_exp):
            save_current()
            parts = [p.strip() for p in line.split(",")]
            role = parts[0] if parts else None
            company = ", ".join(parts[1:]) if len(parts) > 1 else None
            current_exp = {
                "candidateId": candidateId,
                "workExperienceId": None,
                "role": role,
                "companyName": company,
                "startDate": _normalize(start),
                "endDate": None if (end and end.lower() in ("present", "current")) else _normalize(end),
                "isCurrentlyWorking": bool(end and end.lower() in ("present", "current")),
            }
            if not company and i + 1 < len(lines):
                next_line = lines[i + 1].strip("•- \t").strip()
                next_dr = date_range_pattern.search(next_line)
                if (next_line and not next_dr and is_header_line(next_line)
                        and not next_line.lower().startswith(("built","developed","worked","implemented"))
                        and len(next_line.split()) <= 8):
                    current_exp["companyName"] = next_line
                    i += 2  
                    continue
            i += 1
            continue

        if dr:
            if not current_exp:
                current_exp = {
                    "candidateId": candidateId,
                    "workExperienceId": None,
                    "role": None,
                    "companyName": None,
                    "startDate": None,
                    "endDate": None,
                    "isCurrentlyWorking": False,
                }
            current_exp["startDate"] = _normalize(start)
            current_exp["endDate"] = None if (end and end.lower() in ("present", "current")) else _normalize(end)
            current_exp["isCurrentlyWorking"] = bool(end and end.lower() in ("present", "current"))
            i += 1
            continue

        if current_exp:
            current_exp.setdefault("description", []).append(line)
        i += 1

    save_current()
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
        "cloud platforms", "volunteer work", "reading books",
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
        if not current_proj.get("projectName") and not current_proj.get("description"):
            current_proj = None
            return
        if current_proj.get("projectName") and len(current_proj["projectName"].split()) <= 1:
            current_proj = None
            return
        if isinstance(current_proj.get("description"), list):
            desc = " ".join(current_proj["description"]).strip()
            current_proj["description"] = desc if desc else None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        projects.append({
            "candidateId": candidateId,
            "projectId": None,
            "projectName": current_proj.get("projectName"),
            "client": None,
            "clientLocation": None,
            "startDate": _normalize(current_proj.get("startDate")),
            "endDate": _normalize(current_proj.get("endDate")),
            "role": None,
            "technologies": current_proj.get("technologies", []),
            "description": current_proj.get("description"),
            "projectIndustry": None,
            "duration": None,
            "teamSize": None,
            "locationMode": None,
            "projectUrl": None,
            "projectImages": [],
            "createdAt": now,
            "updatedAt": now,
        })
        proj_id += 1
        current_proj = None

    def is_heading(line):
        l = line.lower()
        if any(bad in l for bad in bad_lines):
            return False
        if l.startswith(("•", "-", "developed", "built", "created", "implemented",
                         "used", "designed", "processed", "converted", "integrated",
                         "extracted", "worked", "collaborated", "contributed")):
            return False
        if line.strip().endswith("."):
            return False
        if len(l.split()) > 8:
            return False
        return 1 < len(l.split())

    i = 0
    while i < len(lines):
        line = clean_text(lines[i].strip("•- \t"))
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
                current_proj = {"projectName": f"Project {proj_id}", "startDate": None, "endDate": None, "technologies": [], "description": []}
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

        if is_heading(line):
            save_current()
            current_proj = {"projectName": line, "startDate": None, "endDate": None, "technologies": [], "description": []}
            dm = date_pattern.search(line)
            if dm:
                current_proj["startDate"] = dm.group()
            i += 1
            continue

        if current_proj:
            text = "GitHub Link" if "github" in lower or "link" in lower else line
            current_proj.setdefault("description", []).append(text)
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
        "score":    round(score, 2),
        "details":  checks,
        "parsable": parsable,
    }