import json
from pathlib import Path

from seleniumbase import SB

LIST_URL = (
    "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
    "?sort=new&type_keyword=1&disable_auto_detect_type_keyword=1"
    "&category_family=r257&saturday_status=0"
)

out = Path("data/sample/topcv_links.json")
out.parent.mkdir(parents=True, exist_ok=True)

with SB(uc=True) as sb:
    sb.uc_open_with_reconnect(LIST_URL, 4)
    print("title:", sb.get_title())

links = []                                    
out.write_text(json.dumps(links), encoding="utf-8")
print("Đã tạo", out)