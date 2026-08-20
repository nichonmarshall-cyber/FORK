"""
Strips identifying information from out of a UNT degree audit PDF and writes the 
extracted text as a figure.

run once, by hand when a new fixtureis needed, not imported by application and not part
of the test suite.

    python tools/redact_audit.py <path to pdf> <path to output figure>

A degree audit is an educational record. the pdfs themselves are not included in git
see .gitignore for details. What lands is a fixture, a figure of the text extracted
from the pdf, with identifying information redacted.

The gpa and credit hours are not redacted, because they are not identifying information.
The degree audit is a record of a student's academic progress, and the gpa and credit hours 
are not unique to an individual student, and the reconliation test requires them to be present.
"""

import re
import sys
from pathlib import Path

from pypdf import PdfReader

REDACTED_NAME = "SAMPLE,STUDENT A"
REDACTED_STUDENT_ID = "00000000"
REDACTED_JOB_ID = "00000000"

def redact(text: str) -> str:
    lines = text.split("\n")

    # The name is the first non-empty line of page one, in LAST,FIRST MIDDLE format.
    # Replacing it postionally rather than by pattern aviods buildinga name-shaped regex
    # that might match a course title

    for i, line in enumerate(lines):
        if line.strip():
            lines[i] = REDACTED_NAME
            break

    text = "\n".join(lines)

    #Header value row: date,time,program code,catalog year then the two numeri identifiers.
    
    text = re.sub(
        r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+[AP]M\s+\S+\s+\S+\s+\w+\s+\d{4}\s+)"
        r"(\d+)(\s+)(\d+)",
        lambda m: f"{m.group(1)}{REDACTED_STUDENT_ID}{m.group(3)}{REDACTED_JOB_ID}",
        text,
    )

    # The self-service URL embeds a base64 job-queue token that is tied to
    # the individual audit run.
    text = re.sub(
        r"(id=JobQueueRun)[!A-Za-z0-9+/=]+",
        r"\1REDACTED",
        text,
    )

    return text


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    source, destination = Path(sys.argv[1]), Path(sys.argv[2])
    raw = "\n".join(
        (page.extract_text() or "") for page in PdfReader(str(source)).pages
    )
    cleaned = redact(raw)

    leaked = []
    for line in cleaned.split("\n"):
        if re.search(r"\b\d{8}\b", line) and REDACTED_STUDENT_ID not in line:
            leaked.append(line.strip())
    if leaked:
        print("Refusing to write — possible identifier still present:")
        for line in leaked:
            print(f"  {line}")
        return 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(cleaned, encoding="utf-8")
    print(f"Wrote {destination} ({len(cleaned.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




