"""Vocabulary that maps source-native names onto shared category/system names.

This is the only place where dataset vocabulary lives. It is derived from the
supplied schemas (table, collection and resource-id naming), not from any case
or label. Unknown names are never guessed: the normalizer keeps the native name
and reports an issue instead.
"""

from __future__ import annotations

import re

# resource_id prefix -> (category, system). Longest prefix wins ("customer_export" > "export").
RESOURCE_PREFIXES: dict[str, tuple[str, str]] = {
    "account": ("USER_PROFILE", "account_service"),
    "search": ("SEARCH_INDEX_ENTRY", "search_service"),
    "analytics": ("ANALYTICS_PROFILE", "analytics_platform"),
    "support": ("SUPPORT_MESSAGE", "support_platform"),
    "backup": ("BACKUP_ARCHIVE", "backup_service"),
    "export": ("USER_EXPORT", "export_service"),
    "customer_export": ("USER_EXPORT", "export_service"),
    "audit_record": ("SECURITY_AUDIT_LOG", "security_service"),
    "data_flow": ("DATA_FLOW", "integration_service"),
    "legal_hold": ("LEGAL_HOLD_RECORD", "legal_service"),
    "tombstone": ("ACCOUNT_TOMBSTONE", "identity_service"),
    "email_delivery": ("EMAIL_DELIVERY_LOG", "email_delivery_service"),
    "delivery_confirmation": ("EMAIL_DELIVERY_LOG", "downstream_delivery_service"),
    "cache": ("CACHE_ENTRY", "cache_service"),
    "marketing": ("MARKETING_PROFILE", "marketing_platform"),
}

# native collection / table / list name -> (category, system or None when the container names it)
COLLECTIONS: dict[str, tuple[str, str | None]] = {
    # generic record_json tables and JSON snapshot collections
    "customer_profiles": ("USER_PROFILE", "account_service"),
    "customer_profiles_primary": ("USER_PROFILE", "account_service"),
    "customer_profiles_failover_replica": ("USER_PROFILE", "account_service"),
    "customer_analytics_reports": ("ANALYTICS_PROFILE", "analytics_platform"),
    "customer_analytics_profiles": ("ANALYTICS_PROFILE", "analytics_platform"),
    "backup_catalog": ("BACKUP_ARCHIVE", "backup_service"),
    "backup_restore_entries": ("BACKUP_ARCHIVE", "backup_service"),
    "customer_export_jobs": ("USER_EXPORT", "export_service"),
    "customer_exports": ("USER_EXPORT", "export_service"),
    "deleted_customer_references": ("ACCOUNT_TOMBSTONE", "identity_service"),
    "connector_configurations": ("DATA_FLOW", "integration_service"),
    "connector_subscriptions": ("DATA_FLOW", "integration_service"),
    "retained_order_records": ("RETAINED_ORDER_RECORD", "legal_service"),
    "customer_search_documents": ("SEARCH_INDEX_ENTRY", "search_service"),
    "search_documents_primary": ("SEARCH_INDEX_ENTRY", "search_service"),
    "security_audit_events": ("SECURITY_AUDIT_LOG", "security_service"),
    "security_audit_records": ("SECURITY_AUDIT_LOG", "security_service"),
    "support_conversations": ("SUPPORT_MESSAGE", "support_platform"),
    "support_records": ("SUPPORT_MESSAGE", "support_platform"),
    "ticket_attachments": ("SUPPORT_ATTACHMENT", "support_platform"),
    # lists inside per-service exports (system comes from the service name)
    "profile_lookups": ("USER_PROFILE", None),
    "profiles": ("ANALYTICS_PROFILE", None),
    "restore_entries": ("BACKUP_ARCHIVE", None),
    "exports": ("USER_EXPORT", None),
    "connectors": ("DATA_FLOW", None),
    "index_queries": ("SEARCH_INDEX_ENTRY", None),
    "audit_records": ("SECURITY_AUDIT_LOG", None),
    "tickets": ("SUPPORT_MESSAGE", None),
}

# Categories that appear in lookup records as ``record_type`` pass through unchanged.
KNOWN_CATEGORIES = frozenset(c for c, _ in RESOURCE_PREFIXES.values()) | frozenset(
    c for c, _ in COLLECTIONS.values()
)

_PREFIX_PATTERN = "|".join(sorted((re.escape(p) for p in RESOURCE_PREFIXES), key=len, reverse=True))
# An id followed by "-word" is part of something longer (a file name or date), not an id.
RESOURCE_ID_RE = re.compile(rf"\b(?:{_PREFIX_PATTERN})_[0-9]+\b(?!-\w)")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
USER_ID_RE = re.compile(r"\buser_[0-9]+\b")
PHONE_RE = re.compile(r"\+\d[\d ()\-]{7,}\d")
EMAIL_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def category_for_resource(resource_id: str) -> tuple[str, str] | None:
    """(category, system) implied by a resource id's prefix, or ``None`` if unknown."""
    stem = re.sub(r"_[0-9]+$", "", resource_id)
    return RESOURCE_PREFIXES.get(stem)


# Source field -> canonical identifier type. Fields whose type depends on the
# value (for example ``correlation_key``) are classified by value shape instead.
IDENTIFIER_FIELDS: dict[str, str] = {
    "email": "email",
    "owner_email": "email",
    "customer_email": "email",
    "requester_email": "email",
    "phone": "phone",
    "owner_phone": "phone",
    "requester_phone": "phone",
    "email_hash": "email_hash",
    "full_name": "name",
    "name": "name",
    "display_name": "name",
    "requester_name": "name",
    "user_id": "user_id",
    "customer_reference": "customer_reference",
    # Who uploaded an attachment: the attachment belongs to that person (owner link).
    "uploaded_by": "email",
}
SUBJECT_KEY_FIELDS = frozenset(
    {
        "lookup_key",
        "lookup_value",
        "subject_key",
        "subject_ref",
        "subject_reference",
        "match_key",
        "correlation_key",
        "subject_selector",
        "matched_value",
        "query",
    }
)
