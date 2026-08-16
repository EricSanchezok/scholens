export function zoteroOAuthResultKey(value: string) {
  switch (value) {
    case "connected":
      return "result.connected" as const;
    case "zotero_oauth_expired":
      return "result.zotero_oauth_expired" as const;
    case "zotero_oauth_exchange_failed":
      return "result.zotero_oauth_exchange_failed" as const;
    case "zotero_permissions_insufficient":
      return "result.zotero_permissions_insufficient" as const;
    case "zotero_rate_limited":
      return "result.zotero_rate_limited" as const;
    case "zotero_unavailable":
      return "result.zotero_unavailable" as const;
    default:
      return "result.zotero_connection_failed" as const;
  }
}

export function zoteroSettingsErrorKey(value: string) {
  switch (value) {
    case "zotero_not_connected":
      return "errors.zotero_not_connected" as const;
    case "zotero_permissions_insufficient":
      return "errors.zotero_permissions_insufficient" as const;
    case "zotero_credentials_invalid":
      return "errors.zotero_credentials_invalid" as const;
    case "integration_credentials_unreadable":
      return "errors.integration_credentials_unreadable" as const;
    case "zotero_rate_limited":
      return "errors.zotero_rate_limited" as const;
    case "zotero_auto_import_requires_researcher":
      return "errors.zotero_auto_import_requires_researcher" as const;
    case "zotero_operation_active":
      return "errors.zotero_operation_active" as const;
    case "zotero_import_failed":
      return "errors.zotero_import_failed" as const;
    default:
      return "errors.zotero_unavailable" as const;
  }
}

export function zoteroLibraryErrorKey(value: string) {
  switch (value) {
    case "zotero_not_connected":
      return "errors.zotero_not_connected" as const;
    case "zotero_permissions_insufficient":
      return "errors.zotero_permissions_insufficient" as const;
    case "zotero_credentials_invalid":
      return "errors.zotero_credentials_invalid" as const;
    case "integration_credentials_unreadable":
      return "errors.integration_credentials_unreadable" as const;
    case "zotero_rate_limited":
      return "errors.zotero_rate_limited" as const;
    case "zotero_quota_exceeded":
      return "errors.zotero_quota_exceeded" as const;
    case "paper_quota_exceeded":
      return "errors.paper_quota_exceeded" as const;
    case "storage_quota_exceeded":
      return "errors.storage_quota_exceeded" as const;
    case "zotero_operation_active":
      return "errors.zotero_operation_active" as const;
    default:
      return "errors.zotero_unavailable" as const;
  }
}

export function zoteroOperationErrorKey(value: string) {
  switch (value) {
    case "zotero_item_not_found":
      return "errors.zotero_item_not_found" as const;
    case "zotero_item_not_supported":
      return "errors.zotero_item_not_supported" as const;
    case "zotero_pdf_unavailable":
      return "errors.zotero_pdf_unavailable" as const;
    case "zotero_pdf_encrypted":
      return "errors.zotero_pdf_encrypted" as const;
    case "zotero_pdf_too_large":
      return "errors.zotero_pdf_too_large" as const;
    case "zotero_pdf_unsafe_address":
      return "errors.zotero_pdf_unsafe_address" as const;
    case "zotero_rate_limited":
      return "errors.zotero_rate_limited" as const;
    case "zotero_credentials_invalid":
      return "errors.zotero_credentials_invalid" as const;
    case "zotero_credentials_rotated":
      return "errors.zotero_credentials_rotated" as const;
    case "zotero_operation_cancelled":
      return "errors.zotero_operation_cancelled" as const;
    default:
      return "errors.zotero_import_failed" as const;
  }
}
