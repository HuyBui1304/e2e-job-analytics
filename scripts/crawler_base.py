import argparse
import json
import os
import random
import re
from datetime import date
from itertools import count
from pathlib import Path

from seleniumbase import SB

from src.utils.minio_client import get_s3

DEBUG_DIR = Path("data/debug")
LANDING_DIR = Path("data/landing")
CHALLENGE_TITLES = ("just a moment", "chờ một chút", "xác minh", "verify")
IN_DOCKER = os.environ.get("IN_DOCKER") == "1"


def norm(text: str | None) -> str:
    return (text or "").strip().rstrip(":").strip().lower()


def text_of(node, selector: str) -> str | None:
    el = node.select_one(selector)
    return " ".join(el.get_text(" ", strip=True).split()) if el else None


def lines_of(node, selector: str) -> str | None:
    el = node.select_one(selector)
    return el.get_text("\n", strip=True) if el else None


def split_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r",\s*(?![^()]*\))", text) if p.strip()]


def absolute(href: str | None, site: str) -> str | None:
    if not href:
        return None
    href = href.split("?")[0]
    return site + href if href.startswith("/") else href


def save_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def print_fill_rate(rows: list[dict]) -> None:
    print("\nTỉ lệ có dữ liệu theo trường:")
    for field in rows[0]:
        filled = sum(1 for r in rows if r.get(field) not in (None, "", []))
        print(f"  {field:<22} {filled}/{len(rows)}")


class BaseCrawler:
    source = ""
    empty_pages_to_stop = 5
    open_retries = 3
    page_sleep = (6, 12)

    def __init__(self, sb=None):
        self.sb = sb

    def list_url(self, page: int) -> str:
        raise NotImplementedError

    def parse_links(self, html: str) -> list[str]:
        raise NotImplementedError

    def job_id_from_url(self, url: str | None) -> str | None:
        raise NotImplementedError

    def parse_detail(self, html: str, url: str | None = None) -> dict | None:
        raise NotImplementedError

    def after_open(self, url: str) -> None:
        pass

    def wait_for(self, selector: str, timeout: int = 20) -> bool:
        try:
            self.sb.wait_for_element(selector, timeout=timeout)
            return True
        except Exception:
            print(f"  Chờ {timeout}s vẫn chưa thấy {selector}")
            return False

    def pause(self) -> None:
        self.sb.sleep(random.uniform(*self.page_sleep))

    def save_debug(self, name: str, html: str) -> None:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{self.source}_{name}.html").write_text(html, encoding="utf-8")

    def is_challenge(self) -> bool:
        title = (self.sb.get_title() or "").lower()
        return any(word in title for word in CHALLENGE_TITLES)

    def wait_for_human(self, timeout: int = 90) -> bool:
        print("  Trang yêu cầu xác minh. Hãy bấm xác nhận trên cửa sổ Chrome...")
        for _ in range(timeout // 3):
            self.sb.sleep(3)
            if not self.is_challenge():
                print("  Đã qua bước xác minh, chạy tiếp")
                return True
        return False

    def open_page(self, url: str, manual: bool = True) -> str | None:
        for attempt in range(1, self.open_retries + 1):
            try:
                self.sb.uc_open_with_reconnect(url, 4)
                if self.is_challenge() and not (manual and not IN_DOCKER and self.wait_for_human()):
                    print(f"  Bị chặn (lần {attempt}/{self.open_retries}), nghỉ {60 * attempt}s")
                    self.sb.sleep(60 * attempt)
                    continue
                self.after_open(url)
                return self.sb.get_page_source()
            except Exception as e:
                print(f"  Lỗi mở trang (lần {attempt}/{self.open_retries}): {e}")
                self.sb.sleep(5 * attempt)
        return None

    def fetch_list_page(self, page: int) -> list[str]:
        for attempt in range(1, 3):
            html = self.open_page(self.list_url(page))
            page_links = self.parse_links(html) if html else []
            if page_links:
                return page_links
            print(f"  Trang {page} chưa có link (lần {attempt}/2), tiêu đề tab: {self.sb.get_title()!r}")
            if html:
                self.save_debug(f"list_page_{page}", html)
            self.sb.sleep(10 * attempt)
        return []

    def crawl_links(self, max_pages: int | None = None, stop_after: int | None = None) -> list[str]:
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
            page_links = self.fetch_list_page(page)
            n_new = add(page_links)
            print(f"Trang {page}: {len(page_links)} link, {n_new} link mới")

            if n_new:
                failed_pages.extend(pending_empty)
                pending_empty = []
            else:
                pending_empty.append(page)
                if len(pending_empty) >= self.empty_pages_to_stop:
                    print(f"{self.empty_pages_to_stop} trang liên tiếp không có link mới, dừng")
                    break

            if stop_after is not None and len(all_links) >= stop_after:
                break
            self.pause()

        if failed_pages:
            print(f"\nThử lại các trang bị thiếu: {failed_pages}")
            self.sb.sleep(30)
            still_failed = []
            for page in failed_pages:
                page_links = self.fetch_list_page(page)
                n_new = add(page_links)
                print(f"Trang {page} (thử lại): {len(page_links)} link, {n_new} link mới")
                if not page_links:
                    still_failed.append(page)
                self.pause()
            if still_failed:
                print(f"Vẫn không lấy được các trang: {still_failed}")

        return all_links

    def fetch_detail(self, url: str) -> dict | None:
        for attempt in range(1, 3):
            html = self.open_page(url)
            job = self.parse_detail(html, url) if html else None
            if job:
                return job
            print(f"  Chưa đọc được trang (lần {attempt}/2), tiêu đề tab: {self.sb.get_title()!r}")
            if html:
                self.save_debug(self.job_id_from_url(url) or f"job_{attempt}", html)
            self.sb.sleep(10 * attempt)
        return None

    def crawl_details(self, links: list[str]) -> list[dict]:
        jobs = []
        for i, url in enumerate(links, start=1):
            job = self.fetch_detail(url)
            if job:
                jobs.append(job)
                print(f"[{i}/{len(links)}] OK  {job['job_title'][:70]}")
            else:
                print(f"[{i}/{len(links)}] BỎ QUA {url}")
            self.pause()
        return jobs

    landing_bucket = "landing"

    def landing_key(self, run_date: date) -> str:
        return f"source={self.source}/ingest_date={run_date.isoformat()}/jobs.jsonl"

    def landing_path(self, run_date: date) -> Path:
        return LANDING_DIR / self.landing_key(run_date)

    def upload_to_minio(self, path: Path, run_date: date) -> str:
        key = self.landing_key(run_date)
        get_s3().upload_file(str(path), self.landing_bucket, key)
        return f"s3a://{self.landing_bucket}/{key}"

    def run(self, run_date: date, limit: int | None = None, max_pages: int | None = None) -> Path:
        links = self.crawl_links(max_pages, stop_after=limit)
        if not links:
            raise RuntimeError("Không lấy được link nào: kiểm tra lại selector trang danh sách")
        links = links[:limit] if limit else links
        jobs = self.crawl_details(links)
        if not jobs:
            raise RuntimeError("Không lấy được job nào: kiểm tra lại selector trang chi tiết")
        out = self.landing_path(run_date)
        save_jsonl(jobs, out)
        print(f"\nĐã lưu {len(jobs)}/{len(links)} job vào {out}")
        print_fill_rate(jobs)
        uri = self.upload_to_minio(out, run_date)
        print(f"Đã upload lên MinIO: {uri}")
        return out


def main(crawler_cls: type[BaseCrawler]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--from-html", type=Path, default=None)
    args = parser.parse_args()

    if args.from_html:
        job = crawler_cls().parse_detail(args.from_html.read_text(encoding="utf-8"), url=None)
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return

    with SB(uc=True, locale_code="vi", xvfb=IN_DOCKER) as sb:
        crawler_cls(sb).run(args.date, limit=args.limit or None, max_pages=args.max_pages)
