from datetime import datetime, timezone
import json
import re


def preserve_document_versions(rows, cutoff):
    def parse(value):
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
                raise ValueError()
            return parsed
        except (ValueError, TypeError):
            raise ValueError("utc_seconds_required")

    boundary, identities, eligible = parse(cutoff), {}, []
    for row in rows:
        if not all(isinstance(row.get(key), str) and row[key] for key in ("publisher", "documentId", "version")) or not isinstance(row.get("contentHash"), str) or not re.fullmatch(r"[a-f0-9]{64}", row["contentHash"]):
            raise ValueError("invalid_document_identity")
        available = max(parse(row.get("publishedAt")), parse(row.get("firstSeenAt")))
        key = (row["publisher"], row["documentId"], row["version"])
        fingerprint = (row["contentHash"], row["publishedAt"], row["firstSeenAt"])
        if key in identities:
            if identities[key] != fingerprint:
                raise ValueError("conflicting_document_version")
            continue
        identities[key] = fingerprint
        if available <= boundary:
            eligible.append({**row, "availableAt": available.isoformat(timespec="milliseconds").replace("+00:00", "Z")})
    eligible.sort(key=lambda row: (row["availableAt"], json.dumps([row["publisher"], row["documentId"], row["version"]], ensure_ascii=False, separators=(",", ":"))))
    previous, result = {}, []
    for row in eligible:
        key = (row["publisher"], row["documentId"])
        prior = previous.get(key)
        if prior and prior["availableAt"] == row["availableAt"]:
            raise ValueError("ambiguous_revision_order")
        previous[key] = row
        status = "first_observation" if not prior else "unchanged_content" if prior["contentHash"] == row["contentHash"] else "changed_content"
        result.append({**row, "status": status})
    return result
