import argparse
import json
import random
import re
from datetime import date, datetime
from itertools import count
from pathlib import Path

from bs4 import BeautifulSoup
from seleniumbase import SB

SOURCE = "itviec"
SITE = "https://itviec.com"
BASE = f"{SITE}/viec-lam-it"
EMPTY_PAGES_TO_STOP = 5
OPEN_RETRIES = 3
DEBUG_DIR = Path("data/debug")
CHALLENGE_TITLES = ("just a moment", "chờ một chút", "xác minh", "verify")
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


def list_url(page: int) -> str:
    return f"{BASE}?page={page}"


def absolute(href: str | None) -> str | None:
    if not href:
        return None
    href = href.split("?")[0]
    return SITE + href if href.startswith("/") else href


def parse_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select(".job-card h3 a"):
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
    return " ".join(el.get_text(" ", strip=True).split()) if el else None


def split_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r",\s*(?![^()]*\))", text) if p.strip()]


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
    out["company_url"] = absolute(link.get("href")) if link else None
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


def job_id_from_url(url: str | None) -> str | None:
    match = re.search(r"/(?:viec-lam-it|it-jobs)/([^/?#]+)", url or "")
    return match.group(1) if match else None


def parse_detail(html: str, url: str | None = None) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    ld = parse_jsonld(soup)

    job_title = text_of(soup, ".job-header-info h1") or text_of(soup, "h1")
    if not job_title:
        return None

    header = parse_header_info(soup)
    company = parse_company(soup)

    return {
        "source": SOURCE,
        "job_id": job_id_from_url(url),
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
