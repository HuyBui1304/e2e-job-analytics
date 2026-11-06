import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from scripts.crawler_base import BaseCrawler, absolute, main, norm, split_list, text_of

SOURCE = "itviec"
SITE = "https://itviec.com"
BASE = f"{SITE}/viec-lam-it"
SALARY_HIDDEN = ("đăng nhập", "sign in", "you'll love it")

HEADER_TAGS = {
    "kỹ năng": "skills_tags", "skills": "skills_tags",
    "chuyên môn": "job_expertise", "job expertise": "job_expertise",
    "lĩnh vực": "job_domain", "job domain": "job_domain",
}
SECTIONS = {
    "3 lý do để gia nhập công ty": "top_reasons", "top 3 reasons to join us": "top_reasons",
    "mô tả công việc": "description", "job description": "description",
    "yêu cầu công việc": "requirements", "your skills and experience": "requirements",
    "tại sao bạn sẽ yêu thích làm việc tại đây": "benefits", "why you'll love working here": "benefits",
}
COMPANY_LABELS = {
    "mô hình công ty": "company_type", "company type": "company_type",
    "lĩnh vực công ty": "company_industry", "company industry": "company_industry",
    "quy mô công ty": "company_size", "company size": "company_size",
    "quốc gia": "company_country", "country": "company_country",
    "thời gian làm việc": "working_days", "working days": "working_days",
    "làm việc ngoài giờ": "overtime_policy", "overtime policy": "overtime_policy",
}


def parse_salary(soup) -> str | None:
    salary = text_of(soup, ".job-header-info .salary")
    if not salary or any(word in salary.lower() for word in SALARY_HIDDEN):
        return None
    return salary


def parse_header_info(soup) -> dict:
    info = soup.select_one(".job-show-info") or soup
    addresses = []
    for item in info.select(".d-inline-block"):
        if item.select_one("a[href*='google.com/maps']"):
            address = text_of(item, "span")
            if address and address not in addresses:
                addresses.append(address)
    working_type = None
    for item in info.select(".preview-header-item"):
        value = text_of(item, "span.ms-1")
        if value:
            working_type = value
            break
    return {"addresses": addresses, "working_type": working_type}


def parse_header_tags(soup) -> dict:
    out = {field: [] for field in dict.fromkeys(HEADER_TAGS.values())}
    for label in soup.select(".job-show-info .w-xl-fixed-100"):
        field = HEADER_TAGS.get(norm(label.get_text(" ", strip=True)))
        values = label.find_next_sibling("div")
        if field and values:
            out[field] = [t.get_text(" ", strip=True) for t in values.select(".itag")]
    return out


def parse_sections(soup) -> dict:
    out = {"top_reasons": [], "description": None, "requirements": None, "benefits": None}
    for block in soup.select(".job-content .paragraph"):
        title = block.find("h2")
        field = SECTIONS.get(norm(title.get_text(" ", strip=True))) if title else None
        if not field:
            continue
        if field == "top_reasons":
            out[field] = [li.get_text(" ", strip=True) for li in block.select("li")]
        elif out[field] is None:
            title.extract()
            out[field] = block.get_text("\n", strip=True)
    return out


def parse_company(soup) -> dict:
    box = soup.select_one(".job-show-employer-info")
    if not box:
        return {}
    out = {}
    for row in box.select(".row"):
        cols = row.select(".col")
        if len(cols) < 2:
            continue
        field = COMPANY_LABELS.get(norm(cols[0].get_text(" ", strip=True)))
        if field and field not in out:
            out[field] = " ".join(cols[1].get_text(" ", strip=True).split())
    link = box.select_one("h3 a")
    out["company_url"] = absolute(link.get("href"), SITE) if link else None
    return out


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
    regions = [loc.get("address", {}).get("addressRegion") for loc in locations]

    salary = (data.get("baseSalary") or {}).get("value") or {}
    salary_value = salary.get("value")
    if isinstance(salary_value, str) and any(word in salary_value.lower() for word in SALARY_HIDDEN):
        salary_value = None
    exp = data.get("experienceRequirements") or {}
    emp = data.get("employmentType") or []
    if isinstance(emp, str):
        emp = [emp]

    return {
        "date_posted": data.get("datePosted"),
        "valid_through": data.get("validThrough"),
        "employment_type_code": [e.strip('"') for e in emp],
        "salary_value": salary_value,
        "salary_min": salary.get("minValue"),
        "salary_max": salary.get("maxValue"),
        "salary_unit": salary.get("unitText"),
        "salary_currency": (data.get("baseSalary") or {}).get("currency"),
        "experience_months": exp.get("monthsOfExperience") if isinstance(exp, dict) else None,
        "industry": data.get("industry"),
        "skills": split_list(data.get("skills")),
        "location_regions": list(dict.fromkeys(r for r in regions if r)),
        "ld_addresses": [loc.get("address", {}).get("streetAddress") for loc in locations],
    }


class ITviecCrawler(BaseCrawler):
    source = SOURCE

    def list_url(self, page: int) -> str:
        return f"{BASE}?page={page}"

    def parse_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.select(".job-card h3 a"):
            href = absolute(a.get("href"), SITE)
            if href and href not in links:
                links.append(href)
        return links

    def job_id_from_url(self, url: str | None) -> str | None:
        match = re.search(r"/(?:viec-lam-it|it-jobs)/([^/?#]+)", url or "")
        return match.group(1) if match else None

    def parse_detail(self, html: str, url: str | None = None) -> dict | None:
        soup = BeautifulSoup(html, "lxml")
        ld = parse_jsonld(soup)

        job_title = text_of(soup, ".job-header-info h1") or text_of(soup, "h1")
        if not job_title:
            return None

        header = parse_header_info(soup)
        company = parse_company(soup)

        return {
            "source": SOURCE,
            "job_id": self.job_id_from_url(url),
            "job_url": url,
            "job_title": job_title,
            "company_name": text_of(soup, ".job-header-info .employer-name"),
            "salary": parse_salary(soup),
            "addresses": header["addresses"] or [a for a in ld.get("ld_addresses", []) if a],
            "working_type": header["working_type"],
            **parse_header_tags(soup),
            **parse_sections(soup),
            "company_url": company.get("company_url"),
            "company_type": company.get("company_type"),
            "company_industry": company.get("company_industry"),
            "company_size": company.get("company_size"),
            "company_country": company.get("company_country"),
            "working_days": company.get("working_days"),
            "overtime_policy": company.get("overtime_policy"),
            **{k: v for k, v in ld.items() if not k.startswith("ld_")},
            "crawled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    main(ITviecCrawler)
