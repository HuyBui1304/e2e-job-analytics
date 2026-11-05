import argparse
import json
import random
import re
from datetime import date, datetime
from itertools import count
from pathlib import Path

from bs4 import BeautifulSoup
from seleniumbase import SB

SOURCE = "careerviet"
SITE = "https://careerviet.vn"
BASE = f"{SITE}/viec-lam/cntt-phan-cung-mang-cntt-phan-mem-c63,1"
EMPTY_PAGES_TO_STOP = 5
OPEN_RETRIES = 3
DEBUG_DIR = Path("data/debug")
CHALLENGE_TITLES = ("just a moment", "chờ một chút", "xác minh", "verify")

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


def list_url(page: int) -> str:
    if page == 1:
        return f"{BASE}-vi.html"
    return f"{BASE}-trang-{page}-vi.html"


def absolute(href: str | None) -> str | None:
    if not href:
        return None
    href = href.split("?")[0]
    return SITE + href if href.startswith("/") else href


def parse_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select(".title h2 a.job_link"):
        href = absolute(a.get("href"))
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
            (DEBUG_DIR / f"{SOURCE}_list_page_{page}.html").write_text(html, encoding="utf-8")
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


def split_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r",\s*(?![^()]*\))", text) if p.strip()]


def parse_boxes(soup) -> dict:
    out = {}
    for item in soup.select(".detail-box li, .detail-box .map, .info-career ul.info li"):
        field = BOX_LABELS.get(norm(text_of(item, "strong, b")))
        if not field or field in out:
            continue
        if field == "job_categories":
            value = [a.get_text(" ", strip=True) for a in item.select("p a, .value a")]
        else:
            value = text_of(item, "p, .value")
        if value:
            out[field] = value
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


def job_id_from_url(url: str | None) -> str | None:
    match = re.search(r"\.([0-9A-Za-z]+)\.html$", url or "")
    return match.group(1) if match else None


def parse_detail(html: str, url: str | None = None) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    ld = parse_jsonld(soup)

    job_title = text_of(soup, ".job-desc h1.title") or text_of(soup, "h1")
    if not job_title:
        return None

    box = parse_boxes(soup)
    sections = parse_sections(soup)
    other = sections.pop("other")
    company_link = soup.select_one("a.job-company-name")

    return {
        "source": SOURCE,
        "job_id": job_id_from_url(url),
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
        "company_url": absolute(company_link.get("href")) if company_link else ld.get("ld_company_url"),
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
            (DEBUG_DIR / f"{SOURCE}_{name}.html").write_text(html, encoding="utf-8")
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
