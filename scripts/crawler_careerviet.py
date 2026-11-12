import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from scripts.crawler_base import BaseCrawler, absolute, main, norm, split_list, text_of

SOURCE = "careerviet"
SITE = "https://careerviet.vn"
BASE = f"{SITE}/viec-lam/cntt-phan-cung-mang-cntt-phan-mem-c63,1"
BOX_LABELS = {
    "địa điểm": "place", "nơi làm việc": "place", "location": "place",
    "ngày cập nhật": "date_updated", "updated": "date_updated",
    "ngành nghề": "job_categories", "industry": "job_categories",
    "hình thức": "employment_type", "job type": "employment_type",
    "lương": "salary", "salary": "salary",
    "kinh nghiệm": "experience", "experience": "experience",
    "cấp bậc": "level", "level": "level",
    "hết hạn nộp": "deadline", "expiry date": "deadline",
}
SECTIONS = {
    "phúc lợi": "benefit_tags", "benefits": "benefit_tags",
    "mô tả công việc": "description", "job description": "description",
    "yêu cầu công việc": "requirements", "job requirements": "requirements", "job requirement": "requirements",
    "địa điểm làm việc": "addresses", "job location": "addresses", "work location": "addresses",
    "thông tin khác": "other_info", "other information": "other_info",
}
OTHER_LABELS = {
    "bằng cấp": "education", "degree": "education",
    "thời gian thử việc": "probation", "probation period": "probation",
    "độ tuổi": "age", "age": "age",
    "thời gian làm việc": "working_hours", "working hours": "working_hours",
    "hình thức": "employment_type", "job type": "employment_type",
    "lương": "salary", "salary": "salary",
}


def parse_boxes(soup) -> dict:
    out = {}
    for icon in soup.select(".material-icons"):
        icon.decompose()
    items = ".detail-box li, .detail-box .map, .info-career ul.info li, tr:has(> td.name), .job-overview-item"
    for item in soup.select(items):
        label = text_of(item, "td.name") or text_of(item, ".overview-label") or text_of(item, "strong, b")
        field = BOX_LABELS.get(norm(label))
        if not field or field in out:
            continue
        if field == "job_categories":
            value = [a.get_text(" ", strip=True) for a in item.select("p a, .value a, td.content a, .overview-value a")]
        else:
            value = text_of(item, "td.content") or text_of(item, ".overview-value") or text_of(item, "p, .value")
        if value:
            out[field] = value
    out.setdefault("place", text_of(soup, ".meta-location-text"))
    out.setdefault("salary", text_of(soup, ".meta-salary"))
    out = {k: v for k, v in out.items() if v}
    if out.get("salary"):
        out["salary"] = re.sub(r"^(lương|salary)\s*:\s*", "", out["salary"], flags=re.I)
    return out


def parse_other_info(block) -> dict:
    out = {}
    for li in block.select("li"):
        label, _, value = li.get_text(" ", strip=True).partition(":")
        field = OTHER_LABELS.get(norm(label))
        if field and field not in out:
            out[field] = value.strip() or None
    return out


def parse_sections(soup) -> dict:
    out = {"benefit_tags": [], "description": None, "requirements": None, "addresses": []}
    other = {}
    for row in soup.select(".detail-row"):
        field = SECTIONS.get(norm(text_of(row, ".detail-title")))
        if not field:
            continue
        title = row.select_one(".detail-title")
        if field == "benefit_tags":
            out[field] = [li.get_text(" ", strip=True) for li in row.select("li")]
        elif field == "addresses":
            out[field] = [s.get_text(" ", strip=True) for s in row.select(".place-name span")]
        elif field == "other_info":
            other = parse_other_info(row)
        elif out[field] is None:
            title.extract()
            out[field] = row.get_text("\n", strip=True)
    return {**out, "other": other}


def parse_job_tags(soup) -> list[str]:
    return [a.get_text(" ", strip=True) for a in soup.select(".job-tags li a")]


def parse_jsonld(soup) -> dict:
    data = {}
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            item = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("@type") == "JobPosting":
            data = item
            break
    if not data:
        return {}

    locations = data.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    cities = [loc.get("address", {}).get("addressLocality") for loc in locations]

    salary = (data.get("baseSalary") or {}).get("value") or {}
    org = data.get("hiringOrganization") or {}
    exp = data.get("experienceRequirements") or {}
    edu = data.get("educationRequirements") or {}
    emp = data.get("employmentType") or []
    if isinstance(emp, str):
        emp = [emp]

    return {
        "date_posted": data.get("datePosted"),
        "valid_through": data.get("validThrough"),
        "employment_type_code": [e.strip('"') for e in emp],
        "salary_value": salary.get("value"),
        "salary_min": salary.get("minValue"),
        "salary_max": salary.get("maxValue"),
        "salary_unit": salary.get("unitText"),
        "salary_currency": (data.get("baseSalary") or {}).get("currency"),
        "experience_months": exp.get("monthsOfExperience") if isinstance(exp, dict) else None,
        "education_code": edu.get("credentialCategory") if isinstance(edu, dict) else None,
        "industry": data.get("industry"),
        "skills": split_list(data.get("skills")),
        "location_regions": list(dict.fromkeys(c for c in cities if c)),
        "company_website": org.get("sameAs"),
        "ld_company_name": org.get("name"),
        "ld_company_url": org.get("url"),
        "ld_working_hours": data.get("workHours"),
        "ld_addresses": [loc.get("address", {}).get("streetAddress") for loc in locations],
    }


class CareerVietCrawler(BaseCrawler):
    source = SOURCE

    def list_url(self, page: int) -> str:
        if page == 1:
            return f"{BASE}-vi.html"
        return f"{BASE}-trang-{page}-vi.html"

    def parse_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.select(".title h2 a.job_link"):
            href = absolute(a.get("href"), SITE)
            if href and href not in links:
                links.append(href)
        return links

    def job_id_from_url(self, url: str | None) -> str | None:
        match = re.search(r"\.([0-9A-Za-z]+)\.html$", url or "")
        return match.group(1) if match else None

    def parse_detail(self, html: str, url: str | None = None) -> dict | None:
        soup = BeautifulSoup(html, "lxml")
        ld = parse_jsonld(soup)

        job_title = text_of(soup, ".job-desc h1.title") or text_of(soup, "h1") or text_of(soup, ".head-template .title h2")
        if not job_title:
            return None

        box = parse_boxes(soup)
        sections = parse_sections(soup)
        other = sections.pop("other")
        company_link = soup.select_one("a.job-company-name, .head-template a.company")

        return {
            "source": SOURCE,
            "job_id": self.job_id_from_url(url),
            "job_url": url,
            "job_title": job_title,
            "salary": box.get("salary") or other.get("salary"),
            "place": box.get("place"),
            "experience": box.get("experience"),
            "deadline": box.get("deadline"),
            "date_updated": box.get("date_updated"),
            "level": box.get("level"),
            "education": other.get("education"),
            "employment_type": box.get("employment_type") or other.get("employment_type"),
            "probation": other.get("probation"),
            "age": other.get("age"),
            "working_hours": other.get("working_hours") or ld.get("ld_working_hours"),
            "job_categories": box.get("job_categories", []),
            "job_tags": parse_job_tags(soup),
            "addresses": sections.pop("addresses") or [a for a in ld.get("ld_addresses", []) if a],
            **sections,
            "company_name": (company_link.get_text(" ", strip=True) if company_link else None) or ld.get("ld_company_name"),
            "company_url": absolute(company_link.get("href"), SITE) if company_link else ld.get("ld_company_url"),
            **{k: v for k, v in ld.items() if not k.startswith("ld_")},
            "crawled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    main(CareerVietCrawler)
