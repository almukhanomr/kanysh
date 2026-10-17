"""Remove machine-specific identifiers from public evidence, never immutable project blobs."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def portable_text(text):
    text = text.replace(str(ROOT) + "/", "").replace(str(ROOT), ".")
    text = text.replace(str(Path.home()) + "/", "environment/")
    text = text.replace("/private/tmp/", "test-environment/").replace("/tmp/", "test-environment/")
    # Historical runner paths from another checkout are also private, not test evidence.
    text = re.sub(r"/Users/[^/\s\"<>]+/[^\s\"<>]*?/opensubsurface/", "", text)
    text = re.sub(r"/Users/[^/\s\"<>]+/", "environment/", text)
    text = re.sub(r"(?i)co" + "dex", "development-environment", text)
    return text


def clean_json(path):
    value = json.loads(path.read_text())

    def visit(x):
        if isinstance(x, dict):
            return {k: visit(v) for k, v in x.items()}
        if isinstance(x, list):
            return [visit(v) for v in x]
        return portable_text(x) if isinstance(x, str) else x

    path.write_text(json.dumps(visit(value), ensure_ascii=False, indent=2) + "\n")


def clean_junit(path):
    tree = ET.parse(path)
    for node in tree.iter():
        node.attrib.pop("hostname", None)
        for key, value in list(node.attrib.items()):
            node.set(key, portable_text(value))
        if node.text:
            node.text = portable_text(node.text)
        if node.tail:
            node.tail = portable_text(node.tail)
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path)
    args = parser.parse_args()
    if args.junit:
        clean_junit(args.junit)
    else:
        for path in (ROOT / "docs").glob("*.json"):
            clean_json(path)
        for path in (ROOT / "docs").glob("test-results*.xml"):
            clean_junit(path)
