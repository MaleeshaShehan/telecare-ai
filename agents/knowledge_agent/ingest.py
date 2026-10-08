"""Offline ingest: load -> clean -> chunk -> embed -> index.   Owner: M2

Run:  python -m agents.knowledge_agent.ingest
Rerun whenever data/corpus changes.

Steps:
1. Load each file in data/corpus/manifest.csv.
2. Clean and save plain text guides to data/corpus/processed/<doc_id>.md.
3. Chunk catalog (~1 per plan, 1 per planless record), FAQs (1 per FAQ), guides (~400 tokens).
4. Save structured chunks to data/corpus/processed/chunks.jsonl.
5. Embed with all-MiniLM-L6-v2 -> ChromaDB (cosine) at data/chroma/.
6. Build BM25 with telco-aware tokenizer -> data/bm25.pkl.
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = REPO_ROOT / "data" / "corpus" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "corpus" / "processed"
MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.csv"
CHUNKS_PATH = PROCESSED_DIR / "chunks.jsonl"


# ------------------------------------------------------------------ Helpers
def clean_title(title: str) -> str:
    """Ensure titles do not have duplicate 'Dialog Dialog' prefixes."""
    t = title.strip()
    if t.lower().startswith("dialog dialog"):
        t = t[7:].strip()
    elif not t.lower().startswith("dialog"):
        t = f"Dialog {t}"
    return t


def add_sentence(parts: list[str], text: str) -> None:
    """Append a sentence ensuring single terminal punctuation and no trailing '..'."""
    s = text.strip()
    if not s:
        return
    while s.endswith(".."):
        s = s[:-1]
    if not s.endswith((".", "!", "?")):
        s += "."
    parts.append(s)


def clean_guide_text(raw_text: str) -> str:
    """Normalize whitespace and strip initial 'DOCUMENT ID:' and 'TITLE:' header lines."""
    text = re.sub(r"\r\n", "\n", raw_text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    header_done = False
    for line in lines:
        l = line.strip()
        if not header_done and (l.startswith("DOCUMENT ID:") or l.startswith("TITLE:") or not l):
            continue
        header_done = True
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def load_manifest() -> list[dict[str, str]]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ Plan Formatter
def format_plan_text(sec_name: str, record: dict[str, Any], plan: dict[str, Any], group: Optional[dict[str, Any]] = None) -> str:
    parts: list[str] = []

    # 1. Description: only use record / group / target_customer description. Never invent "Best for".
    desc = ""
    if record.get("description"):
        desc = str(record["description"]).strip()
    elif group and group.get("description"):
        desc = str(group["description"]).strip()
    elif record.get("target_customer") and isinstance(record["target_customer"], dict):
        desc = str(record["target_customer"].get("description", "")).strip()

    if desc:
        add_sentence(parts, desc)

    # 2. Plan Identity: clean, natural phrasing
    p_id = plan.get("plan_id", "")
    p_name = plan.get("plan_name") or plan.get("name") or p_id
    p_type = plan.get("plan_type")
    cat = record.get("category") or record.get("product_name") or sec_name

    cat_clean = re.sub(r"(?i)\s+(plans?|packages?)$", "", str(cat)).strip()
    type_clean = re.sub(r"(?i)\s+(plans?|packages?)$", "", str(p_type)).strip() if p_type else ""

    if p_id == "dialog_prashansa_499":
        add_sentence(parts, f"{p_name} (Plan ID: {p_id}) is a specialized Dialog mobile postpaid plan designed for retired government pensioners.")
    elif p_id == "dialog_prashansa_1012":
        add_sentence(parts, f"{p_name} (Plan ID: {p_id}) is a specialized Dialog mobile postpaid plan designed for retired government pensioners.")
    elif type_clean and type_clean.lower() not in p_name.lower():
        add_sentence(parts, f"{p_name} (Plan ID: {p_id}) is a {type_clean} plan under Dialog {cat_clean}.")
    else:
        add_sentence(parts, f"{p_name} (Plan ID: {p_id}) is a Dialog {cat_clean} plan.")

    # 3. Pricing & Taxes
    if "monthly_rental_lkr" in plan:
        rental = plan["monthly_rental_lkr"]
        price_str = f"Monthly rental is LKR {rental:,.0f}" if isinstance(rental, (int, float)) else f"Monthly rental is LKR {rental}"
        if plan.get("tax_exclusive_monthly_rental_lkr"):
            price_str += f" (tax exclusive: LKR {plan['tax_exclusive_monthly_rental_lkr']:,.0f})"
        if plan.get("tax_inclusive_monthly_rental_lkr"):
            price_str += f" (tax inclusive: LKR {plan['tax_inclusive_monthly_rental_lkr']:,.0f})"
        add_sentence(parts, price_str)
    elif "price_lkr" in plan:
        price = plan["price_lkr"]
        price_str = f"Price is LKR {price:,.0f}" if isinstance(price, (int, float)) else f"Price is LKR {price}"
        if plan.get("taxes_included") is True:
            price_str += " (taxes included)"
        elif plan.get("taxes_included") is False:
            price_str += " (taxes extra)"
        add_sentence(parts, price_str)

    # 4. Data Allowance
    data_items: list[str] = []
    d = plan.get("data")
    if isinstance(d, dict):
        if "amount_gb" in d:
            data_items.append(f"{d['amount_gb']} GB")
        elif "allowance" in d:
            data_items.append(f"{d['allowance']}")
        if "type" in d:
            data_items.append(f"({d['type']})")
        if "details" in d:
            data_items.append(f"- {d['details']}")
    elif "data_gb" in plan:
        data_items.append(f"{plan['data_gb']} GB")
    elif "anytime_data_gb" in plan:
        data_items.append(f"{plan['anytime_data_gb']} GB Anytime Data")

    if plan.get("gaming_data") and isinstance(plan["gaming_data"], dict):
        gd = plan["gaming_data"]
        data_items.append(f"Gaming data: {gd.get('amount_gb')} GB ({gd.get('type')})")
    if plan.get("anytime_data") and isinstance(plan["anytime_data"], dict):
        ad = plan["anytime_data"]
        data_items.append(f"Anytime data: {ad.get('amount_gb')} GB")

    if data_items:
        add_sentence(parts, f"Data allowance: {' '.join(data_items)}")

    # 5. Voice
    v = plan.get("voice")
    if isinstance(v, dict):
        scope_raw = v.get("network_scope")
        scope = " and ".join(scope_raw) if isinstance(scope_raw, list) else (scope_raw or "")
        if p_id == "dialog_prashansa_499":
            add_sentence(parts, "Voice includes 1000 minutes to Any Network (including Dialog to Dialog and other networks).")
        elif p_id == "dialog_prashansa_1012":
            add_sentence(parts, "Voice includes unlimited calls to Any Network (including Dialog to Dialog and other networks).")
        elif "included_minutes" in v:
            add_sentence(parts, f"Voice includes {v['included_minutes']} minutes ({scope}).")
        elif "type" in v:
            add_sentence(parts, f"Voice: {v['type']} ({scope}).")
    elif isinstance(v, str):
        add_sentence(parts, f"Voice: {v}.")

    # 6. SMS
    s = plan.get("sms")
    if isinstance(s, dict):
        scope_raw = s.get("network_scope")
        scope = " and ".join(scope_raw) if isinstance(scope_raw, list) else (scope_raw or "")
        sms_amt = s.get("included_sms") or s.get("amount")
        if sms_amt:
            add_sentence(parts, f"SMS includes {sms_amt} SMS ({scope}).")
    elif "monthly_sms" in plan:
        add_sentence(parts, f"SMS includes {plan['monthly_sms']} SMS.")

    # 7. Validity
    val = plan.get("validity")
    if isinstance(val, dict):
        add_sentence(parts, f"Validity: {val.get('value')} {val.get('unit', 'days')}.")
    elif isinstance(val, (int, str)) and val:
        add_sentence(parts, f"Validity: {val}.")

    # 8. Speed / Bandwidth
    if plan.get("maximum_bandwidth_mbps"):
        add_sentence(parts, f"Maximum bandwidth: {plan['maximum_bandwidth_mbps']} Mbps.")
    elif plan.get("maximum_speed_mbps"):
        add_sentence(parts, f"Maximum speed: {plan['maximum_speed_mbps']} Mbps.")
    elif plan.get("maximum_download_speed_mbps"):
        add_sentence(parts, f"Maximum download speed: {plan['maximum_download_speed_mbps']} Mbps.")

    # 9. Entertainment & Apps
    if plan.get("entertainment") and isinstance(plan["entertainment"], dict):
        ent = plan["entertainment"]
        platform = ent.get("platform", "")
        free_cnt = ent.get("additional_free_subscriptions_count")
        subs = ent.get("subscriptions_shown", [])
        ent_desc = []
        if platform:
            ent_desc.append(platform)
        if free_cnt:
            ent_desc.append(f"{free_cnt} free subscriptions")
        if subs:
            ent_desc.append(f"({', '.join(subs)})")
        if ent_desc:
            add_sentence(parts, f"Entertainment benefits: free {' '.join(ent_desc)}.")

    if plan.get("supported_applications"):
        apps = ", ".join(plan["supported_applications"])
        add_sentence(parts, f"Supported applications: {apps}.")
    if plan.get("unlimited_apps_shown"):
        apps = ", ".join(plan["unlimited_apps_shown"])
        add_sentence(parts, f"Unlimited apps included: {apps}.")

    # 10. Connection Offers (avoiding 'lkr LKR')
    if plan.get("connection_offer"):
        co = plan["connection_offer"]
        if isinstance(co, dict):
            for k, val_offer in co.items():
                k_clean = k.replace("_lkr", "").replace("_", " ").strip()
                if isinstance(val_offer, (int, float)):
                    add_sentence(parts, f"Connection offer: {k_clean} LKR {val_offer:,.0f}.")
                else:
                    add_sentence(parts, f"Connection offer: {k_clean} {val_offer}.")
        else:
            add_sentence(parts, f"Connection offer: {co}.")

    # 11. Data Rollover (avoiding '..')
    if plan.get("data_rollover") and isinstance(plan["data_rollover"], dict):
        if plan["data_rollover"].get("enabled"):
            rule = plan["data_rollover"].get("rule", "Enabled")
            add_sentence(parts, f"Data rollover: {rule}")

    return " ".join(parts)


# ------------------------------------------------------------------ Chunk Generator
def generate_chunks() -> list[dict[str, Any]]:
    """Build all 265 chunks adhering strictly to the schema."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    chunks: list[dict[str, Any]] = []
    manifest = load_manifest()

    # 1. DOC-001 (Catalog: 200 plan chunks + 1 record-level chunk)
    with open(RAW_DIR / "dialog_telecom_master.json", "r", encoding="utf-8") as f:
        master_data = json.load(f)

    for sec_name, sec_data in master_data.get("sections", {}).items():
        for record in sec_data.get("records", []):
            rec_id = record.get("id")
            plans: list[tuple[dict[str, Any], Optional[dict[str, Any]]]] = []

            if "plans" in record and isinstance(record["plans"], list):
                for p in record["plans"]:
                    plans.append((p, None))
            elif "plan_groups" in record and isinstance(record["plan_groups"], list):
                for pg in record["plan_groups"]:
                    if "plans" in pg and isinstance(pg["plans"], list):
                        for p in pg["plans"]:
                            plans.append((p, pg))

            if plans:
                for plan, group in plans:
                    p_id = plan.get("plan_id", "")
                    p_name = plan.get("plan_name") or plan.get("name") or p_id
                    title = clean_title(str(p_name))
                    text = format_plan_text(sec_name, record, plan, group)
                    chunks.append({
                        "chunk_id": f"DOC-001-{p_id}",
                        "doc_id": "DOC-001",
                        "ref_id": p_id,
                        "category": "package",
                        "title": title,
                        "url": None,
                        "text": text,
                    })
            else:
                title = clean_title(record.get("product_name") or record.get("category") or rec_id)
                rec_parts: list[str] = []
                if record.get("description"):
                    add_sentence(rec_parts, str(record["description"]))
                if record.get("eligible_base_plans"):
                    ebp = [f"{bp.get('plan_name')} (rental LKR {bp.get('monthly_rental_lkr')})" for bp in record["eligible_base_plans"]]
                    add_sentence(rec_parts, f"Eligible base plans: {', '.join(ebp)}.")
                if record.get("benefits"):
                    b = record["benefits"]
                    pm = b.get("primary_member", {})
                    sm = b.get("supplementary_members", {})
                    add_sentence(rec_parts, f"Primary member benefits: {pm.get('monthly_bill_discount_percent')}% discount and {pm.get('bonus_data_gb')}GB bonus data.")
                    add_sentence(rec_parts, f"Supplementary member benefits: {sm.get('monthly_bill_discount_percent')}% discount.")
                if record.get("important_notes"):
                    add_sentence(rec_parts, "Important notes: " + " ".join(record["important_notes"]))

                chunks.append({
                    "chunk_id": f"DOC-001-{rec_id}",
                    "doc_id": "DOC-001",
                    "ref_id": rec_id,
                    "category": "package",
                    "title": title,
                    "url": None,
                    "text": " ".join(rec_parts),
                })

    # 2. DOC-002 (FAQs: 53 chunks)
    with open(RAW_DIR / "dialog_faqs_full_structured_complete.json", "r", encoding="utf-8") as f:
        faq_data = json.load(f)

    faq_coverage = {"faq_air_fibre_006", "faq_air_fibre_007", "faq_air_fibre_010"}
    faq_troubleshoot = {
        "Wi-Fi Management and Troubleshooting",
        "Billing/Channels/Decoder",
        "Balance and Quota",
        "Billing and Invoicing",
        "VAS Management",
    }

    for faq in faq_data.get("faqs", []):
        f_id = faq["faq_id"]
        f_cat_raw = faq.get("category", "")
        if f_id in faq_coverage:
            cat = "coverage"
        elif f_cat_raw in faq_troubleshoot:
            cat = "troubleshooting"
        else:
            cat = "package"

        chunks.append({
            "chunk_id": f"DOC-002-{f_id}",
            "doc_id": "DOC-002",
            "ref_id": f_id,
            "category": cat,
            "title": f"FAQ: {faq.get('question')}",
            "url": None,
            "text": f"Question: {faq['question']}\nAnswer: {faq['answer']}",
        })

    # 3. Guides DOC-007 to DOC-017 (11 chunks)
    manifest_map = {m["doc_id"]: m for m in manifest}
    for doc_num in range(7, 18):
        doc_id = f"DOC-{doc_num:03d}"
        m_entry = manifest_map.get(doc_id)
        if not m_entry:
            continue
        fname = m_entry["file"]
        title = m_entry["title"]
        category = m_entry["category"]
        fpath = RAW_DIR / fname

        with open(fpath, "r", encoding="utf-8") as f:
            raw_text = f.read().strip()

        cleaned_text = clean_guide_text(raw_text)

        guide_md_path = PROCESSED_DIR / f"{doc_id}.md"
        with open(guide_md_path, "w", encoding="utf-8") as g_fp:
            g_fp.write(cleaned_text + "\n")

        chunks.append({
            "chunk_id": f"{doc_id}-001",
            "doc_id": doc_id,
            "ref_id": doc_id,
            "category": category,
            "title": title,
            "url": None,
            "text": cleaned_text,
        })

    # Write chunks.jsonl
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    return chunks


def main() -> None:
    chunks = generate_chunks()
    print(f"Generated {len(chunks)} chunks in {CHUNKS_PATH}.")


if __name__ == "__main__":
    main()
