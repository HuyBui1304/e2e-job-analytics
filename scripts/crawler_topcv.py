import argparse
import json
import random
import re
from datetime import date, datetime
from itertools import count
from pathlib import Path

from bs4 import BeautifulSoup
from seleniumbase import SB

SOURCE = "topcv"
BASE = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
EMPTY_PAGES_TO_STOP = 5
OPEN_RETRIES = 3
DEBUG_DIR = Path("data/debug")
CHALLENGE_TITLES = ("just a moment", "chờ một chút", "xác minh", "verify")

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


def list_url(page: int) -> str:
    return f"{BASE}?sort=new&page={page}"


def parse_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("h3.title > a"):
        href = a.get("href", "").split("?")[0]
        if href and href not in links:
            links.append(href)
    return links


def is_challenge(sb) -> bool:
    title = (sb.get_title() or "").lower()
    return any(word in title for word in CHALLENGE_TITLES)


def wait_for_human(sb, timeout: int = 90) -> bool:
    print("  Trang yêu cầu xác minh. Hãy bấm xác nhận trên cửa sổ Chrome...")
    for _ in range(timeout // 3):
        sb.sleep(3)
        if not is_challenge(sb):
            print("  Đã qua bước xác minh, chạy tiếp")
            return True
    return False


def open_page(sb, url: str, manual: bool = True) -> str | None:
    for attempt in range(1, OPEN_RETRIES + 1):
        try:
            sb.uc_open_with_reconnect(url, 4)
            if is_challenge(sb):
                if manual and wait_for_human(sb):
                    return sb.get_page_source()
                print(f"  Bị chặn (lần {attempt}/{OPEN_RETRIES}), nghỉ {60 * attempt}s")
                sb.sleep(60 * attempt)
                continue
            return sb.get_page_source()
        except Exception as e:
            print(f"  Lỗi mở trang (lần {attempt}/{OPEN_RETRIES}): {e}")
            sb.sleep(5 * attempt)
    return None


def fetch_list_page(sb, page: int) -> list[str]:
    for attempt in range(1, 3):
        html = open_page(sb, list_url(page))
        page_links = parse_links(html) if html else []
        if page_links:
            return page_links
        print(f"  Trang {page} chưa có link (lần {attempt}/2), tiêu đề tab: {sb.get_title()!r}")
        if html:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            (DEBUG_DIR / f"list_page_{page}.html").write_text(html, encoding="utf-8")
        sb.sleep(10 * attempt)
    return []


def crawl_links(sb, max_pages: int | None = None, stop_after: int | None = None) -> list[str]:
    pages = count(1) if max_pages is None else range(1, max_pages + 1)
    all_links = []
    seen = set()
    pending_empty = []
    failed_pages = []

    def add(links: list[str]) -> int:
        new = [link for link in links if link not in seen]
        all_links.extend(new)
        seen.update(new)
        return len(new)

    for page in pages:
        page_links = fetch_list_page(sb, page)
        n_new = add(page_links)
        print(f"Trang {page}: {len(page_links)} link, {n_new} link mới")

        if n_new:
            failed_pages.extend(pending_empty)
            pending_empty = []
        else:
            pending_empty.append(page)
            if len(pending_empty) >= EMPTY_PAGES_TO_STOP:
                print(f"{EMPTY_PAGES_TO_STOP} trang liên tiếp không có link mới, dừng")
                break

        if stop_after is not None and len(all_links) >= stop_after:
            break
        sb.sleep(random.uniform(6, 12))

    if failed_pages:
        print(f"\nThử lại các trang bị thiếu: {failed_pages}")
        sb.sleep(30)
        still_failed = []
        for page in failed_pages:
            page_links = fetch_list_page(sb, page)
            n_new = add(page_links)
            print(f"Trang {page} (thử lại): {len(page_links)} link, {n_new} link mới")
            if not page_links:
                still_failed.append(page)
            sb.sleep(random.uniform(6, 12))
        if still_failed:
            print(f"Vẫn không lấy được các trang: {still_failed}")

    return all_links


def norm(text: str | None) -> str:
    return (text or "").strip().rstrip(":").strip().lower()


def text_of(node, selector: str) -> str | None:
    el = node.select_one(selector)
    return el.get_text(" ", strip=True) if el else None


def lines_of(node, selector: str) -> str | None:
    el = node.select_one(selector)
    return el.get_text("\n", strip=True) if el else None


def split_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r",\s*(?![^()]*\))", text) if p.strip()]


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


def job_id_from_url(url: str | None) -> str | None:
    match = re.search(r"(\d+)\.html$", url or "")
    return match.group(1) if match else None


def parse_detail(html: str, url: str | None = None) -> dict | None:
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
        "job_id": job_id_from_url(url),
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


def fetch_detail(sb, url: str) -> dict | None:
    for attempt in range(1, 3):
        html = open_page(sb, url)
        job = parse_detail(html, url) if html else None
        if job:
            return job
        print(f"  Chưa đọc được trang (lần {attempt}/2), tiêu đề tab: {sb.get_title()!r}")
        if html:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            name = job_id_from_url(url) or f"job_{attempt}"
            (DEBUG_DIR / f"{name}.html").write_text(html, encoding="utf-8")
        sb.sleep(10 * attempt)
    return None


def crawl_details(sb, links: list[str]) -> list[dict]:
    jobs = []
    for i, url in enumerate(links, start=1):
        job = fetch_detail(sb, url)
        if job:
            jobs.append(job)
            print(f"[{i}/{len(links)}] OK  {job['job_title'][:70]}")
        else:
            print(f"[{i}/{len(links)}] BỎ QUA {url}")
        sb.sleep(random.uniform(6, 12))
    return jobs


def landing_path(run_date: date) -> Path:
    return Path("data/landing") / f"source={SOURCE}" / f"ingest_date={run_date.isoformat()}" / "jobs.jsonl"


def save_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def print_fill_rate(rows: list[dict]) -> None:
    print("\nTỉ lệ có dữ liệu theo trường:")
    for field in rows[0]:
        filled = sum(1 for r in rows if r.get(field) not in (None, "", []))
        print(f"  {field:<22} {filled}/{len(rows)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--from-html", type=Path, default=None)
    args = parser.parse_args()

    if args.from_html:
        job = parse_detail(args.from_html.read_text(encoding="utf-8"), url=None)
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return

    with SB(uc=True, locale_code="vi") as sb:
        links = crawl_links(sb, args.max_pages, stop_after=args.limit)
        if not links:
            raise RuntimeError("Không lấy được link nào: kiểm tra lại selector trang danh sách")
        links = links[: args.limit] if args.limit else links
        jobs = crawl_details(sb, links)

    if not jobs:
        raise RuntimeError("Không lấy được job nào: kiểm tra lại selector trang chi tiết")

    out = landing_path(args.date)
    save_jsonl(jobs, out)
    print(f"\nĐã lưu {len(jobs)}/{len(links)} job vào {out}")
    print_fill_rate(jobs)


if __name__ == "__main__":
    main()