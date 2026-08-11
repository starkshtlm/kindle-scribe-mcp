"""How a submission connection should be encrypted.

Its own module so the server and ./scribe cannot disagree about it. They run in
different places -- one in the container, one on your laptop -- and a doctor
that tests a different connection than the bridge makes would be worse than no
doctor at all.
"""


def submission_mode(port: int, override: str = "") -> str:
    """'ssl' for implicit TLS, 'starttls' to upgrade after connecting.

    465 is TLS from the first byte and 587 upgrades, which holds nearly
    everywhere; the override exists for the hosts where it does not.
    """
    override = (override or "").strip().lower()
    if override in ("ssl", "starttls"):
        return override
    return "ssl" if port == 465 else "starttls"
