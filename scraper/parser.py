"""Parse CNMC portability check response HTML."""

import logging
import re

logger = logging.getLogger(__name__)


def parse_result(html: str) -> dict[str, str] | None:
    """
    Extract phone, operator, and query date from CNMC response HTML.

    Returns dict with keys: phone, operator, query_date.
    Returns None on parse failure.
    """
    try:
        phone = _extract_field(html, r"[Nn]úmero\s+de\s+teléfono[^<]*?[>:]\s*([^<\n]+)")
        operator = _extract_field(html, r"[Oo]perador\s+actual[^<]*?[>:]\s*([^<\n]+)")
        query_date = _extract_field(html, r"[Ff]echa\s+(?:de\s+)?consulta[^<]*?[>:]\s*([^<\n]+)")

        if not phone and not operator:
            # Try table-based layout: <td>label</td><td>value</td>
            phone = _extract_table_field(html, r"[Nn]úmero\s+de\s+teléfono")
            operator = _extract_table_field(html, r"[Oo]perador\s+actual")
            query_date = _extract_table_field(html, r"[Ff]echa\s+(?:de\s+)?consulta")

        if not phone and not operator:
            # Check for error response
            error = _extract_error(html)
            if error:
                logger.error("CNMC returned error: %s", error)
            else:
                logger.error("Failed to parse CNMC response: no phone or operator found")
            return None

        result = {
            "phone": (phone or "").strip(),
            "operator": (operator or "").strip(),
            "query_date": (query_date or "").strip(),
        }
        logger.debug("Parsed result: %s", result)
        return result

    except Exception:
        logger.exception("Unexpected error parsing CNMC response")
        return None


def _extract_field(html: str, pattern: str) -> str | None:
    """Extract a field value using regex pattern."""
    match = re.search(pattern, html)
    if match:
        value = match.group(1).strip()
        # Remove any remaining HTML tags
        value = re.sub(r"<[^>]+>", "", value).strip()
        return value if value else None
    return None


def _extract_table_field(html: str, label_pattern: str) -> str | None:
    """Extract value from table row: <td>label</td><td>value</td>."""
    pattern = (
        r"<t[dh][^>]*>[^<]*" + label_pattern + r"[^<]*</t[dh]>\s*"
        r"<td[^>]*>\s*([^<]+?)\s*</td>"
    )
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if match:
        value = match.group(1).strip()
        return value if value else None
    return None


def _extract_error(html: str) -> str | None:
    """Extract error message from CNMC response."""
    # Common error patterns
    patterns = [
        r'class="[^"]*error[^"]*"[^>]*>([^<]+)<',
        r'class="[^"]*alert[^"]*"[^>]*>([^<]+)<',
        r"[Ee]rror[:\s]+([^<\n]+)",
        r"[Nn]o\s+se\s+ha\s+encontrado[^<\n]*",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1).strip() if match.lastindex else match.group(0).strip()
    return None
