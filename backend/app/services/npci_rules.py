"""NPCI UPI dispute rules, in one place, with their provenance.

WHY THIS IS A CONFIG BLOCK AND NOT INLINE CONSTANTS
----------------------------------------------------
These rules have changed three times in under two years. A reviewer must be able to see
exactly what the engine assumes and when that was last checked, without reading the
forecaster. Every value below carries the circular it came from.

VERIFIED 2026-08-27 against reporting on the NPCI circulars named below. Three points were
confirmed and one was found to be *more precise* than a plain reading suggests: the caps
are not keyed on an abstract "customer" and "merchant" but on specific identifiers --
CD1 counts against IFSC + account number, CD2 against payer VPA + payee VPA.

    Caps (10 / 5 per rolling 30 days)  NPCI circular dated 5 December 2023
    URCS auto-disposition              UPI OC No. 213 FY 2024-25, effective 15 Feb 2025
    RGNB good-faith re-raise           OC No. 184B/2025-2026, effective 15 July 2025

Re-verify before relying on these in anything that is not a demo.
"""

from __future__ import annotations

from datetime import timedelta

NPCI_RULES: dict = {
    # The date this file's contents were last checked against published circulars. It
    # travels with every forecast the system emits, so a stale rule set is visible in the
    # UI rather than silently assumed.
    "verified_on": "2026-08-27",
    # Exceeding either cap causes URCS to auto-reject the chargeback.
    "cap_per_customer_30d": 10,  # 11th chargeback on IFSC + account number -> CD1
    "cap_per_payer_payee_30d": 5,  # 6th on payer VPA + payee VPA -> CD2
    "cap_window": timedelta(days=30),
    "auto_reject_codes": {
        "CD1": "Exceeded 10 chargebacks per customer (IFSC + account) in a rolling 30-day window",
        "CD2": "Exceeded 5 chargebacks per payer-payee VPA pair in a rolling 30-day window",
    },
    # Remitting Bank Raising Good Faith Negative Chargeback: lets a remitting bank re-raise
    # a chargeback URCS auto-declined under CD1/CD2, without prior NPCI whitelisting.
    "rgnb_available": True,
    "rgnb_front_end_only": True,
    "rgnb_note": (
        "Front-end interface only. NPCI guidance states this must not be used to avoid "
        "compensation or penalty; misuse is treated as a violation."
    ),
    "sources": {
        "caps": "NPCI circular dated 5 December 2023",
        "auto_disposition": "UPI OC No. 213 FY 2024-25, effective 15 February 2025",
        "rgnb": "NPCI OC No. 184B/2025-2026, effective 15 July 2025",
    },
}

__all__ = ["NPCI_RULES"]
