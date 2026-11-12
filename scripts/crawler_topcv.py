import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from scripts.crawler_base import BaseCrawler, lines_of, main, norm, split_list, text_of

SOURCE = "topcv"
BASE = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"

HEADER_LABELS = {
    "địa điểm": "place", "location": "place",
    "kinh nghiệm": "experience", "experience": "experience",
    "hạn ứng tuyển": "deadline", "deadline": "deadline",
}
GENERAL_LABELS = {
    "cấp bậc": "level", "level": "level",
    "học vấn": "education", "education": "education",
    "số lượng tuyển": "openings", "number of hires": "openings",
    "hình thức làm việc": "working_type", "working type": "working_type",
    "loại hình làm việc": "employment_type", "employment type": "employment_type",
}
TAG_GROUPS = {
    "yêu cầu": "requirement_tags", "requirements": "requirement_tags",
    "quyền lợi": "benefit_tags", "benefits": "benefit_tags",
    "chuyên môn": "specializations", "specialization": "specializations",
}
REQUIRED_TAGS = {
    "kiến thức ngành": "domain_knowledge", "domain knowledge": "domain_knowledge",
    "kỹ năng cần có": "skills_required", "required skills": "skills_required",
    "kỹ năng nên có": "skills_preferred", "preferred skills": "skills_preferred",
}
SECTIONS = {
    "description": ["mô tả công việc", "job description"],
    "requirements": ["yêu cầu ứng viên", "candidate requirements"],
    "benefits": ["quyền lợi ứng viên", "quyền lợi được hưởng", "quyền lợi", "benefits"],
}
ADDRESS_TIME_LABELS = {
    "địa điểm làm việc": "addresses", "location": "addresses",
    "thời gian làm việc": "working_hours", "work schedule": "working_hours",
}
COMPANY_LABELS = {
    "quy mô": "company_size", "company size": "company_size",
    "địa điểm": "company_address", "address": "company_address",
    "ngành nghề": "company_field", "industry": "company_field",
}


def label_values(node, item_sel: str, label_sel: str, value_sel: str, mapping: dict) -> dict:
    out = {}
    for item in node.select(item_sel):
        field = mapping.get(norm(text_of(item, label_sel)))
        if field and field not in out:
            out[field] = text_of(item, value_sel)
    return out


def parse_jsonld(soup) -> dict:
    tag = soup.select_one("script[type='application/ld+json']")
    if not tag or not tag.string:
        return {}
    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list):
        data = next((d for d in data if d.get("@type") == "JobPosting"), {})
    if data.get("@type") != "JobPosting":
        return {}

    locations = data.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    regions = [loc.get("address", {}).get("addressRegion") for loc in locations]

    salary = (data.get("baseSalary") or {}).get("value") or {}
    org = data.get("hiringOrganization") or {}
    exp = data.get("experienceRequirements") or {}

    return {
        "date_posted": data.get("datePosted"),
        "valid_through": data.get("validThrough"),
        "employment_type_code": data.get("employmentType"),
        "salary_value": salary.get("value"),
        "salary_min": salary.get("minValue"),
        "salary_max": salary.get("maxValue"),
        "salary_unit": salary.get("unitText"),
        "salary_currency": (data.get("baseSalary") or {}).get("currency"),
        "experience_months": exp.get("monthsOfExperience") if isinstance(exp, dict) else None,
        "industry": data.get("industry"),
        "skills": split_list(data.get("skills")),
        "location_regions": [r for r in regions if r],
        "ld_company_name": org.get("name"),
        "ld_company_url": org.get("sameAs"),
        "ld_level": data.get("occupationalCategory"),
        "ld_openings": data.get("totalJobOpenings"),
    }


def parse_sections(soup) -> dict:
    out = {name: None for name in SECTIONS}
    for h2 in soup.select(".box-job-information-detail-item__title--title"):
        title = norm(h2.get_text(" ", strip=True))
        for name, keywords in SECTIONS.items():
            if out[name] is None and title in keywords:
                block = h2.find_parent(class_="box-job-information-detail-item")
                if block:
                    out[name] = lines_of(block, ".box-job-information-detail-item__text")
    return out


def parse_tag_groups(soup) -> dict:
    out = {field: [] for field in dict.fromkeys(TAG_GROUPS.values())}
    for group in soup.select(".job-tags__group"):
        field = TAG_GROUPS.get(norm(text_of(group, ".job-tags__group-name")))
        if field:
            out[field] = [a.get_text(" ", strip=True) for a in group.select(".job-tags__group-list-tag a")]
    return out


def parse_required_tags(soup) -> dict:
    out = {field: [] for field in dict.fromkeys(REQUIRED_TAGS.values())}
    for tag in soup.select(".required-tag"):
        field = REQUIRED_TAGS.get(norm(text_of(tag, ".required-tag__content--title")))
        if field:
            out[field] = split_list(text_of(tag, ".required-tag__content--desc"))
    return out


def parse_address_time(soup) -> dict:
    out = {field: [] for field in dict.fromkeys(ADDRESS_TIME_LABELS.values())}
    for item in soup.select(".box-job-information-address-and-time-list__item"):
        field = ADDRESS_TIME_LABELS.get(norm(text_of(item, ".box-job-information-address-and-time-list__item--title")))
        if field:
            out[field] = [li.get_text(" ", strip=True) for li in item.select("li")]
    return out


def parse_categories(soup) -> list[str]:
    for box in soup.select(".box-category"):
        if norm(text_of(box, ".box-title")) in ("danh mục nghề liên quan", "related categories"):
            return [a.get_text(" ", strip=True) for a in box.select(".box-category-tag")]
    return []


class TopCVCrawler(BaseCrawler):
    source = SOURCE

    def list_url(self, page: int) -> str:
        return f"{BASE}?sort=new&page={page}"

    def parse_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.select("h3.title > a"):
            href = a.get("href", "").split("?")[0]
            if href and href not in links:
                links.append(href)
        return links

    def job_id_from_url(self, url: str | None) -> str | None:
        match = re.search(r"(\d+)\.html$", url or "")
        return match.group(1) if match else None

    def parse_detail(self, html: str, url: str | None = None) -> dict | None:
        soup = BeautifulSoup(html, "lxml")
        ld = parse_jsonld(soup)

        job_title = text_of(soup, "h1.box-header-job__title")
        if not job_title:
            return None

        header = label_values(soup, ".box-header-job-list-info__item",
                              ".list-info__content__title", ".list-info__content__desc", HEADER_LABELS)
        general = label_values(soup, ".box-job-information-general-info-list__item",
                               ".box-job-information-general-info-list__item--content-title",
                               ".box-job-information-general-info-list__item--content-desc", GENERAL_LABELS)
        company = label_values(soup, ".box-company-info-detail__list--item",
                               ".box-company-info-detail__list--item-label",
                               ".box-company-info-detail__list--item-value", COMPANY_LABELS)
        company_link = soup.select_one(".box-company-info a.name, .company-name-label a")

        return {
            "source": SOURCE,
            "job_id": self.job_id_from_url(url),
            "job_url": url,
            "job_title": job_title,
            "salary": text_of(soup, ".box-header-job__salary--title") or ld.get("salary_value"),
            "place": header.get("place"),
            "experience": header.get("experience"),
            "deadline": header.get("deadline") or text_of(soup, ".box-applied-cv .date"),
            "level": general.get("level") or ld.get("ld_level"),
            "education": general.get("education"),
            "openings": general.get("openings"),
            "working_type": general.get("working_type"),
            "employment_type": general.get("employment_type"),
            **parse_tag_groups(soup),
            **parse_required_tags(soup),
            "job_categories": parse_categories(soup),
            **parse_sections(soup),
            **parse_address_time(soup),
            "company_name": (company_link.get_text(" ", strip=True) if company_link else None) or ld.get("ld_company_name"),
            "company_url": (company_link.get("href") if company_link else None) or ld.get("ld_company_url"),
            "company_size": company.get("company_size"),
            "company_field": company.get("company_field"),
            "company_address": company.get("company_address"),
            **{k: v for k, v in ld.items() if not k.startswith("ld_")},
            "crawled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


if __name__ == "__main__":
    main(TopCVCrawler)


