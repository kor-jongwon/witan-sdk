# Errors and warnings

Every non-2xx answer becomes one of these exceptions, carrying the HTTP `status`, the server's message
and the parsed `body`. All of them derive from `WitanError`, so one `except WitanError` catches
everything the SDK raises.

::: witan_sdk.errors
    options:
      show_root_heading: false
      members_order: source

::: witan_sdk.SignatureError

::: witan_sdk.WitanDeprecationWarning
