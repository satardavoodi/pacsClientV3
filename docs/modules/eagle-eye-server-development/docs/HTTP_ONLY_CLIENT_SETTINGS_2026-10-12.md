# Ordinary Eagle connection settings

The Windows ordinary Eagle connection UI accepts an HTTP server address and port only. Reading an older HTTPS profile normalizes its scheme to HTTP without writing host configuration. Saving removes old device credential and certificate fields while preserving unrelated profile extensions. The changed URL/profile cache key prevents reuse of an old ordinary session; existing captured password context is retained for the next authenticated request.

Separate mobile-to-Windows Agent PACS pairing, QR and HTTPS settings are unchanged. Client parser compatibility is not an alternative ordinary UI transport choice. Source GUI acceptance and deployment remain pending.

Installed settings roles follow the installation edition; source-only role environment overrides do not reinterpret an installed Server. A separate guard preserves source-mode role overrides.
