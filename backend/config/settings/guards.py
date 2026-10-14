"""What must be true of the configuration before the app may run in production.

A plain function of the values, so it can be tested without loading production settings.
"""

MIN_SECRET_LENGTH = 50


def production_problems(
    *,
    secret_key: str,
    allowed_hosts: list[str],
    frontend_url: str,
    refresh_cookie_secure: bool,
    trust_proxy_headers: bool,
) -> list[str]:
    """Every reason these values are unsafe for production. Empty when there is none."""
    problems = []
    if len(secret_key) < MIN_SECRET_LENGTH or len(set(secret_key)) < 5 or "dev-only" in secret_key:
        problems.append(
            f"DJANGO_SECRET_KEY must be a random value of at least {MIN_SECRET_LENGTH} characters."
        )
    if not allowed_hosts or "*" in allowed_hosts:
        problems.append("DJANGO_ALLOWED_HOSTS must list the site's host names, without '*'.")
    if not frontend_url.startswith("https://"):
        problems.append("FRONTEND_URL must be an https:// address: it goes into emailed links.")
    if not refresh_cookie_secure:
        problems.append("AUTH_COOKIE_SECURE must not be switched off.")
    if not trust_proxy_headers:
        # Behind the proxy every request comes from the proxy's address, so rate limits
        # and the audit trail would treat all visitors as one.
        problems.append("TRUST_PROXY_HEADERS must be true: the app runs behind our proxy.")
    return problems
