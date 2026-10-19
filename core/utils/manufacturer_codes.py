"""ManufacturerCode → manufacturer name, from the official JRC registry.

``ManufacturerCode`` is a single byte (Annex 1C Appendix 1 §2.94 for the smart
tachograph; §2.93 in the card layout). The value assignment is **not** in the
regulation: it is the registry the European Commission maintains at
https://dtc.jrc.europa.eu/dtc_manufacturer_code.php ("database registration to
be managed by the European Commission", §2.94). This module is a static copy of
that page, taken 2026-10 and covering **all 65 assigned codes**; there is no
networking at runtime and no refresh path.

The table maps a *code to the registered applicant's name only*. It does not
give any meaning to a manufacturer's proprietary diagnostic payload — the
3-byte ``manufacturerSpecificErrorCode`` of §2.95 stays opaque (see
``core/parser/vu_dispatcher.py``).

Codes that are absent here are either unassigned or a "no information"
sentinel ('00'H, 'FF'H, ...): they are reported as not registered, never
guessed.
"""
from __future__ import annotations

__all__ = ["MANUFACTURER_CODES", "MANUFACTURER_STATUS_NOT_REGISTERED",
           "MANUFACTURER_STATUS_REGISTERED", "MANUFACTURER_STATUSES",
           "REGISTRY_SOURCE", "manufacturer_name"]

#: Where the table below comes from (the registry page, not the regulation).
REGISTRY_SOURCE = "https://dtc.jrc.europa.eu/dtc_manufacturer_code.php"

#: Status of a decoded manufacturer-code byte: a registered code, or one the
#: registry does not assign (unassigned range or a "no information" sentinel).
MANUFACTURER_STATUS_REGISTERED = "registered"
MANUFACTURER_STATUS_NOT_REGISTERED = "not_registered"
MANUFACTURER_STATUSES = (MANUFACTURER_STATUS_REGISTERED,
                         MANUFACTURER_STATUS_NOT_REGISTERED)

#: ManufacturerCode byte → registered manufacturer name (65 entries).
MANUFACTURER_CODES: dict[int, str] = {
    0x10: 'Actia S.A.',
    0x11: 'Security Printing and Systems Ltd.',
    0x12: 'Austria Card Plastikkarten und Ausweissysteme GmbH (formerly Austria Card)',
    0x13: 'Agencija za komercijalnu djelatnost d.o.o (AKD)',
    0x14: 'ALIK Automotive GmbH',
    0x15: 'ASELSAN',
    0x16: 'Asia Tacho Kart LLC',
    0x17: 'Real Casa de la Moneda',
    0x18: 'BARBÉ S.R.L.',
    0x19: 'BogArt Sp. z o.o.',
    0x20: 'CETIS d.d.',
    0x21: 'certSIGN',
    0x22: 'RUE Cryptotech',
    0x23: 'Centr Modernizatcii Transporta OOO (CMT - LLC)',
    0x24: 'Pars Ar-Ge Ltd',
    0x25: 'CardPlus Oy (formely Cardplus Sverige AB)',
    0x26: 'CB Electronics Sp. z o.o.',
    0x28: 'Datakom',
    0x29: 'DVLA',
    0x30: 'IDEMIA The Netherlands BV (formerly Morpho BV - Sdu Identification B.V. - Enschedé/Sdu B.V.)',
    0x32: 'EFKON AG',
    0x35: 'Eurocard LLC',
    0x36: 'S.C. Ecomotive Development S.R.L.',
    0x38: 'Fábrica Nacional de Moneda y Timbre',
    0x39: 'First Print Yard',
    0x40: 'Giesecke & Devrient GmbH',
    0x43: 'Giesecke & Devrient GB Ltd.',
    0x44: 'Giesecke & Devrient sa/nv',
    0x45: 'GrafoCARD',
    0x48: 'Hungarian Banknote Printing Co. Ltd. (formerly PJRT)',
    0x49: 'Haug GmbH',
    0x4A: 'Hegard Sp. z o.o.',
    0x50: 'Imprimerie Nationale',
    0x51: 'Imprensa Nacional-Casa da Moeda, SA',
    0x52: 'InfoCamere S.C.p.A',
    0x53: 'Intellic Germany GmbH - ZF Group CVS (formerly Intellic GmbH)',
    0x55: 'INTELLIGENT TELEMATICS SYSTEMS FOR TRANSPORT (its-t.llc)',
    0x60: 'Kraftfahrt-Bundesamt (KBA)',
    0x61: 'KazTACHOnet LLP',
    0x68: 'LESIKAR a.s.',
    0x69: 'LEDA-SL',
    0x78: 'NAP automotive Produkte GmbH',
    0x79: 'NATIONAL BANK OF SERBIA',
    0x81: 'Morpho e-documents (formerly Sagem Orga - ORGA Kartensysteme GmbH)',
    0x82: 'ORGA Zelenograd ZAO',
    0x84: 'ORGA Kartensysteme GmbH',
    0x88: 'Asseco - Central Europe a.s. (formerly PVT a.s.)',
    0x89: 'Polska Wytwórnia Papierów Wartosciowych S.A. - PWPW S.A.',
    0x8A: 'Papiery Powlekane Pasaco Sp. z o.o.',
    0x98: 'TahoNetSoft',
    0xA1: 'AUMOVIO Germany GmbH (formerly Continental Automotive Technologies GmbH - Continental Automotive GmbH - Siemens AG - Siemens VDO Automotive - Siemens Automotive)',
    0xA2: 'Stoneridge Electronics AB',
    0xA3: 'Thales (formerly Gemalto, Schlumberger SEMA, Axalto)',
    0xA4: '3M Security Printing and Systems Ltd.',
    0xA5: 'STMicroelectronics - Incard Division',
    0xA6: 'STÁTNÍ TISKÁRNA CENIN, státní podnik',
    0xAB: 'T-Systems International GmbH',
    0xAC: 'Thales DIS Schweiz AG (formerly Gemalto AG, Trüb AG)',
    0xAD: 'Trüb Baltic AS',
    0xAE: 'TEMPEST a.s.',
    0xAF: 'Trueb - DEMAX PLC',
    0xB0: 'TAYROL LIMITED',
    0xB1: 'UŽDAROJI AKCINĖ BENDROVĖ "LODVILA"',
    0xD8: 'TOBB - The Union of Chambers and Commodity Exchanges of Türkiye (formely Union of Chambers and Commodity Exchanges of Turkey - TOBB)',
    0xE0: 'Turker Roll Paper Trade',
}


def manufacturer_name(code) -> str | None:
    """Registered name for a ``ManufacturerCode`` byte, or ``None``.

    ``None`` means "not a registered code" — unassigned, a sentinel such as
    '00'H/'FF'H, or a value outside the byte range. It never means "no error":
    the registry assigns identity, not diagnostics.
    """
    if not isinstance(code, int):
        return None
    return MANUFACTURER_CODES.get(code)
