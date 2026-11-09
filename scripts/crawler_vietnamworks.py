import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from scripts.crawler_base import BaseCrawler, absolute, main, norm, split_list, text_of

SOURCE = "vietnamworks"
SITE = "https://www.vietnamworks.com"
BASE = f"{SITE}/viec-lam?g=5"
LIST_READY = ".view_job_item h2 a"
DETAIL_READY = "h1"
PLACEHOLDER = ".job-item-placeholder"
SALARY_HIDDEN = ("thương lượng", "negotiable")

INFO_LABELS = {
    "ngày đăng": "date_posted_text", "date posted": "date_posted_text",
    "cấp bậc": "level", "job level": "level",
    "ngành nghề": "job_function", "job function": "job_function",
    "kỹ năng": "skills_tags", "skills": "skills_tags",
    "lĩnh vực": "job_industry", "industry": "job_industry",
    "ngôn ngữ trình bày hồ sơ": "cv_language", "preferred language for applications": "cv_language",
    "số năm kinh nghiệm tối thiểu": "experience", "minimum years of experience": "experience",
    "quốc tịch": "nationality", "nationality": "nationality",
    "trình độ học vấn": "education", "education": "education",
    "độ tuổi": "age", "age": "age",
    "giới tính": "gender", "gender": "gender",
    "loại hình làm việc": "working_type", "working type": "working_type",
    "số lượng tuyển dụng": "openings", "number of openings": "openings",
    "ngày làm việc": "working_days", "working days": "working_days",
    "giờ làm việc": "working_hours", "working hours": "working_hours",
}
LIST_FIELDS = {"skills_tags"}
SECTIONS = {
    "mô tả công việc": "description", "job description": "description",
    "yêu cầu công việc": "requirements", "job requirements": "requirements",
}
ADDRESS_TITLES = ("địa điểm làm việc", "job locations", "work location")


def parse_info(soup) -> dict:
    out = {field: None for field in dict.fromkeys(INFO_LABELS.values())}
    for label in soup.select("label"):
        field = INFO_LABELS.get(norm(label.get_text(" ", strip=True)))
        value = label.find_next_sibling("p")
        if not field or not value or out[field] is not None:
            continue
        text = " ".join(value.get_text(" ", strip=True).split())
        out[field] = split_list(text) if field in LIST_FIELDS else text
    out["skills_tags"] = out["skills_tags"] or []
    return out


def parse_sections(soup) -> dict:
    out = {name: None for name in dict.fromkeys(SECTIONS.values())}
    for h2 in soup.select("h2"):
        field = SECTIONS.get(norm(h2.get_text(" ", strip=True)))
        if not field or out[field] is not None:
            continue
        blocks = h2.parent.find_all("div", recursive=False)
        if blocks:
            out[field] = blocks[-1].get_text("\n", strip=True)
    return out


def parse_benefits(soup) -> dict:
    tags, lines = [], []
    for item in soup.select("[data-benefit-name]"):
        title = text_of(item, "[name='title']")
        title_el = item.select_one("[name='title']")
        if title_el:
            title_el.extract()
        detail = " ".join(item.get_text(" ", strip=True).split())
        if title:
            tags.append(title)
        lines.append(f"{title}: {detail}" if title and detail else title or detail)
    return {"benefit_tags": tags, "benefits": "\n".join(l for l in lines if l) or None}


def parse_addresses(soup) -> list[str]:
    for h2 in soup.select("h2"):
        if norm(h2.get_text(" ", strip=True)) in ADDRESS_TITLES:
            box = h2.find_next_sibling()
            if box:
                return [line for line in box.get_text("\n", strip=True).split("\n") if line]
    return []


def parse_salary(soup) -> str | None:
    h1 = soup.select_one("h1")
    label = h1.find_next("span", attrs={"name": "label"}) if h1 else None
    return " ".join(label.get_text(" ", strip=True).split()) if label else None


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
    if isinstance(salary_value, str) and salary_value.strip().lower() in SALARY_HIDDEN:
        salary_value = None
    org = data.get("hiringOrganization") or {}
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
        "industry": data.get("industry"),
        "skills": split_list(data.get("skills")),
        "location_regions": list(dict.fromkeys(r for r in regions if r)),
        "ld_company_name": org.get("name"),
        "ld_company_url": org.get("sameAs"),
        "ld_addresses": [loc.get("address", {}).get("streetAddress") for loc in locations],
    }


class VietnamWorksCrawler(BaseCrawler):
    source = SOURCE

    def list_url(self, page: int) -> str:
        return BASE if page == 1 else f"{BASE}&page={page}"

    def is_list_url(self, url: str) -> bool:
        return "/viec-lam?" in url

    def after_open(self, url: str) -> None:
        if self.is_list_url(url):
            if self.wait_for(LIST_READY):
                self.scroll_until_loaded()
        else:
            self.wait_for(DETAIL_READY)
            self.sb.sleep(1)

    def scroll_until_loaded(self, max_rounds: int = 40) -> None:
        for _ in range(max_rounds):
            left = self.sb.execute_script(f"return document.querySelectorAll('{PLACEHOLDER}').length")
            if not left:
                return
            self.sb.execute_script("window.scrollBy(0, 1000)")
            self.sb.sleep(0.8)
        print("  Cuộn hết số lần cho phép mà vẫn còn ô chưa tải")

    def parse_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.select(".view_job_item h2 a"):
            href = absolute(a.get("href"), SITE)
            if href and href not in links:
                links.append(href)
        return links

    def job_id_from_url(self, url: str | None) -> str | None:
        match = re.search(r"-(\d+)-j[dv]$", url or "")
        return match.group(1) if match else None

    def parse_detail(self, html: str, url: str | None = None) -> dict | None:
        soup = BeautifulSoup(html, "lxml")
        ld = parse_jsonld(soup)

        job_title = text_of(soup, "h1")
        if not job_title:
            return None

        info = parse_info(soup)

        return {
            "source": SOURCE,
            "job_id": self.job_id_from_url(url),
            "job_url": url,
            "job_title": job_title,
            "company_name": ld.get("ld_company_name"),
            "company_url": ld.get("ld_company_url"),
            "salary": parse_salary(soup),
            **info,
            **parse_sections(soup),
            **parse_benefits(soup),
            "addresses": parse_addresses(soup) or [a for a in ld.get("ld_addresses", []) if a],
            **{k: v for k, v in ld.items() if not k.startswith("ld_")},
            "crawled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    main(VietnamWorksCrawler)
