#!/usr/bin/env python3
"""Convert BibTeX entries into the site's publications.json format.

Takes a plain-text file containing BibTeX entries (the same content a .bib
file would have) and merges the converted entries into _data/publications.json,
skipping entries that are already present (matched by DOI or exact title).

Usage:
    python3 scripts/bibtex_to_json.py publications.txt
    python3 scripts/bibtex_to_json.py publications.txt --data _data/publications.json
    python3 scripts/bibtex_to_json.py publications.txt --dry-run

Entries missing volume/issue/pages get empty strings for those keys, which the
publication template treats as "not present". Entries recognized as arXiv
preprints get "arXiv preprint" as their Publication Title and a Url built
from the arXiv identifier.
"""

import argparse
import json
import re
import sys

ITEM_TYPES = {
    "article": "journalArticle",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "incollection": "bookSection",
    "book": "book",
    "phdthesis": "thesis",
    "techreport": "report",
    "unpublished": "manuscript",
}


def find_entries(text):
    """Yield (bibtex_type, body) for each @type{...} entry, braces balanced."""
    for match in re.finditer(r"@(\w+)\s*[{(]", text):
        bib_type = match.group(1).lower()
        start = match.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield bib_type, text[start + 1 : i]
                    break


def parse_fields(body):
    """Parse 'name = {value}' fields from an entry body.

    The citation key before the first comma is dropped; keys never contain
    commas, so the split is safe.
    """
    if "," not in body:
        return {}
    body = body.split(",", 1)[1]

    fields = {}
    i, n = 0, len(body)
    while i < n:
        match = re.compile(r"\s*(\w+)\s*=\s*").match(body, i)
        if not match:
            break
        name = match.group(1).lower()
        i = match.end()

        if i < n and body[i] == "{":
            depth, i = 1, i + 1
            start = i
            while i < n and depth > 0:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                if depth > 0:
                    i += 1
            value = body[start:i]
            i += 1
        elif i < n and body[i] == '"':
            i += 1
            start = i
            while i < n and body[i] != '"':
                i += 1
            value = body[start:i]
            i += 1
        else:
            match = re.compile(r"[^,}\s]+").match(body, i)
            if not match:
                break
            value = match.group(0)
            i = match.end()

        fields[name] = value.strip()

        while i < n and body[i] in " \t\r\n":
            i += 1
        if i < n and body[i] == ",":
            i += 1

    return fields


def clean(value):
    """Strip LaTeX braces and collapse whitespace."""
    value = value.replace("{", "").replace("}", "")
    value = value.replace("~", " ")
    return re.sub(r"\s+", " ", value).strip()


def as_number(value):
    """Return int when possible, else float, else empty string."""
    value = clean(value)
    if not value:
        return ""
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return ""


def format_authors(raw):
    """Convert BibTeX 'and'-separated authors to Zotero's 'Last, First; ...'."""
    authors = []
    for author in re.split(r"\s+and\s+", clean(raw)):
        if not author:
            continue
        if "," in author:
            last, first = author.split(",", 1)
            authors.append(f"{last.strip()}, {first.strip()}")
        else:
            parts = author.split()
            if len(parts) > 1:
                authors.append(f"{parts[-1]}, {' '.join(parts[:-1])}")
            else:
                authors.append(author)
    return "; ".join(authors)


def find_arxiv_id(fields):
    """Return the arXiv identifier of a preprint entry, or '' if not one.

    Recognizes the standard eprint/archivePrefix fields as well as the
    'arXiv preprint arXiv:<id>' journal convention (or an arXiv url).
    """
    eprint = clean(fields.get("eprint") or fields.get("arxivid") or "")
    prefix = clean(fields.get("archiveprefix", ""))
    if eprint and (not prefix or prefix.lower() == "arxiv"):
        return eprint

    for value in (
        fields.get("journal", ""),
        fields.get("booktitle", ""),
        fields.get("url", ""),
        fields.get("note", ""),
    ):
        match = re.search(r"arxiv:\s*(\S+)", value, re.IGNORECASE) or re.search(
            r"(\d{4}\.\d{4,5}(?:v\d+)?)", value
        )
        if match:
            return match.group(1)
    return ""


def to_entry(bib_type, fields):
    pages = re.sub(r"--+|-{2,}", "-", clean(fields.get("pages", "")))
    publication_title = clean(fields.get("journal") or fields.get("booktitle") or "")
    url = clean(fields.get("url", ""))
    arxiv_id = find_arxiv_id(fields)
    if arxiv_id:
        publication_title = "arXiv preprint"
        url = f"https://arxiv.org/abs/{arxiv_id}"
    return {
        "Item Type": ITEM_TYPES.get(bib_type, "journalArticle"),
        "Publication Year": as_number(fields.get("year", "")),
        "Author": format_authors(fields.get("author", "")),
        "Title": clean(fields.get("title", "")),
        "Short Title": clean(fields.get("shorttitle", "")),
        "Publication Title": publication_title,
        "DOI": clean(fields.get("doi", "")),
        "Url": url,
        "Date": clean(fields.get("year", "")),
        "Pages": pages,
        "Issue": as_number(fields.get("number", "")),
        "Volume": as_number(fields.get("volume", "")),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert BibTeX entries to the site's publications.json format."
    )
    parser.add_argument("input", help="text file containing BibTeX entries")
    parser.add_argument(
        "--data",
        default="_data/publications.json",
        help="path to publications.json (default: _data/publications.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print converted entries as JSON instead of writing to the data file",
    )
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        entries = [
            to_entry(bib_type, fields)
            for bib_type, body in find_entries(f.read())
            for fields in [parse_fields(body)]
        ]

    if not entries:
        print("No BibTeX entries found in", args.input)
        return 1

    if args.dry_run:
        print(json.dumps(entries, indent=4, ensure_ascii=False))
        return 0

    try:
        with open(args.data, encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []

    def key(entry):
        return (entry.get("DOI") or "") + "|" + entry.get("Title", "").lower()

    seen = {key(entry) for entry in existing}
    new_entries = [e for e in entries if key(e) not in seen and not seen.add(key(e))]

    if not new_entries:
        print("No new entries; all were already present in", args.data)
        return 0

    with open(args.data, "w", encoding="utf-8") as f:
        json.dump(existing + new_entries, f, indent=4, ensure_ascii=False)
        f.write("\n")

    print(f"Added {len(new_entries)} of {len(entries)} entries to {args.data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
