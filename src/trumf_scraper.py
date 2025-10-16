"""Command-line scraper for Trumf partner offers.

This module downloads current offers from Meny, Spar, Kiwi, Joker,
Norli and Mester Grønn. The scraper stores all collected offers in a
single CSV file located in the local ``data`` directory.

The script demonstrates a pragmatic approach to combining information
from traditional HTML pages with PDF based circulars. The Meny circular
is delivered as a PDF document and therefore requires text extraction.
The remaining stores expose offer information in HTML which is parsed
with BeautifulSoup.

Dependencies
------------
* requests
* beautifulsoup4
* pdfminer.six

Usage
-----
Run the scraper from the project root::

    python -m src.trumf_scraper

The script will create a timestamped CSV file in ``data/`` and print its
location.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass
class Offer:
    """Structured representation of a single offer line."""

    store: str
    title: str
    price: str | None = None
    extra: str | None = None

    def as_row(self) -> List[str]:
        return [self.store, self.title, self.price or "", self.extra or ""]


class ScraperError(RuntimeError):
    """Raised when a scraping routine fails."""


def fetch(url: str) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response


def parse_price_line(line: str) -> tuple[str, str | None]:
    """Split a text line into a probable title and price.

    This helper uses a simple heuristic that looks for Norwegian price
    patterns containing ``kr`` or comma separated decimals.
    """

    price_match = re.search(r"(\d+[\.,]\d{2}\s*kr?|kr\s*\d+[\.,]\d{2})", line, flags=re.I)
    if price_match:
        price = price_match.group(0).strip()
        title = line.replace(price_match.group(0), "").strip(" -:")
        return title or line.strip(), price
    return line.strip(), None


def scrape_meny() -> Iterable[Offer]:
    page = fetch("https://kundeavis.meny.no/")
    soup = BeautifulSoup(page.text, "html.parser")

    candidate_attrs = ("href", "src", "data-src", "data-href")
    pdf_url = None
    for tag in soup.find_all(True):
        for attr in candidate_attrs:
            value = tag.get(attr)
            if not value:
                continue
            if ".pdf" in value.lower():
                pdf_url = urljoin(page.url, value)
                break
        if pdf_url:
            break

    if not pdf_url:
        # Fallback: search for embedded URLs inside inline scripts or JSON
        # blobs. Some deployments reference the PDF via configuration objects
        # instead of DOM elements, so we attempt a raw regex lookup.
        match = re.search(r"https?://[^\s'\"<>]+\.pdf(?:\?[^'\"<>]*)?", page.text)
        if match:
            pdf_url = match.group(0)
        else:
            match = re.search(r"['\"]([^'\"]+\.pdf(?:\?[^'\"]*)?)['\"]", page.text)
            if match:
                pdf_url = urljoin(page.url, match.group(1))

    if not pdf_url:
        raise ScraperError("Fant ikke PDF-lenken på Meny-siden.")

    pdf_response = fetch(pdf_url)
    pdf_text = extract_text(BytesIO(pdf_response.content))
    offers: List[Offer] = []
    for raw_line in pdf_text.splitlines():
        clean = raw_line.strip()
        if not clean:
            continue
        if re.search(r"\d", clean):
            title, price = parse_price_line(clean)
            offers.append(Offer(store="Meny", title=title, price=price))
    return offers


def _extract_etilbudsavis_offers(html: str, store_name: str) -> Iterable[Offer]:
    soup = BeautifulSoup(html, "html.parser")
    offers: List[Offer] = []

    # Newer versions of etilbudsavis.no expose data inside __NEXT_DATA__
    data_tag = soup.find("script", id="__NEXT_DATA__")
    if data_tag and data_tag.string:
        try:
            data = json.loads(data_tag.string)
            catalogue = data["props"]["pageProps"].get("catalogue")
            if catalogue:
                items = catalogue.get("offers") or catalogue.get("items")
                if isinstance(items, list):
                    for item in items:
                        title = item.get("heading") or item.get("title") or item.get("name")
                        price = item.get("priceText") or item.get("price")
                        description = item.get("description") or item.get("subtitle")
                        if title:
                            offers.append(
                                Offer(
                                    store=store_name,
                                    title=title.strip(),
                                    price=str(price).strip() if price else None,
                                    extra=description.strip() if isinstance(description, str) else None,
                                )
                            )
        except (KeyError, ValueError, TypeError):
            pass

    # Fallback: parse visible offer cards
    for card in soup.select("[class*=OfferCard]"):
        title = card.find(["h2", "h3", "h4"])
        price = card.find(class_=re.compile("price", re.I))
        extra = card.find(class_=re.compile("description|subtitle", re.I))
        if title:
            offers.append(
                Offer(
                    store=store_name,
                    title=title.get_text(strip=True),
                    price=price.get_text(strip=True) if price else None,
                    extra=extra.get_text(strip=True) if extra else None,
                )
            )

    return offers


def scrape_etilbudsavis(store_slug: str, store_name: str) -> Iterable[Offer]:
    url = f"https://etilbudsavis.no/{store_slug}"
    response = fetch(url)
    return _extract_etilbudsavis_offers(response.text, store_name)


def scrape_spar() -> Iterable[Offer]:
    errors: List[str] = []
    for slug in ("Spar", "Meny"):
        try:
            offers = list(scrape_etilbudsavis(slug, "Spar"))
            if offers:
                return offers
        except Exception as exc:  # pragma: no cover - defensive logging
            errors.append(f"{slug}: {exc}")
    if errors:
        raise ScraperError("; ".join(errors))
    return []


def scrape_norli() -> Iterable[Offer]:
    response = fetch("https://www.norli.no/kampanje/tilbud")
    soup = BeautifulSoup(response.text, "html.parser")
    offers: List[Offer] = []

    for item in soup.select(".product-item-info"):
        title_el = item.select_one(".product-item-link")
        price_el = item.select_one(".price")
        extra_el = item.select_one(".special-price .price")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            continue
        base_price = price_el.get_text(strip=True) if price_el else None
        special = extra_el.get_text(strip=True) if extra_el else None
        offers.append(
            Offer(
                store="Norli",
                title=title,
                price=special or base_price,
                extra=f"Førpris: {base_price}" if special and base_price else None,
            )
        )

    return offers


def scrape_mester_gronn() -> Iterable[Offer]:
    response = fetch("https://www.mestergronn.no/mg/ukens-tilbud.html")
    soup = BeautifulSoup(response.text, "html.parser")
    offers: List[Offer] = []

    for block in soup.select(".mg-box"):
        title_el = block.find(["h2", "h3"])
        price_el = block.find(class_=re.compile("pris|price", re.I))
        desc_el = block.find("p")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            continue
        offers.append(
            Offer(
                store="Mester Grønn",
                title=title,
                price=price_el.get_text(strip=True) if price_el else None,
                extra=desc_el.get_text(strip=True) if desc_el else None,
            )
        )

    return offers


SCRAPERS = [
    scrape_meny,
    scrape_spar,
    lambda: scrape_etilbudsavis("KIWI", "Kiwi"),
    lambda: scrape_etilbudsavis("Joker", "Joker"),
    scrape_norli,
    scrape_mester_gronn,
]


def collect_offers() -> List[Offer]:
    offers: List[Offer] = []
    for scraper in SCRAPERS:
        try:
            offers.extend(list(scraper()))
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"Advarsel: klarte ikke hente tilbud: {exc}")
    return offers


def write_csv(rows: Iterable[Offer], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["butikk", "tittel", "pris", "ekstrainfo"])
        for offer in rows:
            writer.writerow(offer.as_row())


def main() -> None:
    offers = collect_offers()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = Path("data") / f"trumf-tilbud-{timestamp}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(offers, output_path)
    print(f"Lagret {len(offers)} tilbud i {output_path}")


if __name__ == "__main__":
    main()
