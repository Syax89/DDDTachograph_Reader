# DDD Tachograph — Complete Specification Reference

> Generated: 2026-06-09  
> Source: Reg. 2016/799 Annex 1C (consolidated), Reg. 2021/1228, Reg. 2023/980, ASN.1

## Legend

| Status | Meaning |
|--------|---------|
| ✅ SPEC | Byte-level structure confirmed from regulation/ASN.1 |
| ⚠️ ESTIMATED | Structure derived from spec fields, exact byte size unconfirmed |
| ❌ NONE | No public specification exists |

---

## G1/G2 Common Card Data

| Tag | Name | Bytes | Annex Ref | Status | Decoder |
|-----|------|-------|-----------|--------|---------|
| 0x0001 | VU_VehicleIdentification | 32 | Annex 1B §2.15 | ✅ SPEC | `parse_vu_vehicle_identification` |
| 0x0002 | EF_ICC | 24+ | Annex 1B §2.7 | ✅ SPEC | `parse_ef_icc` |
| 0x0005 | EF_IC | 8 | Annex 1B §2.6 | ✅ SPEC | `parse_ef_ic` |
| 0x0100 | CardIssuerIdentification | — | — | ❌ NONE | `parse_card_issuer_identification` |
| 0x0101 | G2_CardIccIdentification | 24+ | Annex 1C §2.23 | ✅ SPEC | `parse_g2_card_icc_identification` |
| 0x0102 | G2_CardIdentification | 65 | Annex 1B §2.15 | ✅ SPEC | `parse_card_identification` |
| 0x0103 | G2_CardCertificate | 194 | Annex 1C §2.30 | ✅ SPEC | `parse_g1_certificate` |
| 0x0104 | G2_MemberStateCertificate | 194 | Annex 1C §2.31 | ✅ SPEC | `parse_g1_certificate` |
| 0x0201 | DriverCardHolderIdentification | 78 | Annex 1B §2.17 | ✅ SPEC | `parse_driver_card_holder_identification` |
| 0x0206 | VU_ActivityDailyRecord | var | Annex 1C | ✅ SPEC | `parse_cyclic_buffer_activities` |
| 0x0420 | G22_CertificateProfileId | var | Reg. EU 2023/980 | ⚠️ ESTIMATED | `parse_g22_certificate_profile` |

### DriverCardApplicationIdentification — G1 vs G2

| Gen | Bytes | Fields |
|-----|-------|--------|
| **G1** | **10** | typeOfTachographCardId(1) + cardStructureVersion(2) + noOfEventsPerType(1) + noOfFaultsPerType(1) + activityStructureLength(2) + noOfCardVehicleRecords(2) + noOfCardPlaceRecords(1) |
| **G2** | **15** | G1 fields + noOfBorderCrossingRecords + noOfLoadUnloadRecords + noOfLoadTypeEntryRecords + vuConfigurationLengthRange |

Note: G2 cards may contain mixed G1 and G2 segments. Detection is per-segment via applicationIdentification byte size (10=G1, 15=G2).

## G1 Card Data Tags

| Tag | Name | Bytes | Annex Ref | Status | Decoder |
|-----|------|-------|-----------|--------|---------|
| 0x0501 | DriverCardApplicationIdentification | 10 | Annex 1B §2.28 | ✅ SPEC | `parse_g1_app_identification` |
| 0x0502 | CardEventData | 24×N | Annex 1B §2.20 | ✅ SPEC | `parse_g1_events_data` |
| 0x0503 | CardFaultData | 24×N | Annex 1B §2.21 | ✅ SPEC | `parse_g1_faults_data` |
| 0x0504 | DriverActivityData | var | Annex 1B §2.32 | ✅ SPEC | `parse_cyclic_buffer_activities` |
| 0x0505 | VehiclesUsed (G1) | 31×N | Annex 1B §2.19 | ✅ SPEC | `parse_g1_vehicles_used` |
| 0x0506 | CardPlaceDailyWorkPeriod | 10/13/27 | Annex 1B §2.22 | ✅ SPEC | `parse_g1_places` |
| 0x0507 | CurrentUsage | 19 | Annex 1B §2.23 | ✅ SPEC | `parse_g1_current_usage` |
| 0x0508 | ControlActivityData | 46 | Annex 1B §2.23 | ✅ SPEC | `parse_control_activity_data` |
| 0x050C | CalibrationData | 105/167 | Annex 1B §2.25 | ✅ SPEC | `parse_calibration_data` |
| 0x050E | CardDownload | 4×N | Annex 1B §2.18 | ✅ SPEC | `parse_card_download` |
| 0x0520 | CardIdentification+DriverID | 143 | Annex 1B §2.15+§2.17 | ✅ SPEC | `parse_g1_identification` |
| 0x0521 | DrivingLicenceInfo | 53 | Annex 1B §2.26 | ✅ SPEC | `parse_g1_driving_licence` |
| 0x0522 | SpecificConditions | 5×N | Annex 1B §2.27 | ✅ SPEC | `parse_specific_conditions` |
| 0x0523 | VehiclesUsed (G2) | 35×N | Annex 1C §2.19 | ✅ SPEC | `parse_g1_vehicles_used` |
| 0x0524 | DriverActivityData (G2) | var | Annex 1C §2.32 | ✅ SPEC | `parse_cyclic_buffer_activities` |
| 0x2020 | CompanyHolderData | — | — | ❌ NONE | `parse_company_holder_data` |

## G2/G2.2 VU Records (RecordArray)

| Tag | Name | Bytes | Annex Ref | Status | RecordType |
|-----|------|-------|-----------|--------|------------|
| 0x0509 | VuCardRecord | 29 | Annex 1C §4.5.3.2.8 | ✅ SPEC | — |
| 0x050A | VuCardIWRecord | 28 | Annex 1C §4.5.3.2.9 | ✅ SPEC | — |
| 0x050B | VuDownloadablePeriod | 8 | Annex 1C §4.5.3.2.10 | ✅ SPEC | — |
| 0x050D | VuTimeAdjustmentData | var (min 9) | Annex 1C §4.5.3.2.12 | ✅ SPEC | — |
| 0x050F | VuCompanyLocksData | 25 | Annex 1C §4.5.3.2.14 | ✅ SPEC | — |
| 0x0510 | SensorPairedData | 24 | Annex 1C §4.5.3.2.15 | ✅ SPEC | — |
| 0x0511 | SensorExternalGNSSCoupledData | 20 | Annex 1C §4.5.3.2.16 | ✅ SPEC | — |
| 0x0512 | VuITSConsentData | 23 | Annex 1C §4.5.3.2.17 | ✅ SPEC | — |

## G2.2 VU Records (RecordArray)

| Tag | Name | Bytes | Annex Ref | Status | RecordType |
|-----|------|-------|-----------|--------|------------|
| 0x052B | VuControllerIdentification | var | Annex 1C (amended) | ✅ SPEC | — |
| 0x052C | VuDetailedSpeedData | 64 | Annex 1C §2.190-2.191 | ✅ SPEC | — |
| 0x052D | VuOverSpeedingEventData | 33 | Annex 1C §2.215 | ⚠️ ESTIMATED | 0x08 |
| 0x052E | VuOverSpeedingControlData | 10 | Annex 1C §2.212 | ✅ SPEC | 0x09 |
| 0x052F | VuTimeAdjustmentGNSSRecord | 8 | Annex 1C §2.230 | ✅ SPEC | 0x0A |
| 0x0530 | VuPowerSupplyInterruptionData | 90 | Annex 1C §2.240 | ⚠️ ESTIMATED | 0x0B |
| 0x0531 | VuSensorFaultData | ~90 | — | ❌ NONE | 0x0C |
| 0x0532 | G22_SensorExternalGNSSCoupled | 20 | Annex 1C §2.242 | ✅ SPEC | — |
| 0x0533 | G22_SensorPairedData | 24 | Annex 1C §2.243 | ✅ SPEC | — |

## G2.2 Container Tags (BER-TLV)

| Tag | Name | Inner Format | Annex Ref | Status |
|-----|------|-------------|-----------|--------|
| 0x0525 | GNSSAccumulatedDriving | 13B flat records | Annex 1C §2.79 | ✅ SPEC |
| 0x0526 | LoadUnloadOperations | 13B flat records | Annex 1C §2.208a | ✅ SPEC |
| 0x0527 | TrailerRegistrations | 20B flat records | Annex 1C §2.166a | ✅ SPEC |
| 0x0528 | GNSSEnhancedPlaces | 14B flat records | Annex 1C §2.79c | ✅ SPEC |
| 0x0529 | LoadSensorData | var single record | — | ❌ NONE |
| 0x052A | BorderCrossings | 14B flat records | Annex 1C §2.203a | ✅ SPEC |

## G2.2 EF Tags (VU internal)

| Tag | Name | Annex Ref | Status |
|-----|------|-----------|--------|
| 0x0222 | EF_GNSS_Places | Annex 1C GNSS | ✅ SPEC |
| 0x0223 | EF_GNSS_Accumulated_Position | Annex 1C GNSS | ✅ SPEC |
| 0x0225 | G22_VU_GNSSADRecord | Annex 1C §2.79 | ✅ SPEC |
| 0x0226 | G22_VU_LoadUnloadRecord | Annex 1C §2.208a | ✅ SPEC |
| 0x0227 | G22_VU_TrailerRecord | Annex 1C §2.166a | ✅ SPEC |
| 0x0228 | G22_VU_BorderCrossingRecord | Annex 1C §2.203a | ✅ SPEC |

## RecordType Codes (§2.120)

| Code | Type |
|------|------|
| 0x08 | VuOverSpeedingEventRecord |
| 0x09 | VuOverSpeedingControlData |
| 0x0A | VuTimeAdjustmentGNSSRecord |
| 0x0B | VuPowerSupplyInterruptionRecord |
| 0x0C | VuSensorFaultRecord |
| 0x22 | VuBorderCrossingRecord (G2.2) |
| 0x23 | VuLoadUnloadRecord (G2.2) |
| 0x24 | VehicleRegistrationIdentification (G2.2) |

## Certificate Tags

| Tag | Name | Bytes | Annex Ref | Status |
|-----|------|-------|-----------|--------|
| 0xC100 | G1_CardCertificate | 194 | Annex 1B §2.29 | ✅ SPEC |
| 0xC108 | G1_CA_Certificate | 194 | Annex 1B §2.30 | ✅ SPEC |
| 0xC101 | G2_CardCertificate | var | Annex 1C §2.30 | ✅ SPEC |
| 0xC109 | G2_CA_Certificate | var | Annex 1C §2.31 | ✅ SPEC |
| 0xC102 | G22_CardCertificate | var | Reg. EU 2023/980 | ✅ SPEC |
| 0xC10A | G22_CA_Certificate | var | Reg. EU 2023/980 | ✅ SPEC |

## BER-TLV Sub-tags (Certificate containers)

| Tag | Name | Bytes | Annex Ref | Status |
|-----|------|-------|-----------|--------|
| 0x5F20 | G22_CardHolderName | var | Annex 1C §2.17 | ✅ SPEC |
| 0x5F24 | G22_CardEffectiveDate | 4 | Annex 1C §2.24 | ✅ SPEC |
| 0x5F25 | G22_CardExpiryDate | 4 | Annex 1C §2.24 | ✅ SPEC |
| 0x5F29 | G22_CardIssuingMemberState | 1 | Annex 1C §2.24 | ✅ SPEC |
| 0x5F37 | G22_CertificateSignature | 64 | Annex 1C §2.31 | ✅ SPEC |
| 0x5F4C | G22_CardExtendedSerialNumber | var | Annex 1C §2.23 | ✅ SPEC |
| 0x7F49 | G22_PublicKeyInfo | var | Annex 1C §2.30 | ✅ SPEC |
| 0x960F | G22_GNSS_Auth_Data | — | — | ❌ NONE |
| 0x6399 | G22_Load_Unload_Auth | — | — | ❌ NONE |

## G1 VU Containers

| Tag | Name | Annex Ref | Status |
|-----|------|-----------|--------|
| 0x7601 | G1_VU_TechnicalData (Overview) | Annex 1B §4.5.3.2.2 | ✅ SPEC (433B prefix) |
| 0x7602 | G1_VU_Activities | Annex 1B §4.5.3.2.3 | ⚠️ PARTIAL |
| 0x7603 | G1_VU_EventsFaults | Annex 1B §4.5.3.2.4 | ✅ SPEC (82/83B records) |
| 0x7604 | G1_VU_Speed | Annex 1B §4.5.3.2.5 | ✅ SPEC |
| 0x7605 | G1_VU_TechnicalData | Annex 1B §4.5.3.2.6 | ⚠️ PARTIAL |

## G2/G2.2 Containers

| Tag | Name | Annex Ref |
|-----|------|-----------|
| 0x7621 | G2_ApplicationContainer | Annex 1C §4.5.3.2 |
| 0x7622 | G2_VU_Activities | Annex 1C §4.5.3.2.3 |
| 0x7623 | G2_VU_EventsFaults | Annex 1C §4.5.3.2.4 |
| 0x7624 | G2_VU_Speed | Annex 1C §4.5.3.2.5 |
| 0x7631 | G22_ApplicationContainer | Reg. EU 2023/980 |
| 0x7632 | G22_VU_Activities | Reg. EU 2023/980 |
| 0x7633 | G22_VU_EventsFaults | Reg. EU 2023/980 |
| 0x7634 | G22_VU_Speed | Reg. EU 2023/980 |
| 0x7D21 | G2_SecurityContainer | Annex 1C §4.5.3.2.7 |
| 0xAD21 | G2_SecurityContainer (alt) | Annex 1C §4.5.3.2.7 |
| 0x7F21 | G22_CardCertificateContainer | Reg. EU 2023/980 |
| 0x7F4E | G22_SecurityContainer | Reg. EU 2023/980 |

## Confirmed Data Type Sizes (§2.x)

| Type | Bytes | Annex Ref |
|------|-------|-----------|
| TimeReal | 4 | UInt32 BE, Unix seconds |
| Datef | 4 | BCD YYMMDD |
| NationNumeric | 1 | Country code |
| Name | 36 | CodePage(1) + Latin1(35) |
| CardNumber | 16 | CodePage(1) + Alphanumeric(15) |
| FullCardNumber | 18 | §2.73: cardType(1)+nation(1)+card(16) |
| FullCardNumberAndGeneration | 20 | §2.74: gen(1)+nation(1)+card(16)+repl(1)+renew(1) |
| InternationalString{N} | 1+N | CodePage(1) + Latin1(N) |
| VehicleRegistrationIdentification | 15 | §2.166: nation(1)+IntStr{13}(14) |
| VehicleIdentificationNumber | 17 | §2.165: ISO 3779 VIN |
| CardSlotsStatus | 1 | §2.34: bitfield |
| CurrentDateTime | 4 | §2.54: TimeReal |
| OdometerValueMidnight | 3 | §2.114: UInt24 |
| ActivityChangeInfo | 2 | §2.1: bit-packed UInt16 |
| MemberStateCertificate | 194 | §2.96: sig(128)+pk(58)+ref(8) |
| Signature (RSA) | 128 | §2.149 |

## OperationType (§2.114a)

| Value | Meaning |
|-------|---------|
| 0x00 | RFU |
| 0x01 | Load |
| 0x02 | Unload |
| 0x03 | Simultaneous load/unload |
